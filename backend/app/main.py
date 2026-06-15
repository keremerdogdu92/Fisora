import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.phase0 import router as phase0_router


DEFAULT_CORS_ALLOW_ORIGINS = (
    'http://localhost:3000,'
    'http://localhost:3100,'
    'http://127.0.0.1:3000,'
    'http://127.0.0.1:3100,'
    'http://192.168.1.101:3000'
)


def cors_allow_origins() -> list[str]:
    raw = os.environ.get("FISORA_CORS_ALLOW_ORIGINS", "").strip() or DEFAULT_CORS_ALLOW_ORIGINS
    return [origin.strip() for origin in raw.split(",") if origin.strip()]


app = FastAPI(
    title="Muhasebe Operasyon Otomasyonu",
    version="0.0.1",
    description="Phase 0 validation API scaffold.",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_allow_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(phase0_router, prefix="/phase0", tags=["phase0"])


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}

