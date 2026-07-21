from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict
import hashlib
import mimetypes
from os import environ
from pathlib import Path
from typing import Any

from fastapi import HTTPException

from app.domain.business_relevance import ClientProfile, check_client_onboarding
from app.domain.document_uploads import store_document_content
from app.domain.research_harness import ResearchHarness, build_research_runtime_from_env
from app.domain.tax_certificates import parse_tax_certificate_file
from app.workflows.document_processing import parser_kind_for_document_type, process_queued_documents


OperationRecorder = Callable[..., dict[str, object]]
AccessChecker = Callable[..., dict[str, object]]


def file_fingerprint(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def has_tax_certificate_core_fields(tax_certificate: dict[str, object]) -> bool:
    return any(
        str(tax_certificate.get(field) or "").strip()
        for field in ("nace_code", "tax_id", "tckn", "vkn", "tax_identifier", "title", "legal_name", "activity_description")
    )


class DocumentService:
    def __init__(
        self,
        *,
        store: Any,
        document_storage_path: Path,
        record_operation_event: OperationRecorder,
        require_client_access: AccessChecker,
    ) -> None:
        self.store = store
        self.document_storage_path = document_storage_path
        self.record_operation_event = record_operation_event
        self.require_client_access = require_client_access

    def store_document_upload(
        self,
        *,
        client_id: str,
        document_type: str,
        intake_category: str = "",
        period: str = "",
        file_name: str,
        uploaded_by: str,
        uploaded_by_user_id: str = "",
        request_user_id: str | None = None,
        session_kind: str = "",
        delegated_by_user_id: str = "",
        delegated_client_id: str = "",
        content: bytes | None = None,
        size_bytes: int | None = None,
        sha256: str | None = None,
        retention_policy_days: int = 90,
    ) -> dict[str, object]:
        if not client_id.strip():
            raise HTTPException(status_code=400, detail="client_id is required for document upload")
        request_user = (request_user_id or "").strip()
        effective_user_id = uploaded_by_user_id.strip() or uploaded_by.strip() or request_user
        if request_user and effective_user_id and request_user != effective_user_id:
            raise HTTPException(
                status_code=403,
                detail={
                    "allowed": False,
                    "reason": "mock_user_header_mismatch",
                    "user_id": request_user,
                    "payload_user_id": effective_user_id,
                },
            )
        if not effective_user_id:
            raise HTTPException(status_code=403, detail="portal user is required for document upload")
        access = self.store.verify_portal_access(client_id=client_id, user_id=effective_user_id)
        if not access.get("allowed"):
            raise HTTPException(status_code=403, detail=access)
        actor_metadata = self._upload_actor_metadata(
            client_id=client_id,
            access=access,
            session_kind=session_kind,
            delegated_by_user_id=delegated_by_user_id,
            delegated_client_id=delegated_client_id,
        )
        onboarding = self._workspace_onboarding_check(client_id)
        try:
            document = store_document_content(
                base_dir=self.document_storage_path,
                client_id=client_id,
                file_name=file_name,
                document_type=document_type,
                intake_category=intake_category,
                period=period,
                uploaded_by=uploaded_by,
                content=content,
                declared_size_bytes=size_bytes,
                declared_sha256=sha256,
                retention_days=retention_policy_days,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        document_payload = asdict(document)
        document_payload["uploaded_by_user_id"] = effective_user_id
        document_payload["portal_access_reason"] = access.get("reason", "")
        document_payload.update(actor_metadata)
        document_payload["client_onboarding_ready"] = onboarding.is_ready
        document_payload["client_onboarding_missing_fields"] = list(onboarding.missing_fields)
        saved = self.store.save_uploaded_document(
            client_id=client_id,
            document=document_payload,
        )
        self.store.record_document_pipeline_event(
            client_id=client_id,
            document_ref=str(saved["document_ref"]),
            step="uploaded",
            status="ok",
            message_tr="Belge yüklendi.",
            debug_code="uploaded",
            details={
                "file_name": file_name,
                "document_type": document_type,
                "intake_category": saved.get("intake_category", ""),
                "period": saved.get("period", ""),
                "size_bytes": saved.get("size_bytes", 0),
                "uploaded_by_user_id": effective_user_id,
                "uploaded_by_role": saved.get("uploaded_by_role", ""),
                "upload_actor_type": saved.get("upload_actor_type", ""),
                "delegated_by_user_id": saved.get("delegated_by_user_id", ""),
                "delegated_client_id": saved.get("delegated_client_id", ""),
                "client_onboarding_ready": saved.get("client_onboarding_ready", False),
                "client_onboarding_missing_fields": saved.get("client_onboarding_missing_fields", []),
            },
        )
        storage_path = Path(str(saved.get("storage_path") or ""))
        if storage_path.exists() and storage_path.is_file():
            self.store.record_document_pipeline_event(
                client_id=client_id,
                document_ref=str(saved["document_ref"]),
                step="file_preview_ready",
                status="ok",
                message_tr="Belge önizlenebiliyor.",
                debug_code="file_preview_ready",
                details={
                    "storage_backend": saved.get("storage_backend", ""),
                    "media_type": mimetypes.guess_type(file_name)[0] or "application/octet-stream",
                },
            )
        else:
            self.store.record_document_pipeline_event(
                client_id=client_id,
                document_ref=str(saved["document_ref"]),
                step="storage_missing",
                status="error",
                message_tr="Belge storage kaydı doğrulanamadı.",
                debug_code="storage_missing",
                details={"storage_path": str(storage_path)},
            )
        job = self.store.create_processing_job(
            client_id=client_id,
            document_ref=str(saved["document_ref"]),
            document_type=document_type,
            parser_kind=parser_kind_for_document_type(document_type),
            intake_category=str(saved.get("intake_category") or ""),
        )
        self.record_operation_event(
            store=self.store,
            client_id=client_id,
            event_type="document_uploaded",
            status="ok",
            message="Belge kaydedildi ve processing job kuyruga alindi.",
            metadata={
                "document_ref": saved["document_ref"],
                "document_type": document_type,
                "intake_category": saved.get("intake_category", ""),
                "period": saved.get("period", ""),
                "file_name": file_name,
                "processing_job_id": job["id"],
                "parser_kind": job["parser_kind"],
                "uploaded_by_user_id": effective_user_id,
                "uploaded_by_role": saved.get("uploaded_by_role", ""),
                "upload_actor_type": saved.get("upload_actor_type", ""),
                "delegated_by_user_id": saved.get("delegated_by_user_id", ""),
                "delegated_client_id": saved.get("delegated_client_id", ""),
                "client_onboarding_ready": saved.get("client_onboarding_ready", False),
                "client_onboarding_missing_fields": saved.get("client_onboarding_missing_fields", []),
            },
        )
        return {**saved, "processing_job": job}

    def _upload_actor_metadata(
        self,
        *,
        client_id: str,
        access: dict[str, object],
        session_kind: str = "",
        delegated_by_user_id: str = "",
        delegated_client_id: str = "",
    ) -> dict[str, object]:
        role = str(access.get("role") or "")
        normalized_delegated_by = delegated_by_user_id.strip()
        normalized_delegated_client = delegated_client_id.strip()
        if session_kind == "delegated_client" and normalized_delegated_by:
            if normalized_delegated_client and normalized_delegated_client != client_id:
                raise HTTPException(
                    status_code=403,
                    detail={
                        "allowed": False,
                        "reason": "delegated_client_mismatch",
                        "delegated_client_id": normalized_delegated_client,
                        "client_id": client_id,
                    },
                )
            delegate_access = self.store.verify_portal_access(client_id=client_id, user_id=normalized_delegated_by)
            delegate_role = str(delegate_access.get("role") or "")
            if not delegate_access.get("allowed") or delegate_role not in {"accountant", "admin"}:
                raise HTTPException(
                    status_code=403,
                    detail={
                        **delegate_access,
                        "reason": "delegated_actor_not_allowed",
                        "allowed_roles": ["accountant", "admin"],
                    },
                )
            return {
                "uploaded_by_role": role,
                "upload_actor_type": "delegated_accountant",
                "delegated_by_user_id": normalized_delegated_by,
                "delegated_client_id": normalized_delegated_client or client_id,
            }
        return {
            "uploaded_by_role": role,
            "upload_actor_type": role or "portal_user",
            "delegated_by_user_id": "",
            "delegated_client_id": "",
        }

    def _workspace_onboarding_check(self, client_id: str):
        workspace = self.store.get_workspace(client_id)
        client = workspace.get("client") or {}
        profile = dict(client.get("profile") or {})
        chart_accounts = workspace.get("chart_accounts") or {}
        return check_client_onboarding(
            ClientProfile(
                client_id=str(profile.get("client_id") or client_id),
                title=str(profile.get("title") or ""),
                tax_id=str(profile.get("tax_id") or ""),
                tckn=str(profile.get("tckn") or ""),
                vkn=str(profile.get("vkn") or ""),
                identity_type=str(profile.get("identity_type") or ""),
                tax_identifier=str(profile.get("tax_identifier") or ""),
                legal_name=str(profile.get("legal_name") or ""),
                trade_name=str(profile.get("trade_name") or ""),
                display_title=str(profile.get("display_title") or ""),
                tax_office=str(profile.get("tax_office") or ""),
                activity_description=str(profile.get("activity_description") or ""),
                nace_code=str(profile.get("nace_code") or ""),
                activity_tags=tuple(str(tag) for tag in profile.get("activity_tags") or []),
                nace_research_profile=dict(profile.get("nace_research_profile") or {}),
                workplace_addresses=tuple(str(address) for address in profile.get("workplace_addresses") or []),
                has_chart_accounts=bool(profile.get("has_chart_accounts") or chart_accounts.get("account_count")),
            )
        )

    def store_onboarding_attachment(
        self,
        *,
        client_id: str,
        attachment_type: str,
        file_name: str,
        uploaded_by: str,
        uploaded_by_user_id: str = "",
        request_user_id: str | None = None,
        content: bytes | None = None,
        size_bytes: int | None = None,
        retention_policy_days: int = 365,
    ) -> dict[str, object]:
        normalized_client_id = client_id.strip()
        if not normalized_client_id:
            raise HTTPException(status_code=400, detail="client_id is required for onboarding attachment")
        normalized_type = attachment_type.strip() or "tax_certificate"
        request_user = (request_user_id or "").strip()
        effective_user_id = uploaded_by_user_id.strip() or uploaded_by.strip() or request_user
        if request_user and effective_user_id and request_user != effective_user_id:
            raise HTTPException(
                status_code=403,
                detail={
                    "allowed": False,
                    "reason": "mock_user_header_mismatch",
                    "user_id": request_user,
                    "payload_user_id": effective_user_id,
                },
            )
        self.require_client_access(
            client_id=normalized_client_id,
            user_id=effective_user_id,
            allowed_roles=("accountant", "admin"),
        )
        try:
            document = store_document_content(
                base_dir=self.document_storage_path,
                client_id=normalized_client_id,
                file_name=file_name,
                document_type="special_document",
                intake_category="special_document",
                uploaded_by=uploaded_by,
                content=content,
                declared_size_bytes=size_bytes,
                retention_days=retention_policy_days,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        payload = asdict(document)
        attachment_ref = str(payload.get("document_id") or "")
        payload.update(
            {
                "attachment_ref": attachment_ref,
                "attachment_type": normalized_type,
                "uploaded_by_user_id": effective_user_id,
            }
        )
        tax_certificate: dict[str, object] = {}
        if normalized_type == "tax_certificate":
            try:
                storage_path = Path(str(payload.get("storage_path") or ""))
                payload["tax_certificate_fingerprint"] = file_fingerprint(storage_path)
                tax_certificate = parse_tax_certificate_file(storage_path).to_payload()
                payload.update(
                    {
                        "tax_certificate_parse_status": "parsed",
                        "tax_certificate_parse_error": "",
                        "tax_certificate": tax_certificate,
                    }
                )
                workspace = self.store.get_workspace(normalized_client_id)
                self._update_client_from_tax_certificate(
                    client_id=normalized_client_id,
                    workspace=workspace,
                    tax_certificate=tax_certificate,
                    nace_profile={},
                )
            except Exception as exc:  # pragma: no cover - exercised through API behavior, exact OCR errors vary by runtime
                payload.update(
                    {
                        "tax_certificate_parse_status": "failed",
                        "tax_certificate_parse_error": str(exc),
                        "tax_certificate": {},
                    }
                )
        saved = self.store.save_onboarding_attachment(client_id=normalized_client_id, attachment=payload)
        self.record_operation_event(
            store=self.store,
            client_id=normalized_client_id,
            event_type="onboarding_attachment_uploaded",
            status="ok",
            message="Onboarding eki kaydedildi.",
            metadata={
                "attachment_ref": saved["attachment_ref"],
                "attachment_type": saved["attachment_type"],
                "file_name": file_name,
                "uploaded_by_user_id": effective_user_id,
                "tax_certificate_parse_status": saved.get("tax_certificate_parse_status", ""),
            },
        )
        return saved

    def store_document_retention_run(self, *, delete_files: bool) -> dict[str, object]:
        summary = self.store.apply_document_retention(delete_files=delete_files)
        self.record_operation_event(
            store=self.store,
            client_id="__system__",
            event_type="document_retention_run",
            status="warning" if summary["deleted_count"] else "ok",
            message="90 gun belge retention job'u calisti.",
            metadata=summary,
        )
        return summary

    def store_document_retention_preview(self) -> dict[str, object]:
        summary = self.store.preview_document_retention()
        self.record_operation_event(
            store=self.store,
            client_id="__system__",
            event_type="document_retention_preview",
            status="warning" if summary["expired_count"] else "ok",
            message="90 gun belge retention onizlemesi hazirlandi.",
            metadata=summary,
        )
        return summary

    def store_document_retention_action(
        self,
        *,
        document_refs: list[str],
        action: str,
        delete_files: bool,
    ) -> dict[str, object]:
        try:
            summary = self.store.apply_document_retention_action(
                document_refs=document_refs,
                action=action,
                delete_files=delete_files,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        self.record_operation_event(
            store=self.store,
            client_id="__system__",
            event_type="document_retention_action",
            status="warning" if summary["deleted_count"] else "ok",
            message="Secili belge retention aksiyonu uygulandi.",
            metadata=summary,
        )
        return summary

    def store_processing_run(self, *, max_jobs: int) -> dict[str, object]:
        summary = process_queued_documents(self.store, max_jobs=max_jobs)
        self.record_operation_event(
            store=self.store,
            client_id="__system__",
            event_type="processing_run",
            status="error" if summary["failed_count"] else "ok",
            message="Worker kuyrugu manuel/API tetiklemesiyle calisti.",
            metadata=summary,
        )
        return summary

    def store_document_reprocess(
        self,
        *,
        client_id: str,
        document_ref: str,
        user_id: str | None,
    ) -> dict[str, object]:
        normalized_client_id = client_id.strip()
        normalized_ref = document_ref.strip()
        if not normalized_client_id or not normalized_ref:
            raise HTTPException(status_code=400, detail="client_id and document_ref are required")
        self.require_client_access(client_id=normalized_client_id, user_id=user_id)
        workspace = self.store.get_workspace(normalized_client_id)
        document = next(
            (
                item
                for item in workspace.get("uploaded_documents", [])
                if str(item.get("document_ref") or item.get("document_id") or item.get("original_file_name")) == normalized_ref
            ),
            None,
        )
        if not document:
            raise HTTPException(status_code=404, detail="uploaded document not found")
        document_type = str(document.get("document_type") or "invoice")
        intake_category = str(document.get("intake_category") or "")
        job = self.store.create_processing_job(
            client_id=normalized_client_id,
            document_ref=normalized_ref,
            document_type=document_type,
            parser_kind=parser_kind_for_document_type(document_type),
            intake_category=intake_category,
            force_requeue=True,
        )
        self.store.record_document_pipeline_event(
            client_id=normalized_client_id,
            document_ref=normalized_ref,
            step="reprocess_queued",
            status="info",
            message_tr="Belge yeni motorla yeniden isleme kuyruguna alindi.",
            debug_code="manual_reprocess_queued",
            details={
                "job_id": str(job.get("id") or ""),
                "document_type": document_type,
                "intake_category": intake_category,
            },
        )
        return {
            "client_id": normalized_client_id,
            "document_ref": normalized_ref,
            "processing_job": job,
        }

    def store_client_reprocess(
        self,
        *,
        client_id: str,
        user_id: str | None,
        max_jobs: int = 50,
    ) -> dict[str, object]:
        normalized_client_id = client_id.strip()
        if not normalized_client_id:
            raise HTTPException(status_code=400, detail="client_id is required")
        self.require_client_access(
            client_id=normalized_client_id,
            user_id=user_id,
            allowed_roles=("accountant", "admin"),
        )
        workspace = self.store.get_workspace(normalized_client_id)
        tax_certificate = self._reparse_latest_tax_certificate(workspace)
        nace_profile: dict[str, object] = {}
        if tax_certificate:
            nace_profile = self._research_nace_for_tax_certificate(tax_certificate)
            self._update_client_from_tax_certificate(
                client_id=normalized_client_id,
                workspace=workspace,
                tax_certificate=tax_certificate,
                nace_profile=nace_profile,
            )
        queued_jobs = []
        for document in workspace.get("uploaded_documents", []):
            document_ref = str(document.get("document_ref") or document.get("document_id") or "").strip()
            if not document_ref:
                continue
            document_type = str(document.get("document_type") or "invoice")
            job = self.store.create_processing_job(
                client_id=normalized_client_id,
                document_ref=document_ref,
                document_type=document_type,
                parser_kind=parser_kind_for_document_type(document_type),
                intake_category=str(document.get("intake_category") or ""),
            )
            queued_jobs.append(job)
            self.store.record_document_pipeline_event(
                client_id=normalized_client_id,
                document_ref=document_ref,
                step="client_reprocess_queued",
                status="info",
                message_tr="Mükellef bazlı yeniden işlemeyle belge yeni motor kuyruğuna alındı.",
                debug_code="client_reprocess_queued",
                details={"job_id": str(job.get("id") or "")},
            )
        processing_summary = {
            "queued_count": len(queued_jobs),
            "processed_count": 0,
            "completed_count": 0,
            "failed_count": 0,
            "current_status": "queued" if queued_jobs else "idle",
        }
        self.record_operation_event(
            store=self.store,
            client_id=normalized_client_id,
            event_type="client_reprocess",
            status="ok",
            message="Mükellef vergi levhası, NACE ve belgeleri yeni motor kuyruğuna alındı.",
            metadata={
                "queued_document_count": len(queued_jobs),
                "tax_certificate_reparsed": bool(tax_certificate),
                "nace_researched": bool(nace_profile),
            },
        )
        return {
            "client_id": normalized_client_id,
            "queued_document_count": len(queued_jobs),
            "queued_jobs": queued_jobs,
            "processing_summary": processing_summary,
            "tax_certificate": tax_certificate or {},
            "nace_research_profile": nace_profile,
        }

    def _reparse_latest_tax_certificate(self, workspace: dict[str, Any]) -> dict[str, object]:
        attachments = [
            attachment
            for attachment in workspace.get("onboarding_attachments", [])
            if str(attachment.get("attachment_type") or "") == "tax_certificate"
        ]
        if not attachments:
            return {}
        latest = sorted(attachments, key=lambda item: str(item.get("created_at") or item.get("updated_at") or ""))[-1]
        path = Path(str(latest.get("storage_path") or ""))
        if not path.exists() or not path.is_file():
            return {}
        current_fingerprint = file_fingerprint(path)
        cached_fingerprint = str(latest.get("tax_certificate_fingerprint") or "").strip()
        cached_tax_certificate = latest.get("tax_certificate") if isinstance(latest.get("tax_certificate"), dict) else {}
        if (
            cached_tax_certificate
            and has_tax_certificate_core_fields(cached_tax_certificate)
            and cached_fingerprint
            and cached_fingerprint == current_fingerprint
        ):
            return dict(cached_tax_certificate)
        return parse_tax_certificate_file(path).to_payload()

    def _research_nace_for_tax_certificate(self, tax_certificate: dict[str, object]) -> dict[str, object]:
        nace_code = str(tax_certificate.get("nace_code") or "").strip()
        if not nace_code:
            return {}
        if hasattr(self.store, "get_nace_research_profile"):
            cached = self.store.get_nace_research_profile(nace_code)
            if cached:
                return cached
        runtime = build_research_runtime_from_env(environ)
        if not runtime:
            return {}
        harness = ResearchHarness(
            store=self.store,
            provider=runtime.get("provider"),  # type: ignore[arg-type]
            policy=runtime.get("policy"),  # type: ignore[arg-type]
        )
        return harness.research_nace(
            nace_code=nace_code,
            activity_context=str(tax_certificate.get("activity_description") or ""),
            bypass_cache=False,
        )

    def _update_client_from_tax_certificate(
        self,
        *,
        client_id: str,
        workspace: dict[str, Any],
        tax_certificate: dict[str, object],
        nace_profile: dict[str, object],
    ) -> None:
        client = workspace.get("client") or {}
        current = dict(client.get("profile") or {})
        activity_tags = [
            str(tag).strip()
            for tag in (
                nace_profile.get("activity_tags")
                or tax_certificate.get("activity_tags")
                or current.get("activity_tags")
                or []
            )
            if str(tag).strip()
        ]
        updated = {
            **current,
            "client_id": current.get("client_id") or client_id,
            "title": tax_certificate.get("display_title") or tax_certificate.get("title") or current.get("title") or "",
            "tax_id": tax_certificate.get("tax_id") or current.get("tax_id") or "",
            "tckn": tax_certificate.get("tckn") or current.get("tckn") or "",
            "vkn": tax_certificate.get("vkn") or current.get("vkn") or "",
            "identity_type": tax_certificate.get("identity_type") or current.get("identity_type") or "",
            "tax_identifier": tax_certificate.get("tax_identifier") or current.get("tax_identifier") or current.get("tax_id") or "",
            "legal_name": tax_certificate.get("legal_name") or current.get("legal_name") or "",
            "trade_name": tax_certificate.get("trade_name") or current.get("trade_name") or "",
            "display_title": tax_certificate.get("display_title") or current.get("display_title") or "",
            "tax_office": tax_certificate.get("tax_office") or current.get("tax_office") or "",
            "activity_description": tax_certificate.get("activity_description") or current.get("activity_description") or "",
            "nace_code": tax_certificate.get("nace_code") or current.get("nace_code") or "",
            "activity_tags": activity_tags,
            "activity_profile": tax_certificate.get("activity_profile") or current.get("activity_profile") or {},
            "workplace_addresses": tax_certificate.get("workplace_addresses") or current.get("workplace_addresses") or [],
            "has_chart_accounts": bool(current.get("has_chart_accounts") or (workspace.get("chart_accounts") or {}).get("account_count")),
        }
        if nace_profile:
            updated["nace_research_profile"] = nace_profile
        onboarding = check_client_onboarding(
            ClientProfile(
                client_id=str(updated.get("client_id") or ""),
                title=str(updated.get("title") or ""),
                tax_id=str(updated.get("tax_id") or ""),
                tckn=str(updated.get("tckn") or ""),
                vkn=str(updated.get("vkn") or ""),
                identity_type=str(updated.get("identity_type") or ""),
                tax_identifier=str(updated.get("tax_identifier") or ""),
                legal_name=str(updated.get("legal_name") or ""),
                trade_name=str(updated.get("trade_name") or ""),
                display_title=str(updated.get("display_title") or updated.get("title") or ""),
                tax_office=str(updated.get("tax_office") or ""),
                activity_description=str(updated.get("activity_description") or ""),
                nace_code=str(updated.get("nace_code") or ""),
                activity_tags=tuple(activity_tags),
                workplace_addresses=tuple(updated.get("workplace_addresses") or []),
                has_chart_accounts=bool(updated.get("has_chart_accounts")),
            )
        )
        self.store.upsert_client(
            client_id=client_id,
            profile=updated,
            onboarding={"is_ready": onboarding.is_ready, "missing_fields": list(onboarding.missing_fields)},
        )

    def store_processing_jobs(self, *, client_id: str, user_id: str | None) -> dict[str, object]:
        if not client_id.strip():
            raise HTTPException(status_code=400, detail="client_id is required")
        self.require_client_access(client_id=client_id, user_id=user_id)
        return {"jobs": self.store.list_processing_jobs(client_id=client_id)}

    def document_pipeline(self, *, client_id: str, document_ref: str, user_id: str | None) -> dict[str, object]:
        normalized_client_id = client_id.strip()
        normalized_ref = document_ref.strip()
        if not normalized_client_id or not normalized_ref:
            raise HTTPException(status_code=400, detail="client_id and document_ref are required")
        self.require_client_access(client_id=normalized_client_id, user_id=user_id)
        return {
            "client_id": normalized_client_id,
            "document_ref": normalized_ref,
            "events": self.store.list_document_pipeline_events(
                client_id=normalized_client_id,
                document_ref=normalized_ref,
            ),
        }

    def original_document_file(self, *, client_id: str, document_ref: str, user_id: str | None) -> dict[str, object]:
        normalized_client_id = client_id.strip()
        normalized_ref = document_ref.strip()
        if not normalized_client_id or not normalized_ref:
            raise HTTPException(status_code=400, detail="client_id and document_ref are required")
        self.require_client_access(client_id=normalized_client_id, user_id=user_id)
        workspace = self.store.get_workspace(normalized_client_id)
        document = next(
            (
                item
                for item in workspace.get("uploaded_documents", [])
                if str(item.get("document_ref") or item.get("document_id") or item.get("original_file_name")) == normalized_ref
            ),
            None,
        )
        if not document:
            document = next(
                (
                    item
                    for item in workspace.get("onboarding_attachments", [])
                    if str(item.get("attachment_ref") or item.get("document_id") or item.get("original_file_name")) == normalized_ref
                ),
                None,
            )
        if not document:
            self.store.record_document_pipeline_event(
                client_id=normalized_client_id,
                document_ref=normalized_ref,
                step="preview_fetch_failed",
                status="error",
                message_tr="Önizleme alınamadı: belge kaydı bulunamadı.",
                debug_code="preview_document_not_found",
                details={},
            )
            raise HTTPException(status_code=404, detail="document not found")
        path = Path(str(document.get("storage_path") or ""))
        if not path.exists() or not path.is_file():
            self.store.record_document_pipeline_event(
                client_id=normalized_client_id,
                document_ref=normalized_ref,
                step="preview_fetch_failed",
                status="error",
                message_tr="Önizleme alınamadı: dosya storage'da bulunamadı.",
                debug_code="preview_file_missing",
                details={"storage_path": str(path)},
            )
            raise HTTPException(status_code=404, detail="document file not found")
        try:
            path.resolve().relative_to(self.document_storage_path.resolve())
        except ValueError as exc:
            self.store.record_document_pipeline_event(
                client_id=normalized_client_id,
                document_ref=normalized_ref,
                step="preview_fetch_failed",
                status="error",
                message_tr="Önizleme alınamadı: dosya yolu izin verilen alanın dışında.",
                debug_code="preview_path_outside_storage",
                details={"storage_path": str(path)},
            )
            raise HTTPException(status_code=403, detail="document storage path is outside allowed storage") from exc
        file_name = Path(str(document.get("original_file_name") or path.name)).name
        media_type = str(document.get("content_type") or "") or mimetypes.guess_type(file_name)[0] or "application/octet-stream"
        document_type = str(document.get("document_type") or "")
        if path.suffix.lower() == ".xml" or "xml" in media_type.lower() or document_type == "einvoice_xml":
            from app.domain.ubl_invoice_preview import render_ubl_invoice_preview_html

            return {
                "path": path,
                "file_name": file_name,
                "media_type": "text/html; charset=utf-8",
                "html": render_ubl_invoice_preview_html(path.read_text(encoding="utf-8")),
            }
        return {
            "path": path,
            "file_name": file_name,
            "media_type": media_type,
        }

