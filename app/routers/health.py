"""Health check da API e do banco de dados Firestore."""

from fastapi import APIRouter, HTTPException, status

from app.config import settings
from app.services import firestore_service as fs

router = APIRouter(tags=["Health"])


@router.get("/health", summary="Verifica se a API e o Firestore estão ativos")
def health() -> dict:
    db_ok, msg = fs.testar_conexao_firestore()
    if not db_ok:
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
