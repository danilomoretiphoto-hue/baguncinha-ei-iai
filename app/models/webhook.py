"""Schemas da integração WhatsApp e da coleção `logs_webhook`."""

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field


class LogWebhook(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str
    origem: str = "WHATSAPP"
    payload_recebido: Dict[str, Any] = Field(default_factory=dict)
    status_processamento: str = "SUCESSO"
    mensagem_erro: Optional[str] = None
    criado_em: str = ""


class MensagemWhatsApp(BaseModel):
    """Mensagem normalizada, independente do provedor (Z-API, Evolution, Meta ou genérico)."""

    provedor: str = "GENERICO"
    message_id: Optional[str] = None
    telefone: str = ""
    nome_contato: Optional[str] = None
    from_me: bool = False
    texto: str = ""
    media_url: Optional[str] = None
    media_base64: Optional[str] = None
    media_id: Optional[str] = None
    mime_type: Optional[str] = None

    @property
    def tem_midia(self) -> bool:
        return bool(self.media_url or self.media_base64 or self.media_id)

    @property
    def processavel(self) -> bool:
        return self.tem_midia or bool(self.texto.strip())


class ResultadoMensagem(BaseModel):
    message_id: Optional[str] = None
    status: str
    lancamento_id: Optional[str] = None
    cliente_id: Optional[str] = None
    valor_total: Optional[float] = None
    status_validacao: Optional[str] = None
    erro: Optional[str] = None


class WebhookResponse(BaseModel):
    status: str
    mensagem: str
    log_id: Optional[str] = None
    resultados: List[ResultadoMensagem] = Field(default_factory=list)
