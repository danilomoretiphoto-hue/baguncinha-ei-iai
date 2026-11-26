"""Rotas consolidadas da API do sistema Baguncinha Ei Iai.

Endpoints administrativos (/api) para controle de vendas, comandas,
clientes, fiados, conferência humana, webhook e exportação gerencial.
"""

import logging
import secrets
from datetime import date
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Security, status
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import Response
from fastapi.security import APIKeyHeader

from app.config import hoje_str, settings
from app.models.cliente import Cliente
from app.models.lancamento import (
    AprovarLancamentoRequest,
    BaixaFiadoClienteRequest,
    BaixaFiadoClienteResponse,
    ExclusaoLancamentoResponse,
    Lancamento,
    LancamentoCreate,
    LancamentoUpdate,
)
from app.services import firestore_service as fs
from app.services.export_service import gerar_xlsx_relatorio_gerencial

logger = logging.getLogger(__name__)

# Dependência de Segurança para Rotas Administrativas
admin_key_header = APIKeyHeader(
    name="X-Admin-Key",
    auto_error=False,
    description="Chave mestra de autenticação administrativa (ADMIN_MASTER_KEY)",
)


def verificar_admin(admin_key: Optional[str] = Security(admin_key_header)) -> None:
    """Valida o cabeçalho X-Admin-Key contra a ADMIN_MASTER_KEY do ambiente."""
    if not settings.ADMIN_MASTER_KEY:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="ADMIN_MASTER_KEY não configurada no servidor.",
        )
    if not admin_key or not secrets.compare_digest(admin_key.strip(), settings.ADMIN_MASTER_KEY):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Acesso não autorizado: cabeçalho 'X-Admin-Key' ausente ou inválido.",
        )


def verificar_webhook_token(
    x_webhook_token: Optional[str] = Header(None, alias="X-Webhook-Token"),
    authorization: Optional[str] = Header(None, alias="Authorization"),
    token_query: Optional[str] = Query(None, alias="token"),
) -> None:
    """Valida o token de segurança exigido para ingestão via Webhook."""
    if not settings.WEBHOOK_SECRET_TOKEN:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="WEBHOOK_SECRET_TOKEN não configurado no servidor.",
        )

    bearer_token = None
    if authorization and authorization.lower().startswith("bearer "):
        bearer_token = authorization[7:].strip()

    token_informado = (x_webhook_token or bearer_token or token_query or "").strip()
    if not token_informado or not secrets.compare_digest(token_informado, settings.WEBHOOK_SECRET_TOKEN):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token de webhook ausente ou inválido.",
        )


router = APIRouter(prefix="/api", tags=["API Consolidada - Baguncinha Ei Iai"])


# ===========================================================================
# 1. LEITURA E FILTROS (GET /api/lancamentos e GET /api/clientes)
# ===========================================================================
@router.get(
    "/lancamentos",
    response_model=List[Lancamento],
    summary="Listar lançamentos com filtros",
    dependencies=[Depends(verificar_admin)],
)
def listar_lancamentos(
    data: Optional[str] = Query(None, description="Filtro por data no formato YYYY-MM-DD"),
    cliente: Optional[str] = Query(None, description="Filtro por nome ou ID do cliente"),
    status: Optional[str] = Query(None, description="Filtro por status: APROVADO, PENDENTE_CONFERENCIA, CANCELADO"),
    tipo: Optional[str] = Query(None, description="Filtro por tipo: VENDA, FIADO, PAGAMENTO_FIADO, DESPESA"),
    limit: int = Query(100, ge=1, le=500, description="Quantidade máxima de registros retornados"),
    offset: int = Query(0, ge=0, description="Deslocamento para paginação"),
):
    """Retorna lançamentos do Firestore com suporte a múltiplos filtros combinados."""
    try:
        # Busca inicial de lançamentos mais recentes
        lancs = fs.listar_lancamentos(limit=500)

        # Filtro de data (data_hora ISO iniciando com YYYY-MM-DD)
        if data:
            data_busca = data.strip()
            lancs = [l for l in lancs if str(l.get("data_hora", "")).startswith(data_busca)]

        # Filtro por cliente (nome ou ID)
        if cliente:
            termo = fs.slugify(cliente)
            lancs = [
                l for l in lancs
                if termo in fs.slugify(l.get("cliente_nome") or "")
                or termo in fs.slugify(l.get("cliente_id") or "")
            ]

        # Filtro por status
        if status:
            status_upper = status.strip().upper()
            if status_upper in ("PENDENTE_CONFERENCIA", "PENDENTE_REVISAO"):
                lancs = [l for l in lancs if l.get("status_validacao") in ("PENDENTE_CONFERENCIA", "PENDENTE_REVISAO")]
            else:
                lancs = [l for l in lancs if str(l.get("status_validacao", "")).upper() == status_upper]

        # Filtro por tipo (VENDA, FIADO, PAGAMENTO_FIADO, DESPESA)
        if tipo:
            tipo_upper = tipo.strip().upper()
            if tipo_upper == "FIADO":
                lancs = [l for l in lancs if l.get("tipo_pagamento") == "FIADO_A_RECEBER"]
            elif tipo_upper == "VENDA":
                lancs = [l for l in lancs if l.get("tipo_operacao") == "VENDA" and l.get("tipo_pagamento") != "FIADO_A_RECEBER"]
            else:
                lancs = [
                    l for l in lancs
                    if str(l.get("tipo_operacao", "")).upper() == tipo_upper
                    or str(l.get("tipo_pagamento", "")).upper() == tipo_upper
                ]

        # Paginação em memória
        resultado = lancs[offset : offset + limit]
        return [Lancamento.model_validate(l) for l in resultado]
    except Exception as exc:
        logger.exception("Erro ao listar lançamentos: %s", exc)
        raise HTTPException(status_code=500, detail=f"Erro interno ao listar lançamentos: {exc}") from exc


@router.get(
    "/clientes",
    response_model=List[Cliente],
    summary="Listar clientes e saldos devedores",
    dependencies=[Depends(verificar_admin)],
)
def listar_clientes():
    """Retorna todos os clientes cadastrados com os respectivos saldos devedores atualizados."""
    try:
        clientes = fs.listar_clientes()
        return [Cliente.model_validate(c) for c in clientes]
    except Exception as exc:
        logger.exception("Erro ao listar clientes: %s", exc)
        raise HTTPException(status_code=500, detail=f"Erro interno ao listar clientes: {exc}") from exc


# ===========================================================================
# 2. GRAVAÇÃO (POST /api/lancamentos)
# ===========================================================================
@router.post(
    "/lancamentos",
    response_model=Lancamento,
    status_code=status.HTTP_201_CREATED,
    summary="Criar lançamento manual (venda à vista ou fiado)",
    dependencies=[Depends(verificar_admin)],
)
def criar_lancamento(payload: LancamentoCreate):
    """Cria um lançamento manual, gerando ID único e atualizando saldo se for fiado aprovado."""
    try:
        itens_dict = [i.model_dump() for i in payload.itens] if payload.itens else None
        lanc, cliente = fs.criar_lancamento_manual(
            cliente=payload.cliente,
            cliente_id=payload.cliente_id,
            itens=itens_dict,
            valor_total=payload.valor_total,
            tipo=payload.tipo,
            forma_pagamento=payload.forma_pagamento,
            status=payload.status,
            confianca=payload.confianca,
            observacoes=payload.observacoes,
        )
        return Lancamento.model_validate(lanc)
    except fs.NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except fs.RegraNegocioError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Erro ao criar lançamento manual: %s", exc)
        raise HTTPException(status_code=500, detail=f"Falha ao criar lançamento: {exc}") from exc


# ===========================================================================
# 3. EDIÇÃO / ATUALIZAÇÃO (PATCH /api/lancamentos/{id})
# ===========================================================================
@router.patch(
    "/lancamentos/{id}",
    response_model=Lancamento,
    summary="Editar lançamento existente",
    dependencies=[Depends(verificar_admin)],
)
def editar_lancamento(id: str, payload: LancamentoUpdate):
    """Atualiza campos de um lançamento existente recalculando saldos vinculados se necessário."""
    try:
        dados_atualizacao = payload.model_dump(exclude_unset=True)
        if not dados_atualizacao:
            raise HTTPException(status_code=400, detail="Nenhum campo fornecido para atualização.")

        if "itens" in dados_atualizacao and dados_atualizacao["itens"] is not None:
            dados_atualizacao["itens"] = [i.model_dump() for i in payload.itens]  # type: ignore

        atualizado = fs.atualizar_lancamento_manual(id, dados_atualizacao)
        return Lancamento.model_validate(atualizado)
    except fs.NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except fs.RegraNegocioError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Erro ao atualizar lançamento '%s': %s", id, exc)
        raise HTTPException(status_code=500, detail=f"Erro interno ao atualizar lançamento: {exc}") from exc


# ===========================================================================
# 4. EXCLUSÃO SEGURA (DELETE /api/lancamentos/{id})
# ===========================================================================
@router.delete(
    "/lancamentos/{id}",
    response_model=ExclusaoLancamentoResponse,
    summary="Excluir ou cancelar lançamento com estorno automático de saldos",
    dependencies=[Depends(verificar_admin)],
)
def excluir_lancamento(
    id: str,
    permanente: bool = Query(
        False,
        description="Se False (padrão), realiza exclusão lógica (status CANCELADO). Se True, exclui documento fisicamente.",
    ),
    motivo: Optional[str] = Query(None, description="Motivo do cancelamento (opcional)"),
):
    """Exclui ou cancela lançamento com estorno imediato do saldo fiado do cliente associado."""
    try:
        resultado = fs.excluir_lancamento(lancamento_id=id, permanente=permanente, motivo=motivo)
        return ExclusaoLancamentoResponse(
            id=resultado["id"],
            status=resultado["status_validacao"] if not permanente else "REMOVIDO",
            permanente=permanente,
            mensagem="Lançamento cancelado e saldo de fiado estornado com sucesso."
            if not permanente
            else "Lançamento excluído permanentemente do Firestore.",
            cliente_id=resultado.get("cliente_id"),
            saldo_fiado_atual=float(resultado.get("saldo_fiado_atual") or 0.0),
        )
    except fs.NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Erro ao excluir lançamento '%s': %s", id, exc)
        raise HTTPException(status_code=500, detail=f"Erro interno ao excluir lançamento: {exc}") from exc


# ===========================================================================
# 5. AÇÕES DE NEGÓCIO (Conferência Humana & Baixa de Fiado)
# ===========================================================================
@router.post(
    "/lancamentos/{id}/aprovar",
    response_model=Lancamento,
    summary="Aprovar lançamento da fila de conferência",
    dependencies=[Depends(verificar_admin)],
)
def aprovar_lancamento(id: str, payload: Optional[AprovarLancamentoRequest] = None):
    """Aprova lançamento com baixa/média confiança (PENDENTE_CONFERENCIA -> APROVADO)."""
    try:
        obs = payload.observacoes if payload else None
        atualizado = fs.aprovar_lancamento(lancamento_id=id, observacoes=obs)
        return Lancamento.model_validate(atualizado)
    except fs.NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except fs.RegraNegocioError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Erro ao aprovar lançamento '%s': %s", id, exc)
        raise HTTPException(status_code=500, detail=f"Erro ao aprovar lançamento: {exc}") from exc


@router.post(
    "/clientes/{id}/baixa-fiado",
    response_model=BaixaFiadoClienteResponse,
    summary="Registrar pagamento e baixa de saldo devedor do cliente",
    dependencies=[Depends(verificar_admin)],
)
def baixa_fiado_cliente(id: str, payload: BaixaFiadoClienteRequest):
    """Registra amortização ou quitação do fiado de um cliente, gerando lançamento de pagamento."""
    try:
        lancamento, saldo_anterior, saldo_atual = fs.registrar_baixa_fiado(
            cliente_id=id,
            valor_pago=payload.valor_pago,
            forma_pagamento=payload.forma_pagamento.value,
            observacoes=payload.observacoes,
        )
        cliente = fs.obter_cliente(id) or {}
        return BaixaFiadoClienteResponse(
            mensagem=f"Baixa de R$ {payload.valor_pago:.2f} registrada com sucesso para {cliente.get('nome', id)}.",
            cliente_id=id,
            cliente_nome=cliente.get("nome", id),
            saldo_anterior=saldo_anterior,
            saldo_fiado_atual=saldo_atual,
            lancamento=Lancamento.model_validate(lancamento),
        )
    except fs.NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except fs.RegraNegocioError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Erro na baixa de fiado do cliente '%s': %s", id, exc)
        raise HTTPException(status_code=500, detail=f"Erro interno na baixa de fiado: {exc}") from exc


# ===========================================================================
# 6. EXPORTAÇÃO GERENCIAL (GET /api/exportar-xlsx)
# ===========================================================================
@router.get(
    "/exportar-xlsx",
    summary="Exportar planilha gerencial Excel (.xlsx) com lançamentos e resumo financeiro",
    dependencies=[Depends(verificar_admin)],
    response_class=Response,
    responses={
        200: {
            "content": {"application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": {}},
            "description": "Arquivo Excel gerencial para download",
        }
    },
)
def exportar_xlsx(
    data: Optional[str] = Query(None, description="Filtro YYYY-MM-DD (padrão: hoje)"),
    cliente: Optional[str] = Query(None, description="Filtro por nome ou ID de cliente"),
    status: Optional[str] = Query(None, description="Filtro por status"),
    tipo: Optional[str] = Query(None, description="Filtro por tipo"),
):
    """Gera e faz streaming de arquivo .xlsx contendo indicadores e detalhamento de vendas/fiados."""
    try:
        data_ref = data or hoje_str()
        lancs = fs.listar_lancamentos(limit=500)

        if data:
            lancs = [l for l in lancs if str(l.get("data_hora", "")).startswith(data.strip())]
        if cliente:
            termo = fs.slugify(cliente)
            lancs = [l for l in lancs if termo in fs.slugify(l.get("cliente_nome") or "")]
        if status:
            st = status.upper().strip()
            lancs = [l for l in lancs if str(l.get("status_validacao", "")).upper() == st]
        if tipo:
            tp = tipo.upper().strip()
            if tp == "FIADO":
                lancs = [l for l in lancs if l.get("tipo_pagamento") == "FIADO_A_RECEBER"]
            elif tp == "VENDA":
                lancs = [l for l in lancs if l.get("tipo_operacao") == "VENDA" and l.get("tipo_pagamento") != "FIADO_A_RECEBER"]
            else:
                lancs = [l for l in lancs if l.get("tipo_operacao") == tp or l.get("tipo_pagamento") == tp]

        clientes_map = fs.mapa_clientes()
        conteudo_xlsx = gerar_xlsx_relatorio_gerencial(lancs, data_ref=data_ref, clientes_mapa=clientes_map)
        nome_arquivo = f"relatorio_baguncinha_eiai_{data_ref}.xlsx"

        return Response(
            content=conteudo_xlsx,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={
                "Content-Disposition": f'attachment; filename="{nome_arquivo}"',
                "Access-Control-Expose-Headers": "Content-Disposition",
            },
        )
    except Exception as exc:
        logger.exception("Erro ao exportar planilha Excel: %s", exc)
        raise HTTPException(status_code=500, detail=f"Erro interno na exportação Excel: {exc}") from exc


# ===========================================================================
# 7. WEBHOOK & SAÚDE DO SISTEMA (POST /api/webhook & GET /health)
# ===========================================================================
@router.post(
    "/webhook",
    summary="Ingestão de webhook com validação de token e idempotência",
    dependencies=[Depends(verificar_webhookToken := verificar_webhook_token)],
)
async def webhook_ingestao(payload: Dict[str, Any]):
    """Recebe eventos de webhook, verifica idempotência pelo ID da mensagem e processa com IA."""
    try:
        # Extrai identificador da mensagem para idempotência
        message_id = str(
            payload.get("message_id")
            or payload.get("id")
            or payload.get("mid")
            or (payload.get("key") or {}).get("id")
            or ""
        ).strip()

        if message_id:
            ja_processado = await run_in_threadpool(
                fs.verificar_e_registrar_idempotencia_webhook, message_id, payload
            )
            if ja_processado:
                logger.info("Webhook ignorado por duplicidade (idempotente): %s", message_id)
                return {
                    "status": "JA_PROCESSADO",
                    "message_id": message_id,
                    "mensagem": "Mensagem já processada anteriormente (idempotência garantida).",
                }

        # Extrai texto do pedido caso enviado em formato de texto livre
        texto = payload.get("texto") or payload.get("text") or payload.get("mensagem")
        cliente_id = payload.get("cliente_id")

        if texto:
            from app.services import gemini_service as gs
            extracao = await gs.extrair_de_texto(str(texto))
            normalizado = gs.normalizar_extracao(extracao)
            lancamento, cliente = await run_in_threadpool(
                fs.registrar_lancamento_extraido,
                normalizado,
                "TEXTO",
                cliente_id,
                None,
                message_id or None,
            )
            return {
                "status": "SUCESSO",
                "message_id": message_id or None,
                "mensagem": f"Lançamento de R$ {lancamento['valor_total']:.2f} processado pelo Agente.",
                "lancamento": lancamento,
            }

        # Registra log de recebimento
        await run_in_threadpool(fs.registrar_log_webhook, payload, "RECEBIDO", None, "API_WEBHOOK")
        return {
            "status": "SUCESSO",
            "message_id": message_id or None,
            "mensagem": "Payload recebido e registrado com sucesso.",
        }
    except Exception as exc:
        logger.exception("Erro ao processar webhook: %s", exc)
        raise HTTPException(status_code=500, detail=f"Erro interno no processamento do webhook: {exc}") from exc


@router.get("/health", summary="Verificação de integridade da API e do Cloud Firestore")
def api_health():
    """Verifica se a API está online e se a conexão com o Google Cloud Firestore está ativa."""
    db_ok, msg = fs.testar_conexao_firestore()
    if not db_ok:
        logger.error("Falha no health check do Firestore: %s", msg)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "status": "degraded",
                "app": settings.APP_NAME,
                "version": settings.APP_VERSION,
                "firestore": "desconectado",
                "erro": msg,
            },
        )
    return {
        "status": "ok",
        "app": settings.APP_NAME,
        "version": settings.APP_VERSION,
        "firestore": "ativo",
    }
