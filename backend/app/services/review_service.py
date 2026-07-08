from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastapi import HTTPException

from app.api.phase0_review_export import workspace_document
from app.api.phase0_schemas import JournalLinePayload, ReviewDecisionPayload, StoredReviewDecisionPayload
from app.domain.chart_accounts import normalize_account_code
from app.domain.learning_intelligence import enrich_learning_event
from app.domain.review_rule_interpretation import build_review_rule_interpretation
from app.domain.review_learning import ReviewDecision, build_learning_event


OperationRecorder = Callable[..., dict[str, object]]
AccessChecker = Callable[..., dict[str, object]]


class ReviewService:
    def __init__(
        self,
        *,
        store: Any,
        record_operation_event: OperationRecorder,
        require_client_access: AccessChecker,
        rule_interpreter: Any | None = None,
    ) -> None:
        self.store = store
        self.record_operation_event = record_operation_event
        self.require_client_access = require_client_access
        self.rule_interpreter = rule_interpreter

    def review_learning_event(self, payload: ReviewDecisionPayload) -> dict[str, object]:
        decision = ReviewDecision(
            document_ref=payload.document_ref,
            action=payload.action,
            reviewer=payload.reviewer,
            corrected_account_code=payload.corrected_account_code,
            corrected_counterparty_code=payload.corrected_counterparty_code,
            category=payload.category,
            reason=payload.reason,
            accountant_note=payload.normalized_accountant_note,
            rule_instruction=payload.normalized_rule_instruction,
            apply_to_similar=payload.apply_to_similar,
            statement_line_no=payload.statement_line_no,
        )
        event = build_learning_event(
            decision,
            prior_consistent_approval_count=payload.prior_consistent_approval_count,
        )
        event_payload = {
            "document_ref": event.document_ref,
            "scope": event.scope,
            "action": event.action,
            "category": event.category,
            "corrected_account_code": event.corrected_account_code,
            "corrected_counterparty_code": event.corrected_counterparty_code,
            "reason": event.reason,
            "accountant_note": event.accountant_note,
            "rule_instruction": event.rule_instruction,
            "automation_candidate": event.automation_candidate,
            "statement_line_no": event.statement_line_no,
        }
        if payload.vat_split_review:
            event_payload["vat_split_review"] = payload.vat_split_review
        return event_payload

    def store_review_decision(self, *, payload: StoredReviewDecisionPayload, user_id: str | None) -> dict[str, object]:
        if not payload.client_id.strip():
            raise HTTPException(status_code=400, detail="client_id is required for persistence")
        self.require_client_access(
            client_id=payload.client_id,
            user_id=user_id,
            allowed_roles=("accountant", "admin"),
        )
        workspace = self.store.get_workspace(payload.client_id)
        document = workspace_document(workspace, payload.decision.document_ref)
        decision = self._validated_review_decision(payload.decision, workspace=workspace, document=document)
        event = self.review_learning_event(decision)
        event = enrich_learning_event(
            event,
            client_id=payload.client_id,
            decision=decision.model_dump(),
            document=document,
            client_profile=(workspace.get("client") or {}).get("profile") or {},
            prior_learning_events=workspace.get("learning_events") or (),
        )
        rule_interpretation = build_review_rule_interpretation(
            event=event,
            document=document,
            provider=self.rule_interpreter,
        )
        if rule_interpretation is not None:
            event["rule_interpretation"] = rule_interpretation
        saved = self.store.save_review_decision(
            client_id=payload.client_id,
            decision=decision.model_dump(),
            learning_event=event,
        )
        document_ref = decision.document_ref
        if (
            decision.corrected_account_code.strip()
            or decision.corrected_counterparty_code.strip()
            or decision.draft_lines
            or decision.statement_line_no
        ):
            self.store.record_document_pipeline_event(
                client_id=payload.client_id,
                document_ref=document_ref,
                step="journal_edited",
                status="ok",
                message_tr="Müşavir muhasebe fişine müdahale etti.",
                debug_code="journal_edited",
                details={
                    "action": decision.action,
                    "corrected_account_code": decision.corrected_account_code,
                    "corrected_counterparty_code": decision.corrected_counterparty_code,
                    "statement_line_no": decision.statement_line_no,
                    "draft_line_count": len(decision.draft_lines),
                },
            )
        if decision.vat_split_review:
            self.store.record_document_pipeline_event(
                client_id=payload.client_id,
                document_ref=document_ref,
                step="vat_split_review_saved",
                status="ok",
                message_tr="KDV ayrimi musavir tarafindan kaydedildi.",
                debug_code="vat_split_review_saved",
                details={
                    "status": str(decision.vat_split_review.get("status") or ""),
                    "similarity_key": str(decision.vat_split_review.get("similarity_key") or ""),
                    "line_count": len(decision.vat_split_review.get("lines") or []),
                },
            )
        corrected_document = saved.get("corrected_document") if isinstance(saved, dict) else None
        corrected_result = corrected_document.get("result") if isinstance(corrected_document, dict) else {}
        self.store.record_document_pipeline_event(
            client_id=payload.client_id,
            document_ref=document_ref,
            step="journal_saved",
            status="ok",
            message_tr="Muhasebe fişi kaydedildi.",
            debug_code="journal_saved",
            details={
                "action": decision.action,
                "export_status": str(corrected_result.get("export_status") or ""),
            },
        )
        if isinstance(corrected_result, dict) and corrected_result.get("export_status") == "export_ready":
            self.store.record_document_pipeline_event(
                client_id=payload.client_id,
                document_ref=document_ref,
                step="export_ready",
                status="ok",
                message_tr="Muhasebe fişi kaydedildi; exporta gönderilebilir durumda.",
                debug_code="export_ready",
                details={"action": decision.action},
            )
        self.record_operation_event(
            store=self.store,
            client_id=payload.client_id,
            event_type="review_decision_saved",
            status="ok",
            message="Musavir review karari ve learning event kaydedildi.",
            metadata={
                "document_ref": decision.document_ref,
                "action": decision.action,
                "reviewer": decision.reviewer,
                "automation_candidate": event.get("automation_candidate", False),
            },
        )
        return saved

    def _validated_review_decision(
        self,
        decision: ReviewDecisionPayload,
        *,
        workspace: dict[str, object],
        document: dict[str, object] | None,
    ) -> ReviewDecisionPayload:
        if not decision.draft_lines:
            return decision
        chart_accounts = workspace.get("chart_accounts") or {}
        accounts = chart_accounts.get("accounts") if isinstance(chart_accounts, dict) else None
        if not isinstance(accounts, list) or not accounts:
            return decision
        account_names, detail_codes = _chart_account_indexes(accounts)
        allowed_new_counterparties = _allowed_new_counterparty_codes(document)
        normalized_lines: list[JournalLinePayload] = []
        invalid_codes: list[str] = []
        for line in decision.draft_lines:
            code = normalize_account_code(line.account_code)
            if code in detail_codes:
                normalized_lines.append(
                    JournalLinePayload(
                        account_code=code,
                        description=account_names[code],
                        debit=line.debit,
                        credit=line.credit,
                        document_ref=line.document_ref,
                    )
                )
                continue
            if code in allowed_new_counterparties:
                normalized_lines.append(
                    JournalLinePayload(
                        account_code=code,
                        description=line.description,
                        debit=line.debit,
                        credit=line.credit,
                        document_ref=line.document_ref,
                    )
                )
                continue
            invalid_codes.append(code or line.account_code)
        if invalid_codes:
            raise HTTPException(
                status_code=400,
                detail=f"Hesap plani disinda veya secilemez hesap kodu: {', '.join(invalid_codes)}",
            )
        return decision.model_copy(update={"draft_lines": normalized_lines})


def _chart_account_indexes(accounts: list[object]) -> tuple[dict[str, str], set[str]]:
    account_names: dict[str, str] = {}
    detail_codes: set[str] = set()
    for account in accounts:
        if not isinstance(account, dict):
            continue
        code = normalize_account_code(
            str(account.get("normalized_account_code") or account.get("code") or account.get("raw_account_code") or "")
        )
        name = str(account.get("account_name") or account.get("name") or "").strip()
        if not code or not name:
            continue
        account_names[code] = name
        if bool(account.get("is_detail_account")):
            detail_codes.add(code)
    return account_names, detail_codes


def _allowed_new_counterparty_codes(document: dict[str, object] | None) -> set[str]:
    if not isinstance(document, dict):
        return set()
    result = document.get("result") or {}
    if not isinstance(result, dict):
        return set()
    fields = (
        "suggested_counterparty_account",
        "selected_supplier_account",
        "selected_customer_account",
        "selected_counterparty_account",
        "ai_suggested_counterparty_code",
    )
    allowed: set[str] = set()
    for field_name in fields:
        code = normalize_account_code(str(result.get(field_name) or ""))
        if code.startswith(("120", "320")):
            allowed.add(code)
    return allowed
