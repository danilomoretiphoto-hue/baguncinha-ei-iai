"""Ponto de entrada da aplicação FastAPI - Baguncinha Ei Iai."""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from app.config import STATIC_DIR, settings
from app.database import init_firebase
from app.routers import admin, api, consulta, health, whatsapp
from app.services.firestore_service import NotFoundError, RegraNegocioError
from app.services.gemini_service import GeminiServiceError

logging.basicConfig(
    level=logging.DEBUG if settings.is_development else logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
)
logging.getLogger("urllib3").setLevel(logging.WARNING)
logging.getLogger("httpx").setLevel(logging.WARNING)
logger = logging.getLogger("agente_like_baguncinha")


@asynccontextmanager
async def lifespan(_: FastAPI):
    try:
        init_firebase()
        logger.info("Firebase Admin SDK pronto.")
    except Exception as exc:  # noqa: BLE001
        logger.error("Falha ao inicializar o Firebase: %s", exc)
    if not settings.GEMINI_API_KEY:
        logger.warning("GEMINI_API_KEY não configurada: endpoints de ingestão falharão.")
    if not settings.ADMIN_MASTER_KEY:
        logger.warning("ADMIN_MASTER_KEY não configurada: API admin indisponível.")
    yield


app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    description=(
        "Gerenciamento inteligente de comandas, lançamentos diários, fiados e prestação de contas "
        "do **Baguncinha Ei Iai** (Bebedouro - SP), com extração multimodal via **Gemini 2.5 Flash** "
        "e persistência no **Cloud Firestore**.\n\n"
        "- **Consulta do Cliente**: header `X-API-Key`\n"
        "- **Administração**: header `X-Admin-Key`\n"
        "- **Webhook WhatsApp**: `?token=` / `X-Webhook-Token` / `Authorization: Bearer`"
    ),
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["Content-Disposition"],
)


@app.exception_handler(NotFoundError)
async def _not_found(_: Request, exc: NotFoundError):
    return JSONResponse(status_code=404, content={"detail": str(exc)})


@app.exception_handler(RegraNegocioError)
async def _regra_negocio(_: Request, exc: RegraNegocioError):
    return JSONResponse(status_code=400, content={"detail": str(exc)})


@app.exception_handler(GeminiServiceError)
async def _gemini_error(_: Request, exc: GeminiServiceError):
    return JSONResponse(status_code=502, content={"detail": f"Falha na IA Gemini: {exc}"})


app.include_router(health.router)
app.include_router(consulta.router)
app.include_router(admin.router)
app.include_router(api.router)
app.include_router(whatsapp.router)

app.mount("/static", StaticFiles(directory=str(STATIC_DIR), html=True), name="static")


@app.get("/", include_in_schema=False)
def raiz():
    return RedirectResponse(url="/static/index.html")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app.main:app", host="0.0.0.0", port=settings.PORT, reload=settings.is_development)
