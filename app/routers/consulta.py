"""API pública do cliente (autenticada por header X-API-Key)."""

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Security, status
from fastapi.security import APIKeyHeader

from app.models.cliente import ClienteResumoPublico
from app.models.lancamento import Lancamento, ListaLancamentosResponse
from app.services import firestore_service as fs

router = APIRouter(prefix="/v1/consulta", tags=["Consulta do Cliente"])

api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False, description="API Key individual do cliente")


def cliente_autenticado(api_key: Optional[str] = Security(api_key_header)) -> Dict[str, Any]:
    if not api_key:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Header X-API-Key ausente.")
    cliente = fs.buscar_cliente_por_api_key(api_key.strip())
    if not cliente:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="X-API-Key inválida.")
    return cliente


def _com_nome(lancs: List[Dict[str, Any]], cliente: Dict[str, Any]) -> List[Dict[str, Any]]:
    return [{**l, "cliente_nome": cliente.get("nome")} for l in lancs]


@router.get("/resumo", response_model=ClienteResumoPublico, summary="Resumo da conta do cliente")
def resumo(cliente: Dict[str, Any] = Depends(cliente_autenticado)):
    lancs = fs.lancamentos_do_cliente(cliente["id"])
    abertos, saldo = fs.calcular_fiados_em_aberto(cliente["id"], lancs)
    compras = [l for l in lancs if l.get("tipo_operacao") == "VENDA" and l.get("status_validacao") != "REJEITADO"]
    return ClienteResumoPublico(
        cliente_id=cliente["id"],
        nome=cliente.get("nome", ""),
        saldo_fiado_atual=saldo,
        quantidade_fiados_em_aberto=len(abertos),
        data_ultima_compra=compras[0].get("data_hora") if compras else None,
    )


@router.get("/fiado", response_model=List[Lancamento], summary="Fiados em aberto do cliente")
def fiado(cliente: Dict[str, Any] = Depends(cliente_autenticado)):
    abertos, _ = fs.calcular_fiados_em_aberto(cliente["id"])
    return _com_nome(abertos, cliente)


@router.get("/lancamentos", response_model=ListaLancamentosResponse, summary="Histórico paginado de lançamentos")
def lancamentos(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    cliente: Dict[str, Any] = Depends(cliente_autenticado),
):
    todos = [l for l in fs.lancamentos_do_cliente(cliente["id"]) if l.get("status_validacao") != "REJEITADO"]
    pagina = todos[offset: offset + limit]
    return ListaLancamentosResponse(total=len(todos), limit=limit, offset=offset, itens=_com_nome(pagina, cliente))


@router.get("/pendencias", response_model=List[Lancamento], summary="Lançamentos com divergência ou em auditoria")
def pendencias(cliente: Dict[str, Any] = Depends(cliente_autenticado)):
    lancs = [
        l for l in fs.lancamentos_do_cliente(cliente["id"])
        if l.get("status_validacao") != "REJEITADO"
        and (l.get("divergencia_calculo") or l.get("status_validacao") == "PENDENTE_REVISAO")
    ]
    return _com_nome(lancs, cliente)
