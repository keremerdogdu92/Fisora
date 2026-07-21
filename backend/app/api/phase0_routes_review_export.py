from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Cookie, Header, HTTPException, Request
from fastapi.responses import FileResponse

from app.api.phase0_context import (
    SESSION_COOKIE_NAME,
    get_export_service,
    get_review_service,
    request_user_id,
)
from app.api.rate_limit import enforce_rate_limit
from app.api.phase0_schemas import (
    ExportPackagePayload,
    JournalReopenPayload,
    ReviewDecisionPayload,
    ReviewRulePreviewPayload,
    StoredExportPackagePayload,
    StoredReviewDecisionPayload,
    WorkspaceExportPackagePayload,
)


router = APIRouter()


@router.post("/review/learning-event")
def review_learning_event(payload: ReviewDecisionPayload) -> dict[str, object]:
    return get_review_service().review_learning_event(payload)


@router.post("/store/review-decision")
def store_review_decision(
    payload: StoredReviewDecisionPayload,
    x_fisora_user_id: str | None = Header(default=None, alias="X-Fisora-User-Id"),
    x_fisora_session: str | None = Header(default=None, alias="X-Fisora-Session"),
    fisora_session: str | None = Cookie(default=None, alias=SESSION_COOKIE_NAME),
) -> dict[str, object]:
    return get_review_service().store_review_decision(
        payload=payload,
        user_id=request_user_id(x_fisora_user_id, x_fisora_session, fisora_session),
    )


@router.post("/store/journal/reopen")
def reopen_journal(
    payload: JournalReopenPayload,
    x_fisora_user_id: str | None = Header(default=None, alias="X-Fisora-User-Id"),
    x_fisora_session: str | None = Header(default=None, alias="X-Fisora-Session"),
    fisora_session: str | None = Cookie(default=None, alias=SESSION_COOKIE_NAME),
) -> dict[str, object]:
    return get_review_service().reopen_journal(
        payload=payload,
        user_id=request_user_id(x_fisora_user_id, x_fisora_session, fisora_session),
    )


@router.post("/store/review-rule/preview")
def preview_review_rule(
    payload: ReviewRulePreviewPayload,
    x_fisora_user_id: str | None = Header(default=None, alias="X-Fisora-User-Id"),
    x_fisora_session: str | None = Header(default=None, alias="X-Fisora-Session"),
    fisora_session: str | None = Cookie(default=None, alias=SESSION_COOKIE_NAME),
) -> dict[str, object]:
    return get_review_service().preview_review_rule(
        payload=payload,
        user_id=request_user_id(x_fisora_user_id, x_fisora_session, fisora_session),
    )


@router.post("/export/package")
def export_package(payload: ExportPackagePayload, request: Request) -> dict[str, object]:
    enforce_rate_limit(scope="export", request=request)
    return get_export_service().export_package(payload)


@router.post("/store/export-package")
def store_export_package(payload: StoredExportPackagePayload, request: Request) -> dict[str, object]:
    enforce_rate_limit(scope="export", key=payload.client_id.strip(), request=request)
    return get_export_service().store_export_package(payload)


@router.post("/store/export-package/from-workspace")
def store_export_package_from_workspace(
    payload: WorkspaceExportPackagePayload,
    request: Request,
    x_fisora_user_id: str | None = Header(default=None, alias="X-Fisora-User-Id"),
    x_fisora_session: str | None = Header(default=None, alias="X-Fisora-Session"),
    fisora_session: str | None = Cookie(default=None, alias=SESSION_COOKIE_NAME),
) -> dict[str, object]:
    enforce_rate_limit(scope="export", key=payload.client_id.strip(), request=request)
    return get_export_service().store_export_package_from_workspace(
        payload=payload,
        user_id=request_user_id(x_fisora_user_id, x_fisora_session, fisora_session),
    )


@router.get("/store/export-package/download/{client_id}/{file_name}")
def download_export_package(
    client_id: str,
    file_name: str,
    x_fisora_user_id: str | None = Header(default=None, alias="X-Fisora-User-Id"),
    x_fisora_session: str | None = Header(default=None, alias="X-Fisora-Session"),
    fisora_session: str | None = Cookie(default=None, alias=SESSION_COOKIE_NAME),
) -> FileResponse:
    service = get_export_service()
    path = service.export_download_path(
        client_id=client_id,
        file_name=file_name,
        user_id=request_user_id(x_fisora_user_id, x_fisora_session, fisora_session),
    )
    safe_name = Path(file_name).name
    if path.suffix.lower() == ".csv":
        service.mark_export_package_downloaded(client_id=client_id, output_filename=safe_name)
    media_type = "application/json; charset=utf-8" if path.suffix.lower() == ".json" else "text/csv; charset=utf-8"
    return FileResponse(path, filename=safe_name, media_type=media_type)
