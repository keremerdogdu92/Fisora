from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from fastapi import HTTPException

from app.api.phase0_review_export import entry_payload, export_package_payload, safe_export_file_name, write_export_manifest
from app.api.phase0_schemas import ExportPackagePayload, StoredExportPackagePayload, WorkspaceExportPackagePayload
from app.domain.export_adapters import get_export_adapter, write_export_file
from app.domain.workspace_exports import (
    apply_document_safety_holds,
    build_workspace_export_package,
)


OperationRecorder = Callable[..., dict[str, object]]
AccessChecker = Callable[..., dict[str, object]]


class ExportService:
    def __init__(
        self,
        *,
        store: Any,
        export_path: Path,
        record_operation_event: OperationRecorder,
        require_client_access: AccessChecker,
    ) -> None:
        self.store = store
        self.export_path = export_path
        self.record_operation_event = record_operation_event
        self.require_client_access = require_client_access

    def export_package(self, payload: ExportPackagePayload) -> dict[str, object]:
        return export_package_payload(payload)

    def store_export_package(self, payload: StoredExportPackagePayload) -> dict[str, object]:
        if not payload.client_id.strip():
            raise HTTPException(status_code=400, detail="client_id is required for persistence")
        package = self.export_package(payload.package)
        self._assert_documents_not_held(
            client_id=payload.client_id,
            document_refs=[
                str(entry.get("document_ref") or "")
                for entry in package.get("entries", [])
                if isinstance(entry, dict)
            ],
        )
        saved = self.store.save_export_package(client_id=payload.client_id, package=package)
        self.record_operation_event(
            store=self.store,
            client_id=payload.client_id,
            event_type="export_package_saved",
            status="ok",
            message="Export package payload store'a kaydedildi.",
            metadata={
                "export_type": package.get("export_type"),
                "entry_count": package.get("entry_count"),
                "excluded_document_refs": package.get("excluded_document_refs", []),
                "excluded_documents": package.get("excluded_documents", []),
            },
        )
        return saved

    def store_export_package_from_workspace(
        self,
        *,
        payload: WorkspaceExportPackagePayload,
        user_id: str | None,
    ) -> dict[str, object]:
        if not payload.client_id.strip():
            raise HTTPException(status_code=400, detail="client_id is required for persistence")
        self.require_client_access(
            client_id=payload.client_id,
            user_id=user_id,
            allowed_roles=("accountant", "admin"),
        )
        workspace_reader = getattr(self.store, "authoritative_export_workspace", None)
        workspace = (
            workspace_reader(payload.client_id)
            if callable(workspace_reader)
            else self.store.get_workspace(payload.client_id)
        )
        holds_reader = getattr(self.store, "active_document_safety_holds", None)
        if callable(holds_reader):
            workspace = apply_document_safety_holds(
                workspace,
                holds=holds_reader(client_id=payload.client_id),
            )
        try:
            adapter = get_export_adapter(payload.export_type)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        build = build_workspace_export_package(workspace, export_type=adapter.export_type)
        output_filename = safe_export_file_name(payload.client_id, adapter.export_type, adapter.file_extension)
        output_path = self.export_path / payload.client_id / output_filename
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
            "excluded_documents": list(build.package.excluded_documents),
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
        saved = self.store.save_export_package(client_id=payload.client_id, package=package_payload)
        self.record_operation_event(
            store=self.store,
            client_id=payload.client_id,
            event_type="workspace_export_package_created",
            status="ok" if package_payload["entry_count"] else "warning",
            message="Workspace'ten indirilebilir export paketi uretildi.",
            metadata={
                "export_type": package_payload["export_type"],
                "entry_count": package_payload["entry_count"],
                "candidate_count": package_payload["candidate_count"],
                "excluded_document_refs": package_payload["excluded_document_refs"],
                "excluded_documents": package_payload["excluded_documents"],
                "output_filename": package_payload["output_filename"],
                "manifest_filename": package_payload["manifest_filename"],
            },
        )
        return saved

    def export_download_path(self, *, client_id: str, file_name: str, user_id: str | None) -> Path:
        self.require_client_access(client_id=client_id, user_id=user_id)
        safe_name = Path(file_name).name
        workspace = self.store.get_workspace(client_id)
        for record in reversed(workspace.get("export_packages", [])):
            package = record.get("package") or {}
            if safe_name not in {
                str(package.get("output_filename") or ""),
                str(package.get("manifest_filename") or ""),
            }:
                continue
            self._assert_documents_not_held(
                client_id=client_id,
                document_refs=[
                    str(entry.get("document_ref") or "")
                    for entry in package.get("entries", [])
                    if isinstance(entry, dict)
                ],
            )
            break
        path = self.export_path / client_id / safe_name
        if not path.exists() or not path.is_file():
            raise HTTPException(status_code=404, detail="export file not found")
        return path

    def _assert_documents_not_held(
        self,
        *,
        client_id: str,
        document_refs: list[str],
    ) -> None:
        holds_reader = getattr(self.store, "active_document_safety_holds", None)
        requested = [item for item in document_refs if item]
        if not callable(holds_reader) or not requested:
            return
        holds = holds_reader(client_id=client_id, document_refs=requested)
        if holds:
            raise HTTPException(
                status_code=409,
                detail={
                    "reason": "qnb_external_status_hold",
                    "document_refs": sorted(
                        {
                            str(hold.get("document_ref") or "")
                            for hold in holds
                            if str(hold.get("document_ref") or "")
                        }
                    ),
                    "hold_codes": sorted(
                        {
                            str(hold.get("hold_code") or "")
                            for hold in holds
                            if str(hold.get("hold_code") or "")
                        }
                    ),
                },
            )

    def mark_export_package_downloaded(self, *, client_id: str, output_filename: str) -> None:
        self.store.mark_export_package_downloaded(client_id=client_id, output_filename=output_filename)
        self.record_operation_event(
            store=self.store,
            client_id=client_id,
            event_type="export_package_downloaded",
            status="ok",
            message="Export CSV indirildi.",
            metadata={"output_filename": output_filename},
        )
