"""Webhook de integração WhatsApp (Z-API, Evolution API, Meta Cloud API ou payload genérico)."""

import base64
import binascii
import logging
import re
import secrets
from typing import Any, Dict, List, Optional, Tuple

import requests
from fastapi import APIRouter, HTTPException, Query, Request, status
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import PlainTextResponse

from app.config import settings
from app.models.lancamento import OrigemDados
from app.models.webhook import MensagemWhatsApp, ResultadoMensagem, WebhookResponse
from app.services import firestore_service as fs
from app.services import gemini_service as gs

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/whatsapp", tags=["WhatsApp Webhook"])

META_GRAPH_URL = "https://graph.facebook.com/v20.0"


# ---------------------------------------------------------------------------
# Autenticação do webhook
# ---------------------------------------------------------------------------
def _token_recebido(request: Request) -> str:
    h = request.headers
    auth = h.get("authorization", "")
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return (
        h.get("x-webhook-token")
        or h.get("x-webhook-secret")
        or h.get("apikey")
        or request.query_params.get("token")
        or ""
    ).strip()


def _verificar_token(request: Request) -> None:
    if not settings.WEBHOOK_SECRET_TOKEN:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                            detail="WEBHOOK_SECRET_TOKEN não configurado no servidor.")
    token = _token_recebido(request)
    if not token or not secrets.compare_digest(token, settings.WEBHOOK_SECRET_TOKEN):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token do webhook inválido.")


# ---------------------------------------------------------------------------
# Parsers por provedor
# ---------------------------------------------------------------------------
def _digitos(valor: Any) -> str:
    return re.sub(r"\D", "", str(valor or "").split("@")[0])


def _parse_meta(payload: Dict[str, Any]) -> List[MensagemWhatsApp]:
    mensagens: List[MensagemWhatsApp] = []
    for entry in payload.get("entry", []) or []:
        for change in entry.get("changes", []) or []:
            value = change.get("value", {}) or {}
            nomes = {
                c.get("wa_id"): (c.get("profile") or {}).get("name")
                for c in value.get("contacts", []) or []
            }
            for m in value.get("messages", []) or []:
                tipo = m.get("type")
                msg = MensagemWhatsApp(
                    provedor="META",
                    message_id=m.get("id"),
                    telefone=_digitos(m.get("from")),
                    nome_contato=nomes.get(m.get("from")),
                )
                if tipo == "text":
                    msg.texto = (m.get("text") or {}).get("body", "")
                elif tipo in ("image", "audio", "document", "voice"):
                    media = m.get(tipo) or {}
                    msg.media_id = media.get("id")
                    msg.mime_type = media.get("mime_type")
                    msg.texto = media.get("caption", "") or ""
                mensagens.append(msg)
    return mensagens


def _parse_evolution(payload: Dict[str, Any]) -> List[MensagemWhatsApp]:
    evento = str(payload.get("event", "")).lower().replace("_", ".")
    if evento and "messages.upsert" not in evento:
        return []
    data = payload.get("data") or {}
    itens = data if isinstance(data, list) else [data]
    mensagens: List[MensagemWhatsApp] = []
    for d in itens:
        key = d.get("key") or {}
        jid = key.get("remoteJid", "")
        participante = key.get("participant") or d.get("participant")
        telefone = _digitos(participante if "@g.us" in jid and participante else jid)
        conteudo = d.get("message") or {}
        msg = MensagemWhatsApp(
            provedor="EVOLUTION",
            message_id=key.get("id"),
            telefone=telefone,
            nome_contato=d.get("pushName"),
            from_me=bool(key.get("fromMe")),
            texto=conteudo.get("conversation") or (conteudo.get("extendedTextMessage") or {}).get("text") or "",
        )
        for tipo in ("imageMessage", "audioMessage", "documentMessage"):
            media = conteudo.get(tipo)
            if media:
                msg.media_url = media.get("url")
                msg.mime_type = media.get("mimetype")
                msg.texto = media.get("caption") or msg.texto
                msg.media_base64 = conteudo.get("base64") or d.get("base64") or media.get("base64")
                break
        mensagens.append(msg)
    return mensagens


def _parse_zapi(payload: Dict[str, Any]) -> List[MensagemWhatsApp]:
    msg = MensagemWhatsApp(
        provedor="ZAPI",
        message_id=payload.get("messageId"),
        telefone=_digitos(payload.get("participantPhone") if payload.get("isGroup") else payload.get("phone")),
        nome_contato=payload.get("senderName") or payload.get("chatName"),
        from_me=bool(payload.get("fromMe")),
        texto=(payload.get("text") or {}).get("message", "") if isinstance(payload.get("text"), dict) else "",
    )
    for tipo, campo_url in (("image", "imageUrl"), ("audio", "audioUrl"), ("document", "documentUrl")):
        media = payload.get(tipo)
        if isinstance(media, dict) and media.get(campo_url):
            msg.media_url = media.get(campo_url)
            msg.mime_type = media.get("mimeType")
            msg.texto = media.get("caption") or msg.texto
            break
    return [msg]


def _parse_generico(payload: Dict[str, Any]) -> List[MensagemWhatsApp]:
    texto = payload.get("texto") or payload.get("message") or payload.get("text") or payload.get("body") or ""
    if isinstance(texto, dict):
        texto = texto.get("message") or texto.get("body") or ""
    return [MensagemWhatsApp(
        provedor="GENERICO",
        message_id=payload.get("message_id") or payload.get("id"),
        telefone=_digitos(payload.get("telefone") or payload.get("phone") or payload.get("from")),
        nome_contato=payload.get("nome") or payload.get("name") or payload.get("senderName"),
        from_me=bool(payload.get("from_me") or payload.get("fromMe")),
        texto=str(texto),
        media_url=payload.get("media_url") or payload.get("mediaUrl"),
        media_base64=payload.get("media_base64") or payload.get("base64"),
        mime_type=payload.get("mime_type") or payload.get("mimeType"),
    )]


def extrair_mensagens(payload: Dict[str, Any]) -> List[MensagemWhatsApp]:
    if payload.get("object") == "whatsapp_business_account" or "entry" in payload:
        return _parse_meta(payload)
    data = payload.get("data")
    if isinstance(data, (dict, list)) and ("event" in payload or "instance" in payload):
        return _parse_evolution(payload)
    if "phone" in payload and any(k in payload for k in ("text", "image", "audio", "document", "messageId")):
        return _parse_zapi(payload)
    return _parse_generico(payload)


# ---------------------------------------------------------------------------
# Download de mídia (somente em memória; nada é persistido)
# ---------------------------------------------------------------------------
def _baixar(url: str, headers: Optional[Dict[str, str]] = None) -> Tuple[bytes, str]:
    with requests.get(url, headers=headers or {}, timeout=30, stream=True) as resp:
        resp.raise_for_status()
        conteudo = bytearray()
        for bloco in resp.iter_content(chunk_size=64 * 1024):
            conteudo.extend(bloco)
            if len(conteudo) > settings.max_upload_bytes:
                raise ValueError(f"Mídia excede {settings.MAX_UPLOAD_MB} MB.")
        return bytes(conteudo), resp.headers.get("content-type", "")


def obter_bytes_midia(msg: MensagemWhatsApp) -> Tuple[bytes, str]:
    if msg.media_base64:
        b64 = msg.media_base64
        mime = msg.mime_type or ""
        if b64.startswith("data:"):
            cabecalho, b64 = b64.split(",", 1)
            mime = mime or cabecalho[5:].split(";")[0]
        try:
            return base64.b64decode(b64, validate=False), mime
        except (binascii.Error, ValueError) as exc:
            raise ValueError(f"Base64 de mídia inválido: {exc}") from exc

    if msg.media_id:
        if not settings.META_ACCESS_TOKEN:
            raise ValueError("META_ACCESS_TOKEN não configurado para baixar mídias da Meta Cloud API.")
        auth = {"Authorization": f"Bearer {settings.META_ACCESS_TOKEN}"}
        info = requests.get(f"{META_GRAPH_URL}/{msg.media_id}", headers=auth, timeout=20)
        info.raise_for_status()
        meta = info.json()
        dados, mime = _baixar(meta["url"], headers=auth)
        return dados, msg.mime_type or meta.get("mime_type") or mime

    if msg.media_url:
        dados, mime = _baixar(msg.media_url)
        return dados, msg.mime_type or mime

    raise ValueError("Mensagem sem mídia disponível.")


# ---------------------------------------------------------------------------
# Processamento
# ---------------------------------------------------------------------------
async def processar_mensagem(msg: MensagemWhatsApp) -> ResultadoMensagem:
    contexto: List[str] = []
    if msg.nome_contato or msg.telefone:
        contexto.append(f"Mensagem recebida via WhatsApp de {msg.nome_contato or 'contato'} ({msg.telefone or 'sem número'}).")

    arquivo_ref: Optional[str] = None
    if msg.tem_midia:
        dados, mime_bruto = await run_in_threadpool(obter_bytes_midia, msg)
        mime = gs.normalizar_mime(mime_bruto)
        if msg.texto:
            contexto.append(f"Legenda enviada junto com a mídia: {msg.texto}")
        extracao = await gs.extrair_de_midia(dados, mime, contexto=" ".join(contexto))
        origem = gs.origem_por_mime(mime)
        arquivo_ref = f"whatsapp:{msg.provedor}:{msg.media_url or msg.media_id or 'base64'} ({mime})"
    else:
        extracao = await gs.extrair_de_texto(msg.texto, contexto=" ".join(contexto))
        origem = OrigemDados.TEXTO

    normalizado = gs.normalizar_extracao(extracao)
    lancamento, cliente = await run_in_threadpool(
        fs.registrar_lancamento_extraido,
        normalizado,
        origem.value,
        None,
        msg.telefone or None,
        msg.nome_contato,
        arquivo_ref,
        msg.from_me,
    )
    return ResultadoMensagem(
        message_id=msg.message_id,
        status="SUCESSO",
        lancamento_id=lancamento["id"],
        cliente_id=cliente["id"],
        valor_total=lancamento["valor_total"],
        status_validacao=lancamento["status_validacao"],
    )


@router.get("/webhook", summary="Verificação de webhook (Meta Cloud API)", response_class=PlainTextResponse)
def verificar_webhook_meta(
    hub_mode: Optional[str] = Query(None, alias="hub.mode"),
    hub_verify_token: Optional[str] = Query(None, alias="hub.verify_token"),
    hub_challenge: Optional[str] = Query(None, alias="hub.challenge"),
):
    if (
        hub_mode == "subscribe"
        and settings.WEBHOOK_SECRET_TOKEN
        and hub_verify_token
        and secrets.compare_digest(hub_verify_token, settings.WEBHOOK_SECRET_TOKEN)
    ):
        return PlainTextResponse(hub_challenge or "")
    raise HTTPException(status_code=403, detail="Falha na verificação do webhook.")


@router.post("/webhook", response_model=WebhookResponse, summary="Recebe mensagens do provedor WhatsApp")
async def receber_webhook(request: Request):
    _verificar_token(request)
    try:
        payload = await request.json()
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail="Payload JSON inválido.") from exc
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="Payload deve ser um objeto JSON.")

    mensagens = [m for m in extrair_mensagens(payload) if m.processavel]
    if not mensagens:
        return WebhookResponse(status="IGNORADO", mensagem="Evento sem mensagem processável.")

    resultados: List[ResultadoMensagem] = []
    erros: List[str] = []
    for msg in mensagens:
        try:
            resultados.append(await processar_mensagem(msg))
        except Exception as exc:  # noqa: BLE001 - nunca derrubar o webhook do provedor
            logger.exception("Erro ao processar mensagem WhatsApp %s", msg.message_id)
            erros.append(str(exc))
            resultados.append(ResultadoMensagem(message_id=msg.message_id, status="ERRO", erro=str(exc)[:500]))

    status_final = "ERRO" if erros else "SUCESSO"
    try:
        log = await run_in_threadpool(
            fs.registrar_log_webhook, payload, status_final, " | ".join(erros) if erros else None
        )
        log_id = log["id"]
    except Exception:  # noqa: BLE001
        logger.exception("Falha ao gravar log do webhook")
        log_id = None

    # Responde 200 mesmo em erro de processamento para evitar tempestade de reenvios do provedor.
    return WebhookResponse(
        status=status_final,
        mensagem=f"{len(resultados) - len(erros)} mensagem(ns) processada(s), {len(erros)} erro(s).",
        log_id=log_id,
        resultados=resultados,
    )
