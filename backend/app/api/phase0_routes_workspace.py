from __future__ import annotations

from pathlib import Path
import sys
import tempfile

from fastapi import APIRouter, Cookie, File, Form, Header, HTTPException, UploadFile

from app.api.phase0_context import (
    SESSION_COOKIE_NAME,
    get_workspace_service,
)
from app.api.phase0_schemas import (
    ChartAccountsStorePayload,
    ClientDocumentsDeletePayload,
    ClientOnboardingPackagePayload,
    ClientProfilePayload,
)
from app.domain.tax_certificates import parse_tax_certificate_file as _parse_tax_certificate_file


router = APIRouter()


def parse_tax_certificate_file(path: Path):
    phase0 = sys.modules.get("app.api.phase0")
    parser = getattr(phase0, "parse_tax_certificate_file", _parse_tax_certificate_file) if phase0 else _parse_tax_certificate_file
    return parser(path)


@router.post("/onboarding/check")
def onboarding_check(payload: ClientProfilePayload) -> dict[str, object]:
    return get_workspace_service().onboarding_check(payload)


@router.post("/store/client")
def store_client(payload: ClientProfilePayload) -> dict[str, object]:
    return get_workspace_service().store_client(payload)


@router.get("/store/clients")
def store_clients(
    x_fisora_user_id: str | None = Header(default=None, alias="X-Fisora-User-Id"),
    x_fisora_session: str | None = Header(default=None, alias="X-Fisora-Session"),
    fisora_session: str | None = Cookie(default=None, alias=SESSION_COOKIE_NAME),
) -> dict[str, object]:
    return get_workspace_service().store_clients(
        x_fisora_user_id=x_fisora_user_id,
        x_fisora_session=x_fisora_session,
        fisora_session=fisora_session,
    )


@router.post("/store/chart-accounts")
def store_chart_accounts(payload: ChartAccountsStorePayload) -> dict[str, object]:
    return get_workspace_service().store_chart_accounts(payload)


@router.post("/store/chart-accounts/upload")
async def store_chart_accounts_upload(
    client_id: str = Form(...),
    file: UploadFile = File(...),
    x_fisora_user_id: str | None = Header(default=None, alias="X-Fisora-User-Id"),
    x_fisora_session: str | None = Header(default=None, alias="X-Fisora-Session"),
    fisora_session: str | None = Cookie(default=None, alias=SESSION_COOKIE_NAME),
) -> dict[str, object]:
    original_name = Path(file.filename or "chart_accounts.csv").name
    content = await file.read()
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir) / original_name
        temp_path.write_bytes(content)
        return get_workspace_service().store_chart_accounts_upload(
            client_id=client_id,
            original_name=original_name,
            file_path=temp_path,
            x_fisora_user_id=x_fisora_user_id,
            x_fisora_session=x_fisora_session,
            fisora_session=fisora_session,
        )


@router.post("/chart-accounts/parse")
async def parse_chart_accounts_upload(file: UploadFile = File(...)) -> dict[str, object]:
    original_name = Path(file.filename or "chart_accounts.csv").name
    content = await file.read()
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir) / original_name
        temp_path.write_bytes(content)
        return get_workspace_service().parse_chart_accounts_upload(
            original_name=original_name,
            file_path=temp_path,
        )


@router.post("/store/client-onboarding-package")
def store_client_onboarding_package(
    payload: ClientOnboardingPackagePayload,
    x_fisora_user_id: str | None = Header(default=None, alias="X-Fisora-User-Id"),
    x_fisora_session: str | None = Header(default=None, alias="X-Fisora-Session"),
    fisora_session: str | None = Cookie(default=None, alias=SESSION_COOKIE_NAME),
) -> dict[str, object]:
    return get_workspace_service().store_client_onboarding_package(
        payload,
        x_fisora_user_id=x_fisora_user_id,
        x_fisora_session=x_fisora_session,
        fisora_session=fisora_session,
    )


@router.post("/tax-certificate/parse")
async def parse_tax_certificate_upload(file: UploadFile = File(...)) -> dict[str, object]:
    suffix = Path(file.filename or "tax-certificate.pdf").suffix.lower() or ".pdf"
    if suffix not in {".pdf", ".png", ".jpg", ".jpeg", ".tif", ".tiff"}:
        raise HTTPException(status_code=400, detail="unsupported tax certificate file type")
    content = await file.read()
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as handle:
        handle.write(content)
        temp_path = Path(handle.name)
    try:
        return parse_tax_certificate_file(temp_path).to_payload()
    finally:
        temp_path.unlink(missing_ok=True)


@router.get("/store/workspace/{client_id}")
def store_workspace(
    client_id: str,
    x_fisora_user_id: str | None = Header(default=None, alias="X-Fisora-User-Id"),
    x_fisora_session: str | None = Header(default=None, alias="X-Fisora-Session"),
    fisora_session: str | None = Cookie(default=None, alias=SESSION_COOKIE_NAME),
) -> dict[str, object]:
    return get_workspace_service().store_workspace(
        client_id=client_id,
        x_fisora_user_id=x_fisora_user_id,
        x_fisora_session=x_fisora_session,
        fisora_session=fisora_session,
    )


@router.post("/store/documents/delete")
def store_documents_delete(
    payload: ClientDocumentsDeletePayload,
    x_fisora_user_id: str | None = Header(default=None, alias="X-Fisora-User-Id"),
    x_fisora_session: str | None = Header(default=None, alias="X-Fisora-Session"),
    fisora_session: str | None = Cookie(default=None, alias=SESSION_COOKIE_NAME),
) -> dict[str, object]:
    return get_workspace_service().delete_client_documents(
        payload,
        x_fisora_user_id=x_fisora_user_id,
        x_fisora_session=x_fisora_session,
        fisora_session=fisora_session,
    )
