"""Schemas Pydantic v2 do Agente Like Baguncinha."""

from app.models.cliente import Cliente, ClienteCreate, ClienteResumoPublico, MensagemCobranca
from app.models.fechamento import DashboardKPIs, Fechamento
from app.models.lancamento import (
    BaixaFiadoRequest,
    BaixaFiadoResponse,
    ExtracaoIA,
    FormaPagamento,
    IngestaoResponse,
    IngestaoTextoRequest,
    ItemExtraido,
    ItemLancamento,
    Lancamento,
    ListaLancamentosResponse,
    NivelConfianca,
    OrigemDados,
    StatusValidacao,
    TipoOperacao,
    TipoPagamento,
    ValidacaoRequest,
)
from app.models.webhook import LogWebhook, MensagemWhatsApp, WebhookResponse

__all__ = [
    "BaixaFiadoRequest",
    "BaixaFiadoResponse",
    "Cliente",
    "ClienteCreate",
    "ClienteResumoPublico",
    "DashboardKPIs",
    "ExtracaoIA",
    "Fechamento",
    "FormaPagamento",
    "IngestaoResponse",
    "IngestaoTextoRequest",
    "ItemExtraido",
    "ItemLancamento",
    "Lancamento",
    "ListaLancamentosResponse",
    "LogWebhook",
    "MensagemCobranca",
    "MensagemWhatsApp",
    "NivelConfianca",
    "OrigemDados",
    "StatusValidacao",
    "TipoOperacao",
    "TipoPagamento",
    "ValidacaoRequest",
    "WebhookResponse",
]
