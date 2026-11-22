"""Configurações centrais da aplicação (carregadas do arquivo .env)."""

import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import List

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
STATIC_DIR = Path(__file__).resolve().parent / "static"

load_dotenv(BASE_DIR / ".env")

# Bebedouro - SP: horário de Brasília (UTC-3, sem horário de verão desde 2019)
TZ_BRASIL = timezone(timedelta(hours=-3), name="America/Sao_Paulo")


def _resolver_caminho(valor: str) -> Path:
    caminho = Path(valor)
    if not caminho.is_absolute():
        caminho = BASE_DIR / caminho
    return caminho


def _lista(valor: str) -> List[str]:
    itens = [v.strip() for v in valor.split(",") if v.strip()]
    return itens or ["*"]


class Settings:
    """Container simples de configurações lidas das variáveis de ambiente."""

    def __init__(self) -> None:
        self.APP_NAME: str = "Baguncinha Ei Iai"
        self.APP_VERSION: str = "1.0.0"

        self.GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "").strip()
        self.GEMINI_MODEL: str = os.getenv("GEMINI_MODEL", "gemini-3.8-flash").strip() or "gemini-3.8-flash"

        self.FIREBASE_PROJECT_ID: str = os.getenv("FIREBASE_PROJECT_ID", "").strip()
        self.FIREBASE_CREDENTIALS_JSON: str = os.getenv("FIREBASE_CREDENTIALS_JSON", "").strip()
        self.FIREBASE_CREDENTIALS_PATH: Path = _resolver_caminho(
            os.getenv("FIREBASE_CREDENTIALS_PATH", "serviceAccountKey.json").strip() or "serviceAccountKey.json"
        )

        self.ADMIN_MASTER_KEY: str = os.getenv("ADMIN_MASTER_KEY", "").strip()
        self.WEBHOOK_SECRET_TOKEN: str = os.getenv("WEBHOOK_SECRET_TOKEN", "").strip()
        self.META_ACCESS_TOKEN: str = os.getenv("META_ACCESS_TOKEN", "").strip()

        self.PORT: int = int(os.getenv("PORT", "8000"))
        self.ENVIRONMENT: str = os.getenv("ENVIRONMENT", "development").strip().lower()
        self.MAX_UPLOAD_MB: int = int(os.getenv("MAX_UPLOAD_MB", "20"))
        self.CORS_ORIGINS: List[str] = _lista(os.getenv("CORS_ORIGINS", "*"))

    @property
    def is_development(self) -> bool:
        return self.ENVIRONMENT in {"development", "dev", "local"}

    @property
    def max_upload_bytes(self) -> int:
        return self.MAX_UPLOAD_MB * 1024 * 1024


settings = Settings()


def agora() -> datetime:
    """Data/hora atual no fuso de Bebedouro - SP."""
    return datetime.now(TZ_BRASIL)


def agora_iso() -> str:
    """Timestamp ISO8601 com offset -03:00 (ordenável lexicograficamente)."""
    return agora().isoformat(timespec="seconds")


def hoje_str() -> str:
    """Data atual no formato YYYY-MM-DD."""
    return agora().date().isoformat()
