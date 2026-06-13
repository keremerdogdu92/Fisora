from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Cookie, Header, HTTPException
from fastapi.responses import FileResponse

from app.api.phase0_context import (
    SESSION_COOKIE_NAME,
    default_export_path,
    get_workflow_store,
    record_operation_event,
    request_user_id,
    require_client_access,
)
from app.api.phase0_review_export import (
    entry_payload,
    export_package_payload,
    safe_export_file_name,
    workspace_document,
    write_export_manifest,
)
from app.api.phase0_schemas import (
    ExportPackagePayload,
    ReviewDecisionPayload,
    StoredExportPackagePayload,
    StoredReviewDecisionPayload,
    WorkspaceExportPackagePayload,
)
from app.domain.export_adapters import get_export_adapter, write_export_file
from app.domain.learning_intelligence import enrich_learning_event
from app.domain.review_learning import ReviewDecision, build_learning_event
from app.domain.workspace_exports import build_workspace_export_package


router = APIRouter()


@router.post("/review/learning-event")
def review_learning_event(payload: ReviewDecisionPayload) -> dict[str, object]:
    decision = ReviewDecision(
        document_ref=payload.document_ref,
        action=payload.action,
        reviewer=payload.reviewer,
        corrected_account_code=payload.corrected_account_code,
        corrected_counterparty_code=payload.corrected_counterparty_code,
        category=payload.category,
        reason=payload.reason,
        apply_to_similar=payload.apply_to_similar,
        statement_line_no=payload.statement_line_no,
    )
    event = build_learning_event(
        decision,
        prior_consistent_approval_count=payload.prior_consistent_approval_count,
    )
    return {
        "document_ref": event.document_ref,
        "scope": event.scope,
        "action": event.action,
        "category": event.category,
        "corrected_account_code": event.corrected_account_code,
        "corrected_counterparty_code": event.corrected_counterparty_code,
        "reason": event.reason,
        "automation_candidate": event.automation_candidate,
        "statement_line_no": event.statement_line_no,
    }


@router.post("/store/review-decision")
def store_review_decision(
    payload: StoredReviewDecisionPayload,
    x_fisora_user_id: str | None = Header(default=None, alias="X-Fisora-User-Id"),
    x_fisora_session: str | None = Header(default=None, alias="X-Fisora-Session"),
    fisora_session: str | None = Cookie(default=None, alias=SESSION_COOKIE_NAME),
) -> dict[str, object]:
    if not payload.client_id.strip():
        raise HTTPException(status_code=400, detail="client_id is required for persistence")
    require_client_access(
        client_id=payload.client_id,
        user_id=request_user_id(x_fisora_user_id, x_fisora_session, fisora_session),
        allowed_roles=("accountant", "admin"),
    )
    store = get_workflow_store()
    workspace = store.get_workspace(payload.client_id)
    event = review_learning_event(payload.decision)
    event = enrich_learning_event(
        event,
        client_id=payload.client_id,
        decision=payload.decision.model_dump(),
        document=workspace_document(workspace, payload.decision.document_ref),
        prior_learning_events=workspace.get("learning_events") or (),
    )
    saved = store.save_review_decision(
        client_id=payload.client_id,
        decision=payload.decision.model_dump(),
        learning_event=event,
    )
    record_operation_event(
        store=store,
        client_id=payload.client_id,
        event_type="review_decision_saved",
        status="ok",
        message="Musavir review karari ve learning event kaydedildi.",
        metadata={
            "document_ref": payload.decision.document_ref,
            "action": payload.decision.action,
            "reviewer": payload.decision.reviewer,
            "automation_candidate": event.get("automation_candidate", False),
        },
    )
    return saved


@router.post("/export/package")
def export_package(payload: ExportPackagePayload) -> dict[str, object]:
    return export_package_payload(payload)


@router.post("/store/export-package")
def store_export_package(payload: StoredExportPackagePayload) -> dict[str, object]:
    if not payload.client_id.strip():
        raise HTTPException(status_code=400, detail="client_id is required for persistence")
    package = export_package(payload.package)
    store = get_workflow_store()
    saved = store.save_export_package(client_id=payload.client_id, package=package)
    record_operation_event(
        store=store,
        client_id=payload.client_id,
        event_type="export_package_saved",
        status="ok",
        message="Export package payload store'a kaydedildi.",
        metadata={
            "export_type": package.get("export_type"),
            "entry_count": package.get("entry_count"),
            "excluded_document_refs": package.get("excluded_document_refs", []),
        },
    )
    return saved


@router.post("/store/export-package/from-workspace")
def store_export_package_from_workspace(
    payload: WorkspaceExportPackagePayload,
    x_fisora_user_id: str | None = Header(default=None, alias="X-Fisora-User-Id"),
    x_fisora_session: str | None = Header(default=None, alias="X-Fisora-Session"),
    fisora_session: str | None = Cookie(default=None, alias=SESSION_COOKIE_NAME),
) -> dict[str, object]:
    if not payload.client_id.strip():
        raise HTTPException(status_code=400, detail="client_id is required for persistence")
    require_client_access(
        client_id=payload.client_id,
        user_id=request_user_id(x_fisora_user_id, x_fisora_session, fisora_session),
        allowed_roles=("accountant", "admin"),
    )
    store = get_workflow_store()
    workspace = store.get_workspace(payload.client_id)
    try:
        adapter = get_export_adapter(payload.export_type)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    build = build_workspace_export_package(workspace, export_type=adapter.export_type)
    output_filename = safe_export_file_name(payload.client_id, adapter.export_type, adapter.file_extension)
    output_path = default_export_path() / payload.client_id / output_filename
    write_export_file(
        adapter=adapter,
        entries=build.package.entries,
        output_path=output_path,
        client_id=payload.client_id,
    )
    package_payload = {
        "export_type": build.package.export_type,
        "adapter": {
            "display_name": adapter.display_name,
            "file_extension": adapter.file_extension,
            "mime_type": adapter.mime_type,
            "verified_in_zirve": adapter.verified_in_zirve,
            "validation_status": adapter.validation_status,
            "field_mapping_notes": list(adapter.field_mapping_notes),
        },
        "candidate_count": build.candidate_count,
        "entry_count": len(build.package.entries),
        "excluded_document_refs": list(build.package.excluded_document_refs),
        "output_filename": output_filename,
        "output_path": str(output_path),
        "download_url": f"/phase0/store/export-package/download/{payload.client_id}/{output_filename}",
        "entries": [entry_payload(entry) for entry in build.package.entries],
    }
    manifest = write_export_manifest(client_id=payload.client_id, output_path=output_path, package_payload=package_payload)
    package_payload.update(
        {
            **manifest,
            "manifest_download_url": f"/phase0/store/export-package/download/{payload.client_id}/{manifest['manifest_filename']}",
        }
    )
    saved = store.save_export_package(client_id=payload.client_id, package=package_payload)
    record_operation_event(
        store=store,
        client_id=payload.client_id,
        event_type="workspace_export_package_created",
        status="ok" if package_payload["entry_count"] else "warning",
        message="Workspace'ten indirilebilir export paketi uretildi.",
        metadata={
            "export_type": package_payload["export_type"],
            "entry_count": package_payload["entry_count"],
            "candidate_count": package_payload["candidate_count"],
            "excluded_document_refs": package_payload["excluded_document_refs"],
            "output_filename": package_payload["output_filename"],
            "manifest_filename": package_payload["manifest_filename"],
        },
    )
    return saved


@router.get("/store/export-package/download/{client_id}/{file_name}")
def download_export_package(
    client_id: str,
    file_name: str,
    x_fisora_user_id: str | None = Header(default=None, alias="X-Fisora-User-Id"),
    x_fisora_session: str | None = Header(default=None, alias="X-Fisora-Session"),
    fisora_session: str | None = Cookie(default=None, alias=SESSION_COOKIE_NAME),
) -> FileResponse:
    require_client_access(
        client_id=client_id,
        user_id=request_user_id(x_fisora_user_id, x_fisora_session, fisora_session),
    )
    safe_name = Path(file_name).name
    path = default_export_path() / client_id / safe_name
    if not path.exists() or not path.is_file():
        raise HTTPException(status_code=404, detail="export file not found")
    if path.suffix.lower() == ".csv":
        get_workflow_store().mark_export_package_downloaded(client_id=client_id, output_filename=safe_name)
        record_operation_event(
            store=get_workflow_store(),
            client_id=client_id,
            event_type="export_package_downloaded",
            status="ok",
            message="Export CSV indirildi.",
            metadata={"output_filename": safe_name},
        )
    media_type = "application/json; charset=utf-8" if path.suffix.lower() == ".json" else "text/csv; charset=utf-8"
    return FileResponse(path, filename=safe_name, media_type=media_type)
