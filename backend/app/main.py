from fastapi import FastAPI

from app.api.phase0 import router as phase0_router


app = FastAPI(
    title="Muhasebe Operasyon Otomasyonu",
    version="0.0.1",
    description="Phase 0 validation API scaffold.",
)

app.include_router(phase0_router, prefix="/phase0", tags=["phase0"])


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}

