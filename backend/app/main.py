from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.phase0 import router as phase0_router


app = FastAPI(
    title="Muhasebe Operasyon Otomasyonu",
    version="0.0.1",
    description="Phase 0 validation API scaffold.",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://localhost:3100",
        "http://127.0.0.1:3000",
        "http://127.0.0.1:3100",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(phase0_router, prefix="/phase0", tags=["phase0"])


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}

