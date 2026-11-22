"""API administrativa (autenticada por header X-Admin-Key = ADMIN_MASTER_KEY)."""

import secrets
from datetime import date
from typing import List, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Security, UploadFile, status
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import Response
from fastapi.security import APIKeyHeader

from app.config import hoje_str, settings
from app.models.cliente import Cliente, ClienteCreate, MensagemCobranca
from app.models.fechamento import DashboardKPIs, Fechamento
from app.models.lancamento import (
    BaixaFiadoRequest,
    BaixaFiadoResponse,
    IngestaoResponse,
    IngestaoTextoRequest,
    Lancamento,
    OrigemDados,
    StatusValidacao,
    TipoPagamento,
    ValidacaoRequest,
)
from app.services import firestore_service as fs
from app.services import gemini_service as gs
from app.services.export_service import gerar_xlsx_fechamento

admin_key_header = APIKeyHeader(name="X-Admin-Key", auto_error=False, description="Chave mestra ADMIN_MASTER_KEY")


def verificar_admin(admin_key: Optional[str] = Security(admin_key_header)) -> None:
    if not settings.ADMIN_MASTER_KEY:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                            detail="ADMIN_MASTER_KEY não configurada no servidor.")
    if not admin_key or not secrets.compare_digest(admin_key.strip(), settings.ADMIN_MASTER_KEY):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="X-Admin-Key inválida ou ausente.")


router = APIRouter(prefix="/v1/admin", tags=["Administração"], dependencies=[Depends(verificar_admin)])


def _validar_data(data: Optional[str]) -> str:
    if not data:
        return hoje_str()
    try:
        return date.fromisoformat(data).isoformat()
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="Data inválida. Use o formato YYYY-MM-DD.") from exc


# ---------------------------------------------------------------------------
# Clientes
# ---------------------------------------------------------------------------
@router.post("/clientes", response_model=Cliente, status_code=status.HTTP_201_CREATED, summary="Cadastra cliente")
def criar_cliente(payload: ClienteCreate):
    return fs.criar_cliente(
        nome=payload.nome, telefone=payload.telefone, cpf_cnpj=payload.cpf_cnpj, cliente_id=payload.id
    )


@router.get("/clientes", response_model=List[Cliente], summary="Lista clientes e saldos")
def listar_clientes():
    return fs.listar_clientes()


@router.get("/clientes/{cliente_id}/fiado", response_model=List[Lancamento], summary="Fiados em aberto de um cliente")
def fiados_cliente(cliente_id: str):
    cliente = fs.obter_cliente(cliente_id)
    if not cliente:
        raise fs.NotFoundError(f"Cliente '{cliente_id}' não encontrado.")
    abertos, _ = fs.calcular_fiados_em_aberto(cliente_id)
    return [{**l, "cliente_nome": cliente.get("nome")} for l in abertos]


@router.get("/clientes/{cliente_id}/cobranca", response_model=MensagemCobranca, summary="Mensagem de cobrança WhatsApp")
def cobranca_cliente(cliente_id: str):
    return fs.gerar_mensagem_cobranca(cliente_id)


# ---------------------------------------------------------------------------
# Dashboard / lançamentos
# ---------------------------------------------------------------------------
@router.get("/dashboard", response_model=DashboardKPIs, summary="KPIs do dia")
def dashboard():
    return fs.dashboard_kpis()


@router.get("/lancamentos", response_model=List[Lancamento], summary="Lançamentos recentes")
def listar_lancamentos(
    limit: int = Query(200, ge=1, le=500),
    tipo_pagamento: Optional[TipoPagamento] = None,
    status_validacao: Optional[StatusValidacao] = None,
    busca: Optional[str] = Query(None, description="Filtro por nome do cliente"),
):
    return fs.listar_lancamentos(
        limit=limit,
        tipo_pagamento=tipo_pagamento.value if tipo_pagamento else None,
        status_validacao=status_validacao.value if status_validacao else None,
        busca=busca,
    )


@router.get("/pendencias", response_model=List[Lancamento], summary="Fila de conferência humana")
def pendencias():
    return fs.listar_pendentes()


# ---------------------------------------------------------------------------
# Ingestão multimodal
# ---------------------------------------------------------------------------
def _resposta_ingestao(lancamento: dict, cliente: dict) -> IngestaoResponse:
    status_txt = (
        "aprovado automaticamente" if lancamento["status_validacao"] == "APROVADO"
        else "enviado para a fila de conferência humana"
    )
    return IngestaoResponse(
        mensagem=f"Lançamento de R$ {lancamento['valor_total']:.2f} registrado e {status_txt}.",
        lancamento=Lancamento.model_validate(lancamento),
        cliente_id=cliente["id"],
        cliente_nome=cliente.get("nome", ""),
        saldo_fiado_atual=float(cliente.get("saldo_fiado_atual") or 0),
    )


@router.post("/ingestao/texto", response_model=IngestaoResponse, summary="Ingestão de texto via Gemini")
async def ingestao_texto(payload: IngestaoTextoRequest):
    if payload.cliente_id and not await run_in_threadpool(fs.obter_cliente, payload.cliente_id):
        raise fs.NotFoundError(f"Cliente '{payload.cliente_id}' não encontrado.")
    extracao = await gs.extrair_de_texto(payload.texto)
    normalizado = gs.normalizar_extracao(extracao)
    lancamento, cliente = await run_in_threadpool(
        fs.registrar_lancamento_extraido, normalizado, OrigemDados.TEXTO.value, payload.cliente_id
    )
    return _resposta_ingestao(lancamento, cliente)


@router.post("/ingestao/midia", response_model=IngestaoResponse, summary="Ingestão de imagem/áudio via Gemini")
async def ingestao_midia(
    arquivo: UploadFile = File(..., description="Imagem de comanda, PDF ou áudio de pedido"),
    cliente_id: Optional[str] = Form(None),
    texto_contexto: Optional[str] = Form(None, description="Observação opcional enviada junto à mídia"),
):
    dados = await arquivo.read()
    if not dados:
        raise HTTPException(status_code=400, detail="Arquivo vazio.")
    if len(dados) > settings.max_upload_bytes:
        raise HTTPException(status_code=413, detail=f"Arquivo excede {settings.MAX_UPLOAD_MB} MB.")
    mime = gs.normalizar_mime(arquivo.content_type, arquivo.filename)
    if not gs.mime_suportado(mime):
        raise HTTPException(status_code=415, detail=f"Tipo de arquivo não suportado: '{mime or 'desconhecido'}'.")

    cliente_id = (cliente_id or "").strip() or None
    if cliente_id and not await run_in_threadpool(fs.obter_cliente, cliente_id):
        raise fs.NotFoundError(f"Cliente '{cliente_id}' não encontrado.")

    contexto = (texto_contexto or "").strip() or None
    extracao = await gs.extrair_de_midia(dados, mime, contexto=contexto)
    normalizado = gs.normalizar_extracao(extracao)
    lancamento, cliente = await run_in_threadpool(
        fs.registrar_lancamento_extraido,
        normalizado,
        gs.origem_por_mime(mime).value,
        cliente_id,
        None,
        None,
        f"upload:{arquivo.filename or 'arquivo'} ({mime}, {len(dados) // 1024} KB)",
    )
    return _resposta_ingestao(lancamento, cliente)


# ---------------------------------------------------------------------------
# Validação humana e fiado
# ---------------------------------------------------------------------------
@router.patch("/lancamentos/{lancamento_id}/validar", response_model=Lancamento, summary="Aprova/rejeita lançamento")
def validar_lancamento(lancamento_id: str, payload: ValidacaoRequest):
    return fs.validar_lancamento(
        lancamento_id=lancamento_id,
        status_validacao=payload.status_validacao.value,
        itens=[i.model_dump() for i in payload.itens] if payload.itens is not None else None,
        tipo_operacao=payload.tipo_operacao.value if payload.tipo_operacao else None,
        tipo_pagamento=payload.tipo_pagamento.value if payload.tipo_pagamento else None,
        forma_pagamento=payload.forma_pagamento.value if payload.forma_pagamento else None,
        cliente_id=payload.cliente_id,
        observacoes=payload.observacoes,
    )


@router.post("/fiado/baixa", response_model=BaixaFiadoResponse, summary="Registra pagamento de fiado")
def baixa_fiado(payload: BaixaFiadoRequest):
    lancamento, saldo_anterior, saldo_atual = fs.registrar_baixa_fiado(
        cliente_id=payload.cliente_id,
        valor_pago=payload.valor_pago,
        forma_pagamento=payload.forma_pagamento.value,
        observacoes=payload.observacoes,
    )
    return BaixaFiadoResponse(
        mensagem=f"Baixa de R$ {payload.valor_pago:.2f} registrada com sucesso.",
        lancamento=Lancamento.model_validate(lancamento),
        saldo_anterior=saldo_anterior,
        saldo_fiado_atual=saldo_atual,
    )


# ---------------------------------------------------------------------------
# Fechamento
# ---------------------------------------------------------------------------
@router.post("/fechamento", response_model=Fechamento, summary="Calcula e grava o fechamento do dia")
def gerar_fechamento(data: Optional[str] = Query(None, description="YYYY-MM-DD (padrão: hoje)")):
    return fs.salvar_fechamento(_validar_data(data))


@router.get("/fechamento/exportar-xlsx", summary="Exporta o fechamento em Excel (.xlsx)",
            response_class=Response,
            responses={200: {"content": {"application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": {}}}})
def exportar_xlsx(data: Optional[str] = Query(None, description="YYYY-MM-DD (padrão: hoje)")):
    data_ref = _validar_data(data)
    fs.salvar_fechamento(data_ref)
    resumo, lancamentos = fs.calcular_fechamento(data_ref)
    conteudo = gerar_xlsx_fechamento(resumo, lancamentos, fs.mapa_clientes())
    nome = f"fechamento_like_baguncinha_{data_ref}.xlsx"
    return Response(
        content=conteudo,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{nome}"', "Access-Control-Expose-Headers": "Content-Disposition"},
    )
