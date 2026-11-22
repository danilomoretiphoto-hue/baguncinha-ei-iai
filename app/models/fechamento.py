"""Schemas da coleção `fechamentos` e KPIs do dashboard."""

from pydantic import BaseModel, ConfigDict


class Fechamento(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str = ""
    data_fechamento: str
    total_vendas_pago: float = 0.0
    total_fiado_gerado: float = 0.0
    total_fiado_recebido: float = 0.0
    total_despesas: float = 0.0
    saldo_liquido_dia: float = 0.0
    quantidade_transacoes: int = 0
    criado_em: str = ""


class DashboardKPIs(BaseModel):
    data_referencia: str
    total_vendido_hoje: float
    total_fiado_gerado_hoje: float
    total_fiado_a_receber: float
    total_recebido_fiado_hoje: float
    total_despesas_hoje: float
    saldo_liquido_hoje: float
    pendencias_conferencia: int
    quantidade_transacoes_hoje: int
    quantidade_clientes: int
