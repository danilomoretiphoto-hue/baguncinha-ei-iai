"""Integração com o Gemini 2.5 Flash via SDK oficial `google-genai`.

Responsável por:
- Enviar textos, imagens de comandas e áudios ao modelo com saída JSON estruturada;
- Normalizar/auditar a resposta (recalcular totais, detectar divergências, aplicar
  regras de confiança e coerência financeira) antes da persistência.
"""

import asyncio
import json
import logging
import mimetypes
import re
from typing import Any, Dict, List, Optional

from google import genai
from google.genai import types

from app.config import agora, settings
from app.models.lancamento import (
    ExtracaoIA,
    FormaPagamento,
    NivelConfianca,
    OrigemDados,
    StatusValidacao,
    TipoOperacao,
    TipoPagamento,
    coerencia_tipos,
    rebaixar_confianca,
)

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """Você é o motor de inteligência artificial financeira do comércio "Like Baguncinha", em Bebedouro - SP.
Sua missão é ler notas manuscritas, comanda em papel, comprovantes, tabelas ou ouvir áudios de pedidos/compras e converter TUDO em dados financeiros estruturados em JSON impecável.

REGRAS DE EXTRAÇÃO E INTERPRETAÇÃO:

IDENTIFICAÇÃO DE CLIENTE: Extraia o nome do cliente se citado. Se for cliente anônimo de balcão, defina como "Cliente Balcão".
CLASSIFICAÇÃO DE TIPO DE PAGAMENTO:
Se o texto/imagem indicar "marcar", "fiado", "anotar", "paga depois", "assinado": tipo_pagamento = "FIADO_A_RECEBER".
Se mencionar "pago no Pix", "dinheiro entregue", "passou cartão", "comprovante": tipo_pagamento = "PAGO".
Se for uma compra de insumo ou conta do próprio estabelecimento (luz, fornecedor, água): tipo_pagamento = "A_PAGAR".
ITENS E VALORES:
Liste todos os itens individualmente com quantidade, valor unitário e valor total do item.
Calcule a soma total dos itens. Se o valor total indicado na foto/áudio for diferente da soma calculada dos itens, defina divergencia_calculo: true e adicione um aviso explicativo em observacoes.
CONFIANÇA DE EXTRAÇÃO:
Retorne "ALTO" se a letra/áudio estiver legível/claro e todos os valores baterem perfeitamente.
Retorne "MEDIO" se houver rasura leve, palavra duvidosa ou pequena incerteza na quantidade.
Retorne "BAIXO" se o papel estiver muito rasgado, áudio abafado, letra ilegível ou divergência grave de valores.

Retorne EXATAMENTE no formato JSON correspondente ao esquema solicitado.

REGRAS COMPLEMENTARES DE PREENCHIMENTO DO ESQUEMA:
- tipo_operacao: "VENDA" para vendas a clientes (pagas ou fiado); "PAGAMENTO_FIADO" quando um cliente está quitando/abatendo uma dívida de fiado anterior (ex: "o João pagou 50 do fiado"); "DESPESA" para gastos do estabelecimento.
- forma_pagamento: use "FIADO" sempre que tipo_pagamento = "FIADO_A_RECEBER"; para pagamentos identifique PIX, DINHEIRO, CARTAO_CREDITO ou CARTAO_DEBITO ("cartão" sem especificar = CARTAO_DEBITO, com confiança no máximo MEDIO). Se não houver indicação de forma, use DINHEIRO e confiança no máximo MEDIO.
- Se o valor unitário não for citado, mas o total do item for, calcule valor_unitario = total do item / quantidade. Se apenas um preço for citado para vários itens iguais e não ficar claro se é unitário ou total, registre a dúvida em observacoes e use confiança MEDIO.
- Gírias de balcão: "real"/"conto"/"pila" = reais; "lata" = unidade; "x-tudo", "marmita", "pinga", "dose" são produtos.
- Valores monetários em reais, com ponto como separador decimal (ex: 12.5). Nunca use strings em campos numéricos.
- valor_total_informado: o total explicitamente escrito/falado (0 se não houver).
- valor_total: a soma exata dos valor_total_item.
- cliente_telefone: apenas dígitos se um telefone aparecer no conteúdo; caso contrário string vazia.
- Para DESPESA, coloque em cliente_nome o nome do fornecedor/credor (ex: "CPFL", "Distribuidora São Paulo").
- transcricao_raw: transcreva literalmente o conteúdo lido/ouvido.
- observacoes: string vazia se não houver nenhum aviso.
- Nunca invente itens ou valores que não estejam no conteúdo. Se algo estiver ilegível, registre em observacoes e reduza a confiança."""

MIME_ALIASES = {
    "image/jpg": "image/jpeg",
    "image/pjpeg": "image/jpeg",
    "audio/opus": "audio/ogg",
    "audio/x-opus+ogg": "audio/ogg",
    "audio/oga": "audio/ogg",
    "audio/x-wav": "audio/wav",
    "audio/wave": "audio/wav",
    "audio/vnd.wave": "audio/wav",
    "audio/mp3": "audio/mpeg",
    "audio/x-mp3": "audio/mpeg",
    "audio/x-m4a": "audio/mp4",
    "audio/m4a": "audio/mp4",
    "audio/x-aac": "audio/aac",
    "audio/x-flac": "audio/flac",
    "audio/x-aiff": "audio/aiff",
}

MIME_SUPORTADOS = {
    "image/jpeg", "image/png", "image/webp", "image/heic", "image/heif",
    "audio/wav", "audio/mpeg", "audio/aiff", "audio/aac", "audio/ogg",
    "audio/flac", "audio/mp4", "audio/webm",
    "application/pdf",
}

EXTENSOES_EXTRA = {
    ".ogg": "audio/ogg", ".opus": "audio/ogg", ".oga": "audio/ogg", ".m4a": "audio/mp4",
    ".webm": "audio/webm", ".heic": "image/heic", ".heif": "image/heif", ".webp": "image/webp",
    ".aac": "audio/aac", ".flac": "audio/flac", ".mp3": "audio/mpeg", ".wav": "audio/wav",
}

NOMES_BALCAO = {"cliente balcao", "balcao", "cliente anonimo", "anonimo", "consumidor", "consumidor final", ""}


class GeminiServiceError(Exception):
    """Falha na comunicação ou interpretação da resposta do Gemini."""


_client: Optional[genai.Client] = None


def get_client() -> genai.Client:
    global _client
    if not settings.GEMINI_API_KEY:
        raise GeminiServiceError("GEMINI_API_KEY não configurada no arquivo .env.")
    if _client is None:
        _client = genai.Client(api_key=settings.GEMINI_API_KEY)
    return _client


# ---------------------------------------------------------------------------
# Utilitários de MIME
# ---------------------------------------------------------------------------
def normalizar_mime(mime_type: Optional[str], filename: Optional[str] = None) -> str:
    """Normaliza o content-type (remove parâmetros como `; codecs=opus` e aplica aliases)."""
    mime = (mime_type or "").split(";")[0].strip().lower()
    mime = MIME_ALIASES.get(mime, mime)
    if (not mime or mime in {"application/octet-stream", "binary/octet-stream"}) and filename:
        ext = "." + filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
        mime = EXTENSOES_EXTRA.get(ext) or (mimetypes.guess_type(filename)[0] or "")
        mime = MIME_ALIASES.get(mime, mime)
    return mime


def mime_suportado(mime: str) -> bool:
    return mime in MIME_SUPORTADOS


def origem_por_mime(mime: str) -> OrigemDados:
    return OrigemDados.AUDIO_WHATSAPP if mime.startswith("audio/") else OrigemDados.IMAGEM_COMANDA


# ---------------------------------------------------------------------------
# Chamada ao modelo
# ---------------------------------------------------------------------------
def _config() -> types.GenerateContentConfig:
    return types.GenerateContentConfig(
        system_instruction=SYSTEM_PROMPT,
        response_mime_type="application/json",
        response_schema=ExtracaoIA,
        temperature=0.1,
    )


def _contexto(contexto_extra: Optional[str]) -> str:
    momento = agora()
    linhas = [
        f"Data e hora atual em Bebedouro - SP: {momento.strftime('%d/%m/%Y %H:%M')} ({momento.isoformat(timespec='seconds')}).",
    ]
    if contexto_extra:
        linhas.append(f"Contexto adicional: {contexto_extra.strip()}")
    return "\n".join(linhas)


def _parse_texto_json(texto: str) -> ExtracaoIA:
    limpo = texto.strip()
    limpo = re.sub(r"^```(?:json)?\s*", "", limpo)
    limpo = re.sub(r"\s*```$", "", limpo)
    return ExtracaoIA.model_validate(json.loads(limpo))


async def _gerar(contents: List[Any], tentativas: int = 3) -> ExtracaoIA:
    client = get_client()
    ultimo_erro: Optional[Exception] = None
    for tentativa in range(1, tentativas + 1):
        try:
            resposta = await client.aio.models.generate_content(
                model=settings.GEMINI_MODEL,
                contents=contents,
                config=_config(),
            )
            parsed = getattr(resposta, "parsed", None)
            if isinstance(parsed, ExtracaoIA):
                return parsed
            if isinstance(parsed, dict):
                return ExtracaoIA.model_validate(parsed)
            texto = getattr(resposta, "text", None)
            if not texto:
                raise GeminiServiceError("O Gemini retornou uma resposta vazia (possível bloqueio de segurança).")
            return _parse_texto_json(texto)
        except Exception as exc:  # noqa: BLE001 - retentativa genérica
            ultimo_erro = exc
            logger.warning("Falha na extração Gemini (tentativa %s/%s): %s", tentativa, tentativas, exc)
            if tentativa < tentativas:
                await asyncio.sleep(1.5 * tentativa)
    raise GeminiServiceError(f"Não foi possível extrair os dados via Gemini: {ultimo_erro}")


async def extrair_de_texto(texto: str, contexto: Optional[str] = None) -> ExtracaoIA:
    """Extrai dados financeiros estruturados a partir de texto livre."""
    if not texto or not texto.strip():
        raise GeminiServiceError("Texto vazio para extração.")
    contents = [
        _contexto(contexto),
        "Interprete a seguinte nota/mensagem de balcão e retorne o JSON estruturado:\n"
        f'"""\n{texto.strip()}\n"""',
    ]
    return await _gerar(contents)


async def extrair_de_midia(dados: bytes, mime_type: str, contexto: Optional[str] = None) -> ExtracaoIA:
    """Extrai dados de imagem de comanda, comprovante, PDF ou áudio de pedido."""
    if not dados:
        raise GeminiServiceError("Arquivo de mídia vazio.")
    if len(dados) > settings.max_upload_bytes:
        raise GeminiServiceError(f"Arquivo excede o limite de {settings.MAX_UPLOAD_MB} MB.")
    mime = normalizar_mime(mime_type)
    if not mime_suportado(mime):
        raise GeminiServiceError(f"Tipo de mídia não suportado pelo Gemini: '{mime or 'desconhecido'}'.")

    if mime.startswith("audio/"):
        instrucao = (
            "Ouça o áudio de pedido/compra acima. Transcreva-o integralmente em transcricao_raw "
            "e extraia os dados financeiros no JSON estruturado."
        )
    else:
        instrucao = (
            "Leia a imagem/documento acima (comanda, nota manuscrita, comprovante ou tabela). "
            "Transcreva o conteúdo em transcricao_raw e extraia os dados financeiros no JSON estruturado."
        )
    contents = [
        types.Part.from_bytes(data=dados, mime_type=mime),
        f"{_contexto(contexto)}\n\n{instrucao}",
    ]
    return await _gerar(contents)


# ---------------------------------------------------------------------------
# Auditoria / normalização pós-IA
# ---------------------------------------------------------------------------
def _norm_nome(nome: str) -> str:
    import unicodedata

    txt = unicodedata.normalize("NFKD", nome or "").encode("ascii", "ignore").decode("ascii")
    return " ".join(txt.lower().split())


def is_cliente_balcao(nome: Optional[str]) -> bool:
    return _norm_nome(nome or "") in NOMES_BALCAO


def _descricao_padrao(op: TipoOperacao) -> str:
    return {
        TipoOperacao.VENDA: "Venda avulsa (valor total)",
        TipoOperacao.PAGAMENTO_FIADO: "Pagamento de fiado",
        TipoOperacao.DESPESA: "Despesa do estabelecimento",
    }[op]


def normalizar_extracao(extracao: ExtracaoIA) -> Dict[str, Any]:
    """Audita a saída da IA aplicando as regras inegociáveis de balcão.

    - valor_total = soma(quantidade * valor_unitario) SEMPRE recalculado no servidor;
    - divergências entre total informado e soma geram `divergencia_calculo=True` + observação;
    - coerência entre tipo de operação, tipo e forma de pagamento;
    - confiança MEDIO/BAIXO => status PENDENTE_REVISAO; ALTO => APROVADO.
    """
    observacoes: List[str] = []
    if extracao.observacoes and extracao.observacoes.strip():
        observacoes.append(extracao.observacoes.strip())

    confianca = NivelConfianca(extracao.confianca_extracao)
    divergencia = bool(extracao.divergencia_calculo)

    op, tp, forma, avisos = coerencia_tipos(
        extracao.tipo_operacao, extracao.tipo_pagamento, extracao.forma_pagamento
    )
    if avisos:
        observacoes.extend(avisos)
        confianca = rebaixar_confianca(confianca, NivelConfianca.MEDIO)

    itens: List[Dict[str, Any]] = []
    for item in extracao.itens:
        descricao = (item.descricao or "").strip() or "Item sem descrição"
        quantidade = float(item.quantidade or 0)
        valor_unitario = abs(float(item.valor_unitario or 0))
        total_ia = abs(float(item.valor_total_item or 0))

        if quantidade <= 0:
            quantidade = 1.0
            observacoes.append(f"Quantidade inválida em '{descricao}' ajustada para 1.")
            confianca = rebaixar_confianca(confianca, NivelConfianca.MEDIO)
        if valor_unitario == 0 and total_ia > 0:
            valor_unitario = round(total_ia / quantidade, 2)

        valor_total_item = round(quantidade * valor_unitario, 2)
        if total_ia > 0 and abs(total_ia - valor_total_item) > 0.01:
            divergencia = True
            observacoes.append(
                f"Item '{descricao}': total indicado R$ {total_ia:.2f} difere de "
                f"{quantidade:g} x R$ {valor_unitario:.2f} = R$ {valor_total_item:.2f}."
            )
        if valor_unitario == 0:
            observacoes.append(f"Item '{descricao}' sem valor identificado.")
            confianca = rebaixar_confianca(confianca, NivelConfianca.BAIXO)

        itens.append({
            "descricao": descricao[:200],
            "quantidade": quantidade,
            "valor_unitario": round(valor_unitario, 2),
            "valor_total_item": valor_total_item,
        })

    informado = round(abs(float(extracao.valor_total_informado or 0)), 2)
    if not itens and informado > 0:
        itens.append({
            "descricao": _descricao_padrao(op),
            "quantidade": 1.0,
            "valor_unitario": informado,
            "valor_total_item": informado,
        })
        observacoes.append("Nenhum item detalhado; lançado o valor total informado como item único.")
        confianca = rebaixar_confianca(confianca, NivelConfianca.MEDIO)

    soma = round(sum(i["valor_total_item"] for i in itens), 2)

    if informado > 0 and abs(informado - soma) > 0.01:
        divergencia = True
        diferenca = round(informado - soma, 2)
        observacoes.append(
            f"DIVERGÊNCIA: total informado R$ {informado:.2f} x soma dos itens R$ {soma:.2f} "
            f"(diferença R$ {diferenca:+.2f} — possível taxa, desconto, couvert ou erro de soma)."
        )

    if divergencia:
        confianca = rebaixar_confianca(confianca, NivelConfianca.MEDIO)

    if soma <= 0:
        confianca = NivelConfianca.BAIXO
        observacoes.append("Nenhum valor monetário identificado no conteúdo.")

    cliente_nome = " ".join((extracao.cliente_nome or "").split()) or "Cliente Balcão"
    if is_cliente_balcao(cliente_nome):
        cliente_nome = "Cliente Balcão"
        if tp == TipoPagamento.FIADO_A_RECEBER or op == TipoOperacao.PAGAMENTO_FIADO:
            observacoes.append("Fiado/pagamento de fiado sem cliente identificado — conferir a quem pertence.")
            confianca = rebaixar_confianca(confianca, NivelConfianca.MEDIO)

    status = StatusValidacao.APROVADO if confianca == NivelConfianca.ALTO else StatusValidacao.PENDENTE_REVISAO

    # remove observações duplicadas preservando a ordem
    vistas, obs_final = set(), []
    for o in observacoes:
        if o not in vistas:
            vistas.add(o)
            obs_final.append(o)

    return {
        "cliente_nome": cliente_nome,
        "cliente_telefone": re.sub(r"\D", "", extracao.cliente_telefone or ""),
        "tipo_operacao": op.value,
        "tipo_pagamento": tp.value,
        "forma_pagamento": forma.value,
        "itens": itens,
        "valor_total": soma,
        "valor_total_informado": informado,
        "divergencia_calculo": divergencia,
        "confianca_extracao": confianca.value,
        "status_validacao": status.value,
        "transcricao_raw": (extracao.transcricao_raw or "").strip()[:8000],
        "observacoes": " | ".join(obs_final)[:2000],
    }


__all__ = [
    "GeminiServiceError",
    "SYSTEM_PROMPT",
    "extrair_de_midia",
    "extrair_de_texto",
    "is_cliente_balcao",
    "mime_suportado",
    "normalizar_extracao",
    "normalizar_mime",
    "origem_por_mime",
    "FormaPagamento",
]
