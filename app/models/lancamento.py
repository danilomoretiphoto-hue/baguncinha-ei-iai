"""Schemas da coleção `lancamentos` e do contrato de extração da IA."""

from enum import Enum
from typing import List, Optional, Tuple

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


# ---------------------------------------------------------------------------
# Enumerações de domínio
# ---------------------------------------------------------------------------
class TipoOperacao(str, Enum):
    VENDA = "VENDA"
    PAGAMENTO_FIADO = "PAGAMENTO_FIADO"
    DESPESA = "DESPESA"


class TipoPagamento(str, Enum):
    PAGO = "PAGO"
    FIADO_A_RECEBER = "FIADO_A_RECEBER"
    A_PAGAR = "A_PAGAR"


class FormaPagamento(str, Enum):
    PIX = "PIX"
    DINHEIRO = "DINHEIRO"
    CARTAO_CREDITO = "CARTAO_CREDITO"
    CARTAO_DEBITO = "CARTAO_DEBITO"
    FIADO = "FIADO"


class NivelConfianca(str, Enum):
    ALTO = "ALTO"
    MEDIO = "MEDIO"
    BAIXO = "BAIXO"


class StatusValidacao(str, Enum):
    APROVADO = "APROVADO"
    PENDENTE_REVISAO = "PENDENTE_REVISAO"
    REJEITADO = "REJEITADO"


class OrigemDados(str, Enum):
    TEXTO = "TEXTO"
    IMAGEM_COMANDA = "IMAGEM_COMANDA"
    AUDIO_WHATSAPP = "AUDIO_WHATSAPP"


_ORDEM_CONFIANCA = {NivelConfianca.ALTO: 3, NivelConfianca.MEDIO: 2, NivelConfianca.BAIXO: 1}


def rebaixar_confianca(atual: NivelConfianca, maximo: NivelConfianca) -> NivelConfianca:
    """Retorna o pior nível entre `atual` e `maximo`."""
    atual = NivelConfianca(atual)
    maximo = NivelConfianca(maximo)
    return atual if _ORDEM_CONFIANCA[atual] <= _ORDEM_CONFIANCA[maximo] else maximo


def coerencia_tipos(
    tipo_operacao: TipoOperacao,
    tipo_pagamento: TipoPagamento,
    forma_pagamento: FormaPagamento,
) -> Tuple[TipoOperacao, TipoPagamento, FormaPagamento, List[str]]:
    """Garante combinações financeiramente válidas entre operação, tipo e forma de pagamento."""
    op = TipoOperacao(tipo_operacao)
    tp = TipoPagamento(tipo_pagamento)
    forma = FormaPagamento(forma_pagamento)
    avisos: List[str] = []

    if tp == TipoPagamento.A_PAGAR and op != TipoOperacao.DESPESA:
        avisos.append(f"Operação {op.value} com tipo A_PAGAR reclassificada como DESPESA.")
        op = TipoOperacao.DESPESA
    elif op == TipoOperacao.DESPESA and tp != TipoPagamento.A_PAGAR:
        avisos.append(f"Despesa com tipo {tp.value} reclassificada como A_PAGAR.")
        tp = TipoPagamento.A_PAGAR

    if op == TipoOperacao.PAGAMENTO_FIADO and tp != TipoPagamento.PAGO:
        avisos.append("Pagamento de fiado sempre é PAGO; tipo ajustado.")
        tp = TipoPagamento.PAGO

    if tp == TipoPagamento.FIADO_A_RECEBER:
        if op != TipoOperacao.VENDA:
            op = TipoOperacao.VENDA
        if forma != FormaPagamento.FIADO:
            forma = FormaPagamento.FIADO

    if tp == TipoPagamento.PAGO and forma == FormaPagamento.FIADO:
        avisos.append("Forma FIADO incompatível com pagamento PAGO; ajustada para DINHEIRO (conferir).")
        forma = FormaPagamento.DINHEIRO

    return op, tp, forma, avisos


# ---------------------------------------------------------------------------
# Itens e lançamentos
# ---------------------------------------------------------------------------
class ItemLancamento(BaseModel):
    """Item individual de um lançamento. `valor_total_item` é sempre recalculado."""

    descricao: str = Field(..., min_length=1, max_length=200)
    quantidade: float = Field(..., gt=0)
    valor_unitario: float = Field(..., ge=0)
    valor_total_item: float = 0.0

    @model_validator(mode="after")
    def _calcular_total(self) -> "ItemLancamento":
        self.valor_total_item = round(self.quantidade * self.valor_unitario, 2)
        return self


class Lancamento(BaseModel):
    """Documento da coleção `lancamentos` (com campos calculados opcionais)."""

    model_config = ConfigDict(extra="ignore")

    id: str
    cliente_id: str = ""
    cliente_nome: Optional[str] = Field(None, description="Campo calculado (join com clientes), não persistido.")
    data_hora: str = ""
    tipo_operacao: TipoOperacao = TipoOperacao.VENDA
    tipo_pagamento: TipoPagamento = TipoPagamento.PAGO
    forma_pagamento: FormaPagamento = FormaPagamento.DINHEIRO
    itens: List[ItemLancamento] = Field(default_factory=list)
    valor_total: float = 0.0
    confianca_extracao: NivelConfianca = NivelConfianca.ALTO
    status_validacao: StatusValidacao = StatusValidacao.APROVADO
    divergencia_calculo: bool = False
    origem_dados: OrigemDados = OrigemDados.TEXTO
    transcricao_raw: str = ""
    observacoes: str = ""
    criado_em: str = ""
    valor_em_aberto: Optional[float] = Field(None, description="Campo calculado (FIFO de fiados), não persistido.")


class ListaLancamentosResponse(BaseModel):
    total: int
    limit: int
    offset: int
    itens: List[Lancamento]


# ---------------------------------------------------------------------------
# Contrato estruturado de resposta do Gemini (response_schema)
# Obs.: sem valores default/Optional para máxima compatibilidade com o schema da API.
# ---------------------------------------------------------------------------
class ItemExtraido(BaseModel):
    descricao: str = Field(..., description="Descrição do produto/serviço, ex: 'Guaraná Antarctica lata'.")
    quantidade: float = Field(..., description="Quantidade do item. Use 1 se não informada.")
    valor_unitario: float = Field(..., description="Valor unitário em reais.")
    valor_total_item: float = Field(..., description="quantidade * valor_unitario.")


class ExtracaoIA(BaseModel):
    cliente_nome: str = Field(..., description="Nome do cliente/fornecedor citado ou 'Cliente Balcão' se anônimo.")
    cliente_telefone: str = Field(..., description="Telefone citado no conteúdo (apenas dígitos) ou string vazia.")
    tipo_operacao: TipoOperacao = Field(..., description="VENDA, PAGAMENTO_FIADO (cliente quitando fiado) ou DESPESA.")
    tipo_pagamento: TipoPagamento = Field(..., description="PAGO, FIADO_A_RECEBER ou A_PAGAR.")
    forma_pagamento: FormaPagamento = Field(..., description="PIX, DINHEIRO, CARTAO_CREDITO, CARTAO_DEBITO ou FIADO.")
    itens: List[ItemExtraido] = Field(..., description="Todos os itens listados individualmente.")
    valor_total_informado: float = Field(
        ..., description="Valor total escrito no papel/falado no áudio. 0 se nenhum total foi informado."
    )
    valor_total: float = Field(..., description="Soma calculada de (quantidade * valor_unitario) de todos os itens.")
    divergencia_calculo: bool = Field(..., description="true se o total informado difere da soma calculada.")
    confianca_extracao: NivelConfianca = Field(..., description="ALTO, MEDIO ou BAIXO.")
    transcricao_raw: str = Field(..., description="Transcrição literal e completa do texto/imagem/áudio.")
    observacoes: str = Field(..., description="Avisos, divergências, taxas, dúvidas de leitura. Vazio se nada.")


# ---------------------------------------------------------------------------
# Requests / Responses da API administrativa
# ---------------------------------------------------------------------------
class IngestaoTextoRequest(BaseModel):
    texto: str = Field(..., min_length=1, max_length=10000,
                       examples=["Marcar pro João do Bar 3 guaraná lata 5 real cada e 1 x-tudo 22"])
    cliente_id: Optional[str] = Field(None, description="Força a associação a um cliente existente.")


class IngestaoResponse(BaseModel):
    mensagem: str
    lancamento: Lancamento
    cliente_id: str
    cliente_nome: str
    saldo_fiado_atual: float


class ValidacaoRequest(BaseModel):
    status_validacao: StatusValidacao = Field(..., description="APROVADO ou REJEITADO.")
    itens: Optional[List[ItemLancamento]] = Field(None, description="Itens corrigidos (recalcula valor_total).")
    tipo_operacao: Optional[TipoOperacao] = None
    tipo_pagamento: Optional[TipoPagamento] = None
    forma_pagamento: Optional[FormaPagamento] = None
    cliente_id: Optional[str] = None
    observacoes: Optional[str] = Field(None, max_length=2000)

    @field_validator("status_validacao")
    @classmethod
    def _status_final(cls, v: StatusValidacao) -> StatusValidacao:
        if v == StatusValidacao.PENDENTE_REVISAO:
            raise ValueError("status_validacao deve ser APROVADO ou REJEITADO.")
        return v

    @field_validator("itens")
    @classmethod
    def _itens_nao_vazios(cls, v: Optional[List[ItemLancamento]]) -> Optional[List[ItemLancamento]]:
        if v is not None and len(v) == 0:
            raise ValueError("Informe ao menos um item ou omita o campo.")
        return v


class BaixaFiadoRequest(BaseModel):
    cliente_id: str = Field(..., min_length=1)
    valor_pago: float = Field(..., gt=0, examples=[50.0])
    forma_pagamento: FormaPagamento = Field(FormaPagamento.PIX)
    observacoes: Optional[str] = Field(None, max_length=1000)

    @field_validator("forma_pagamento")
    @classmethod
    def _forma_valida(cls, v: FormaPagamento) -> FormaPagamento:
        if v == FormaPagamento.FIADO:
            raise ValueError("Baixa de fiado não pode ser paga com FIADO.")
        return v

    @field_validator("valor_pago")
    @classmethod
    def _arredondar(cls, v: float) -> float:
        return round(v, 2)


class BaixaFiadoResponse(BaseModel):
    mensagem: str
    lancamento: Lancamento
    saldo_anterior: float
    saldo_fiado_atual: float


# ---------------------------------------------------------------------------
# Schemas para rotas consolidadas da API (/api/lancamentos e /api/clientes)
# ---------------------------------------------------------------------------
class LancamentoCreate(BaseModel):
    """Payload para criação manual de lançamento (venda ou fiado)."""

    cliente: Optional[str] = Field(None, description="Nome do cliente (ex: 'João da Padaria')")
    cliente_id: Optional[str] = Field(None, description="ID do cliente caso já cadastrado")
    itens: Optional[List[ItemLancamento]] = Field(default=None, description="Itens comercializados")
    valor_total: Optional[float] = Field(None, ge=0, description="Valor total da operação (opcional se itens informados)")
    tipo: Optional[str] = Field("VENDA", description="Tipo da transação: 'VENDA' ou 'FIADO'")
    forma_pagamento: Optional[str] = Field("DINHEIRO", description="'DINHEIRO', 'PIX', 'CARTAO', 'CARTAO_CREDITO', 'CARTAO_DEBITO', 'FIADO'")
    status: Optional[str] = Field("APROVADO", description="'APROVADO' ou 'PENDENTE_CONFERENCIA'")
    confianca: Optional[str] = Field("ALTA", description="'ALTA', 'MEDIA' ou 'BAIXA'")
    observacoes: Optional[str] = Field(None, max_length=2000)


class LancamentoUpdate(BaseModel):
    """Payload para edição parcial de lançamento existente."""

    cliente: Optional[str] = Field(None, description="Atualizar nome ou associar a outro cliente")
    cliente_id: Optional[str] = Field(None, description="ID do cliente")
    itens: Optional[List[ItemLancamento]] = Field(None, description="Nova lista de itens")
    valor_total: Optional[float] = Field(None, ge=0, description="Novo valor total")
    tipo: Optional[str] = Field(None, description="'VENDA' ou 'FIADO'")
    forma_pagamento: Optional[str] = Field(None, description="'DINHEIRO', 'PIX', 'CARTAO', 'FIADO'")
    status: Optional[str] = Field(None, description="'APROVADO', 'PENDENTE_CONFERENCIA', 'CANCELADO'")
    observacoes: Optional[str] = Field(None, max_length=2000)


class ExclusaoLancamentoResponse(BaseModel):
    """Resposta da exclusão lógica ou física de lançamento."""

    id: str
    status: str
    permanente: bool
    mensagem: str
    cliente_id: Optional[str] = None
    saldo_fiado_atual: float = 0.0


class AprovarLancamentoRequest(BaseModel):
    """Payload opcional para aprovação de lançamento em conferência."""

    observacoes: Optional[str] = Field(None, max_length=2000)


class BaixaFiadoClienteRequest(BaseModel):
    """Payload para baixa de fiado pelo ID do cliente (POST /api/clientes/{id}/baixa-fiado)."""

    valor_pago: float = Field(..., gt=0, examples=[50.0], description="Valor amortizado ou quitado")
    forma_pagamento: FormaPagamento = Field(FormaPagamento.PIX, description="Forma do pagamento (PIX, DINHEIRO, CARTAO)")
    observacoes: Optional[str] = Field(None, max_length=1000)

    @field_validator("forma_pagamento")
    @classmethod
    def _forma_valida(cls, v: FormaPagamento) -> FormaPagamento:
        if v == FormaPagamento.FIADO:
            raise ValueError("Baixa de fiado não pode ser paga com FIADO.")
        return v

    @field_validator("valor_pago")
    @classmethod
    def _arredondar(cls, v: float) -> float:
        return round(v, 2)


class BaixaFiadoClienteResponse(BaseModel):
    """Resposta consolidada de baixa de fiado de um cliente."""

    mensagem: str
    cliente_id: str
    cliente_nome: str
    saldo_anterior: float
    saldo_fiado_atual: float
    lancamento: Lancamento
