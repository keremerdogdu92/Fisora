from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict
from pathlib import Path
from typing import Any

from fastapi import HTTPException

from app.api.phase0_mappers import chart_account_from_payload, chart_account_payloads, client_profile_from_payload
from app.api.phase0_schemas import ChartAccountsStorePayload, ClientDocumentsDeletePayload, ClientOnboardingPackagePayload, ClientProfilePayload
from app.domain.business_relevance import check_client_onboarding
from app.domain.chart_accounts import parse_chart_accounts
from app.domain.document_uploads import store_document_content
from app.domain.nace_research import NaceResearcher, resolve_nace_research_profile


OperationRecorder = Callable[..., dict[str, object]]
AccessChecker = Callable[..., dict[str, object]]
UserIdResolver = Callable[[str | None, str | None, str | None], str]


class WorkspaceService:
    def __init__(
        self,
        *,
        store: Any,
        record_operation_event: OperationRecorder,
        require_client_access: AccessChecker,
        request_user_id: UserIdResolver,
        document_storage_path: Path | None = None,
        chart_account_parser: Callable[[Path], object] = parse_chart_accounts,
        nace_researcher: NaceResearcher | None = None,
    ) -> None:
        self.store = store
        self.document_storage_path = document_storage_path or Path("exports/documents")
        self.record_operation_event = record_operation_event
        self.require_client_access = require_client_access
        self.request_user_id = request_user_id
        self.chart_account_parser = chart_account_parser
        self.nace_researcher = nace_researcher

    def onboarding_check(self, payload: ClientProfilePayload) -> dict[str, object]:
        check = check_client_onboarding(client_profile_from_payload(payload))
        return {"is_ready": check.is_ready, "missing_fields": list(check.missing_fields)}

    def _with_nace_research(self, payload: ClientProfilePayload) -> ClientProfilePayload:
        if not payload.nace_code.strip():
            return payload
        try:
            profile = resolve_nace_research_profile(
                store=self.store,
                nace_code=payload.nace_code,
                researcher=self.nace_researcher,
            )
        except Exception:
            return payload
        activity_tags = payload.activity_tags or [
            str(tag).strip() for tag in profile.get("activity_tags") or [] if str(tag).strip()
        ]
        data = payload.model_dump()
        data["activity_tags"] = activity_tags
        data["nace_research_profile"] = profile
        return ClientProfilePayload(**data)

    def store_client(self, payload: ClientProfilePayload) -> dict[str, object]:
        if not payload.client_id.strip():
            raise HTTPException(status_code=400, detail="client_id is required for persistence")
        enriched_payload = self._with_nace_research(payload)
        return self.store.upsert_client(
            client_id=enriched_payload.client_id,
            profile=enriched_payload.model_dump(),
            onboarding=self.onboarding_check(enriched_payload),
        )

    def store_clients(
        self,
        *,
        x_fisora_user_id: str | None,
        x_fisora_session: str | None,
        fisora_session: str | None,
    ) -> dict[str, object]:
        clients = self.store.list_clients()
        user_id = self.request_user_id(x_fisora_user_id, x_fisora_session, fisora_session)
        if user_id:
            clients = [
                client
                for client in clients
                if self.store.verify_portal_access(client_id=client_id_from_record(client), user_id=user_id).get("allowed")
            ]
        return {
            "clients": clients,
            "auth": {
                "mode": "session_or_header" if user_id else "disabled",
                "user_id": user_id,
            },
        }

    def store_chart_accounts(self, payload: ChartAccountsStorePayload) -> dict[str, object]:
        if not payload.client_id.strip():
            raise HTTPException(status_code=400, detail="client_id is required for persistence")
        return self.store.replace_chart_accounts(
            client_id=payload.client_id,
            accounts=chart_account_payloads(payload.accounts),
        )

    def store_chart_accounts_upload(
        self,
        *,
        client_id: str,
        original_name: str,
        file_path: Path,
        x_fisora_user_id: str | None,
        x_fisora_session: str | None,
        fisora_session: str | None,
    ) -> dict[str, object]:
        normalized_client_id = client_id.strip()
        if not normalized_client_id:
            raise HTTPException(status_code=400, detail="client_id is required for chart account upload")
        self.require_client_access(
            client_id=normalized_client_id,
            user_id=self.request_user_id(x_fisora_user_id, x_fisora_session, fisora_session),
            allowed_roles=("accountant", "admin"),
        )
        suffix = Path(original_name).suffix.lower()
        if suffix not in {".csv", ".xlsx", ".xlsm"}:
            raise HTTPException(status_code=400, detail=f"Unsupported chart account format: {suffix or 'unknown'}")
        try:
            parsed_accounts = self.chart_account_parser(file_path)
        except (RuntimeError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        accounts = [asdict(account) for account in parsed_accounts]
        stored = self.store.replace_chart_accounts(client_id=normalized_client_id, accounts=accounts)
        raw_document = store_document_content(
            base_dir=self.document_storage_path,
            client_id=normalized_client_id,
            file_name=original_name,
            document_type="special_document",
            intake_category="special_document",
            uploaded_by=self.request_user_id(x_fisora_user_id, x_fisora_session, fisora_session) or "mali-musavir",
            content=file_path.read_bytes(),
            retention_days=365,
        )
        raw_payload = asdict(raw_document)
        raw_payload.update(
            {
                "attachment_ref": raw_payload.get("document_id", ""),
                "attachment_type": "chart_accounts",
                "parsed_account_count": len(accounts),
            }
        )
        attachment = self.store.save_onboarding_attachment(client_id=normalized_client_id, attachment=raw_payload)
        self.record_operation_event(
            store=self.store,
            client_id=normalized_client_id,
            event_type="chart_accounts_uploaded",
            status="ok" if accounts else "warning",
            message="Hesap plani import edildi.",
            metadata={
                "file_name": original_name,
                "account_count": len(accounts),
                "raw_attachment_ref": attachment["attachment_ref"],
            },
        )
        return {**stored, "file_name": original_name, "raw_attachment": attachment}

    def parse_chart_accounts_upload(self, *, original_name: str, file_path: Path) -> dict[str, object]:
        suffix = Path(original_name).suffix.lower()
        if suffix not in {".csv", ".xlsx", ".xlsm"}:
            raise HTTPException(status_code=400, detail=f"Unsupported chart account format: {suffix or 'unknown'}")
        try:
            parsed_accounts = self.chart_account_parser(file_path)
        except (RuntimeError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        accounts = [asdict(account) for account in parsed_accounts]
        return {
            "file_name": original_name,
            "account_count": len(accounts),
            "accounts": accounts,
        }

    def store_client_onboarding_package(
        self,
        payload: ClientOnboardingPackagePayload,
        *,
        x_fisora_user_id: str | None = None,
        x_fisora_session: str | None = None,
        fisora_session: str | None = None,
    ) -> dict[str, object]:
        if not payload.client.client_id.strip():
            raise HTTPException(status_code=400, detail="client_id is required for onboarding package")
        enriched_client_payload = self._with_nace_research(payload.client)
        client = self.store.upsert_client(
            client_id=enriched_client_payload.client_id,
            profile=enriched_client_payload.model_dump(),
            onboarding=self.onboarding_check(enriched_client_payload),
        )
        chart_accounts = None
        if payload.chart_accounts:
            chart_accounts = self.store.replace_chart_accounts(
                client_id=enriched_client_payload.client_id,
                accounts=[asdict(chart_account_from_payload(account)) for account in payload.chart_accounts],
            )
        portal_users = []
        for user in payload.portal_users:
            portal_users.append(
                self.store.upsert_portal_user(
                    user_id=user.user_id,
                    display_name=user.display_name,
                    role=user.role,
                    allowed_client_ids=user.allowed_client_ids or [enriched_client_payload.client_id],
                )
            )
        actor_user = self.request_user_id(x_fisora_user_id, x_fisora_session, fisora_session)
        actor_grant = self._grant_actor_access_to_new_client(
            actor_user_id=actor_user,
            client_id=enriched_client_payload.client_id,
        )
        if actor_grant:
            portal_users.append(actor_grant)
        return {
            "client": client,
            "chart_accounts": chart_accounts,
            "portal_users": portal_users,
            "workspace": self.store.get_workspace(enriched_client_payload.client_id),
        }

    def _grant_actor_access_to_new_client(self, *, actor_user_id: str, client_id: str) -> dict[str, object] | None:
        actor_user_id = actor_user_id.strip()
        if not actor_user_id:
            return None
        access = self.store.verify_portal_access(client_id=client_id, user_id=actor_user_id)
        if access.get("allowed"):
            return None
        if access.get("role") not in {"accountant", "admin"}:
            return None
        existing = self.store.get_portal_user(actor_user_id) if hasattr(self.store, "get_portal_user") else None
        if not existing:
            return None
        allowed_client_ids = list(dict.fromkeys([*(existing.get("allowed_client_ids") or []), client_id]))
        return self.store.upsert_portal_user(
            user_id=actor_user_id,
            display_name=str(existing.get("display_name") or actor_user_id),
            role=str(existing.get("role") or access.get("role") or "accountant"),
            allowed_client_ids=allowed_client_ids,
        )

    def store_workspace(
        self,
        *,
        client_id: str,
        view: str = "full",
        x_fisora_user_id: str | None,
        x_fisora_session: str | None,
        fisora_session: str | None,
    ) -> dict[str, object]:
        if not client_id.strip():
            raise HTTPException(status_code=400, detail="client_id is required")
        self.require_client_access(
            client_id=client_id,
            user_id=self.request_user_id(x_fisora_user_id, x_fisora_session, fisora_session),
        )
        workspace = self.store.get_workspace(client_id)
        if view.strip().lower() in {"summary", "compact"}:
            return compact_workspace_payload(workspace)
        return workspace

    def delete_client_documents(
        self,
        payload: ClientDocumentsDeletePayload,
        *,
        x_fisora_user_id: str | None,
        x_fisora_session: str | None,
        fisora_session: str | None,
    ) -> dict[str, object]:
        if not payload.confirmed:
            raise HTTPException(status_code=400, detail={"allowed": False, "reason": "confirmation_required"})
        normalized_client_id = payload.client_id.strip()
        if not normalized_client_id:
            raise HTTPException(status_code=400, detail="client_id is required")
        document_refs = [ref.strip() for ref in payload.document_refs if ref.strip()]
        if not document_refs:
            raise HTTPException(status_code=400, detail="document_refs is required")
        self.require_client_access(
            client_id=normalized_client_id,
            user_id=self.request_user_id(x_fisora_user_id, x_fisora_session, fisora_session),
            allowed_roles=("accountant", "admin"),
        )
        try:
            return self.store.delete_client_documents(
                client_id=normalized_client_id,
                document_refs=document_refs,
                delete_files=payload.delete_files,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc


def client_id_from_record(record: dict[str, object]) -> str:
    profile = record.get("profile") if isinstance(record, dict) else {}
    if isinstance(profile, dict) and profile.get("client_id"):
        return str(profile["client_id"])
    return str(record.get("client_id") or record.get("id") or "")


def compact_workspace_payload(workspace: dict[str, object]) -> dict[str, object]:
    compact = dict(workspace)
    compact["chart_accounts"] = compact_chart_accounts(workspace.get("chart_accounts"))
    compact["documents"] = [compact_document(document) for document in safe_list(workspace.get("documents"))]
    compact["uploaded_documents"] = [compact_uploaded_document(document) for document in safe_list(workspace.get("uploaded_documents"))]
    compact["processing_jobs"] = [compact_processing_job(job) for job in safe_list(workspace.get("processing_jobs"))]
    compact["review_decisions"] = [compact_review_decision(decision) for decision in safe_list(workspace.get("review_decisions"))]
    compact["learning_events"] = [compact_learning_event(event) for event in safe_list(workspace.get("learning_events"))]
    compact["document_pipeline_events"] = []
    compact["operation_events"] = list(reversed(safe_list(workspace.get("operation_events"))))[:20]
    return compact


def compact_chart_accounts(value: object) -> dict[str, object]:
    source = value if isinstance(value, dict) else {}
    accounts = safe_list(source.get("accounts"))
    return {
        "account_count": source.get("account_count", len(accounts)),
        "accounts": [],
    }


def compact_document(document: object) -> dict[str, object]:
    if not isinstance(document, dict):
        return {}
    allowed_document_keys = {
        "client_id",
        "document_ref",
        "document_type",
        "export_status",
        "review_reason_codes",
        "created_at",
        "updated_at",
    }
    compact = {key: value for key, value in document.items() if key in allowed_document_keys}
    compact["result"] = compact_result(document.get("result"))
    return compact


def compact_result(result: object) -> dict[str, object]:
    if not isinstance(result, dict):
        return {}
    allowed_result_keys = {
        "accountant_action_hint",
        "accountant_explanation_tr",
        "accountant_summary",
        "accounting_direction",
        "accounting_intent",
        "accounting_intent_confidence",
        "account_candidates",
        "ai_account_reason",
        "ai_classification_provider",
        "ai_classification_reason",
        "ai_explanation_tr",
        "ai_gate_reason",
        "ai_product_identity",
        "ai_quality_scorecard",
        "ai_research_query",
        "ai_research_requested",
        "ai_resolution_status",
        "ai_retry_reason",
        "ai_risk_flags",
        "ai_suggested_account_code",
        "ai_suggested_counterparty_code",
        "automation_eligibility",
        "business_relevance_account_treatment",
        "business_relevance_reason",
        "business_relevance_relation",
        "business_relevance_requires_review",
        "canonical_extraction_ai_used",
        "canonical_line_count",
        "canonical_validation_reasons",
        "canonical_validation_status",
        "client_activity_tags",
        "client_nace_code",
        "content_type",
        "counterparty_creation_suggestion",
        "counterparty_identity_key",
        "counterparty_match_code",
        "counterparty_match_confidence",
        "counterparty_match_reason",
        "counterparty_tax_id",
        "counterparty_title",
        "decision_narrative",
        "deterministic_checks",
        "direction_conflict",
        "document_validation_status",
        "draft_confidence",
        "draft_decision_source",
        "draft_lines",
        "draft_status",
        "export_gate_reason",
        "export_status",
        "file_name",
        "intake_category",
        "invoice_type",
        "issue_date",
        "learning_rule_reason",
        "learning_rule_scope",
        "learning_rule_source_summary",
        "learning_audit",
        "payable_total",
        "period",
        "primary_suggestion",
        "product_category",
        "product_line_hint",
        "provider_hint",
        "review_blockers",
        "review_reason_codes",
        "risk_flags",
        "rule_interpretation",
        "rule_prompt",
        "selected_customer_account",
        "selected_expense_account",
        "selected_purchase_vat_account",
        "selected_revenue_account",
        "selected_sales_vat_account",
        "selected_supplier_account",
        "selected_vat_account",
        "statement_ai_suggestions",
        "statement_ai_summary",
        "statement_entries",
        "statement_lines",
        "static_fallback_account",
        "static_fallback_suppressed",
        "suggested_counterparty_account",
        "vat_rates",
    }
    return {key: value for key, value in result.items() if key in allowed_result_keys}


def compact_uploaded_document(document: object) -> dict[str, object]:
    if not isinstance(document, dict):
        return {}
    allowed_keys = {
        "client_id",
        "content_type",
        "created_at",
        "document_ref",
        "document_type",
        "intake_category",
        "original_file_name",
        "period",
        "status",
        "stored_file_name",
        "updated_at",
        "uploaded_by",
    }
    return {key: value for key, value in document.items() if key in allowed_keys}


def compact_processing_job(job: object) -> dict[str, object]:
    if not isinstance(job, dict):
        return {}
    allowed_keys = {
        "client_id",
        "created_at",
        "document_ref",
        "document_type",
        "intake_category",
        "parser_kind",
        "period",
        "status",
        "updated_at",
    }
    return {key: value for key, value in job.items() if key in allowed_keys}


def compact_review_decision(decision: object) -> dict[str, object]:
    if not isinstance(decision, dict):
        return {}
    allowed_keys = {
        "action",
        "category",
        "client_id",
        "created_at",
        "document_ref",
        "reviewer",
        "updated_at",
    }
    return {key: value for key, value in decision.items() if key in allowed_keys}


def compact_learning_event(event: object) -> dict[str, object]:
    if not isinstance(event, dict):
        return {}
    allowed_keys = {
        "accountant_note",
        "action",
        "category",
        "client_id",
        "created_at",
        "document_ref",
        "learning_key",
        "natural_language_rule_candidate",
        "rule_instruction",
        "rule_interpretation",
        "updated_at",
    }
    return {key: value for key, value in event.items() if key in allowed_keys}


def safe_list(value: object) -> list[object]:
    return value if isinstance(value, list) else []

