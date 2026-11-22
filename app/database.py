"""Inicialização do Firebase Admin SDK e acesso ao Cloud Firestore."""

import json
import logging
import os
from pathlib import Path
import threading
from typing import Optional

import firebase_admin
from firebase_admin import credentials, firestore

from app.config import settings

logger = logging.getLogger(__name__)

_lock = threading.Lock()
_db: Optional["firestore.firestore.Client"] = None


class Collections:
    """Nomes oficiais das coleções do Firestore."""

    CLIENTES = "clientes"
    LANCAMENTOS = "lancamentos"
    FECHAMENTOS = "fechamentos"
    LOGS_WEBHOOK = "logs_webhook"


def init_firebase() -> firebase_admin.App:
    """Inicializa (uma única vez) o app Firebase Admin.

    Regras de inicialização:
    1. Primeiro: variável de ambiente FIREBASE_CREDENTIALS_JSON (se existir e não estiver vazia).
    2. Segundo: arquivo local serviceAccountKey.json (no caminho configurado ou na raiz).
    3. Terceiro (fallback): firebase_admin.initialize_app() sem argumentos (autenticação nativa Google Cloud).
    """
    if firebase_admin._apps:
        try:
            return firebase_admin.get_app()
        except ValueError:
            pass

    # 1. Primeiro, verifique se existe a variável de ambiente FIREBASE_CREDENTIALS_JSON
    cred_json = os.getenv("FIREBASE_CREDENTIALS_JSON", "").strip() or getattr(settings, "FIREBASE_CREDENTIALS_JSON", "").strip()
    if cred_json:
        dados = json.loads(cred_json)
        cred = credentials.Certificate(dados)
        logger.info("Firebase inicializado via variável de ambiente FIREBASE_CREDENTIALS_JSON.")
        return firebase_admin.initialize_app(cred)

    # 2. Caso a variável não exista, verifique se o arquivo local serviceAccountKey.json existe
    caminho_local = getattr(settings, "FIREBASE_CREDENTIALS_PATH", Path("serviceAccountKey.json"))
    if caminho_local and Path(caminho_local).exists():
        cred = credentials.Certificate(str(caminho_local))
        logger.info("Firebase inicializado com arquivo de credencial: %s", caminho_local)
        return firebase_admin.initialize_app(cred)

    if os.path.exists("serviceAccountKey.json"):
        cred = credentials.Certificate("serviceAccountKey.json")
        logger.info("Firebase inicializado com serviceAccountKey.json na raiz.")
        return firebase_admin.initialize_app(cred)

    # 3. Fallback: chame apenas firebase_admin.initialize_app() sem argumentos (autenticação nativa do Google Cloud)
    logger.info("Nenhuma credencial explícita encontrada. Inicializando via autenticação nativa do Google Cloud.")
    return firebase_admin.initialize_app()


def get_db():
    """Retorna o cliente Firestore (singleton thread-safe)."""
    global _db
    if _db is None:
        with _lock:
            if _db is None:
                init_firebase()
                _db = firestore.client()
    return _db


class _FirestoreProxy:
    """Proxy para permitir acesso direto `db.collection(...)` e preservar `from app.database import db`."""

    def __getattr__(self, name: str):
        return getattr(get_db(), name)

    def __repr__(self) -> str:
        return f"<FirestoreProxy client={_db}>"


# Instância exportada do cliente Firestore: `db`
db = _FirestoreProxy()
