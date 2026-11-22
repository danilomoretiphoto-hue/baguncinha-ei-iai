"""Schemas da coleção `clientes`."""

import re
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ClienteCreate(BaseModel):
    """Payload de cadastro de cliente (POST /v1/admin/clientes)."""

    nome: str = Field(..., min_length=2, max_length=120, examples=["João do Bar"])
    telefone: str = Field("", max_length=20, examples=["5517999998888"])
    cpf_cnpj: Optional[str] = Field(None, max_length=20, examples=["123.456.789-00"])
    id: Optional[str] = Field(None, max_length=80, description="ID/slug opcional. Gerado a partir do nome se omitido.")

    @field_validator("nome")
    @classmethod
    def _limpar_nome(cls, v: str) -> str:
        v = " ".join(v.split())
        if len(v) < 2:
            raise ValueError("Nome deve ter ao menos 2 caracteres.")
        return v

    @field_validator("telefone")
    @classmethod
    def _limpar_telefone(cls, v: str) -> str:
        return re.sub(r"\D", "", v or "")

    @field_validator("cpf_cnpj")
    @classmethod
    def _limpar_doc(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        v = v.strip()
        return v or None


class Cliente(BaseModel):
    """Documento completo de cliente."""

    model_config = ConfigDict(extra="ignore")

    id: str
    nome: str
    telefone: str = ""
    cpf_cnpj: Optional[str] = None
    api_key: str = ""
    saldo_fiado_atual: float = 0.0
    criado_em: str = ""


class ClienteResumoPublico(BaseModel):
    """Resposta de GET /v1/consulta/resumo."""

    cliente_id: str
    nome: str
    saldo_fiado_atual: float
    quantidade_fiados_em_aberto: int
    data_ultima_compra: Optional[str] = None


class MensagemCobranca(BaseModel):
    """Mensagem pronta de cobrança via WhatsApp."""

    cliente_id: str
    nome: str
    telefone: str = ""
    saldo_fiado_atual: float
    quantidade_lancamentos_em_aberto: int
    mensagem: str
    whatsapp_link: Optional[str] = None
