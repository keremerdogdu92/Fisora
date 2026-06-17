from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastapi import HTTPException

from app.api.phase0_review_export import workspace_document
from app.api.phase0_schemas import ReviewDecisionPayload, StoredReviewDecisionPayload
from app.domain.learning_intelligence import enrich_learning_event
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
    ) -> None:
        self.store = store
        self.record_operation_event = record_operation_event
        self.require_client_access = require_client_access

    def review_learning_event(self, payload: ReviewDecisionPayload) -> dict[str, object]:
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

    def store_review_decision(self, *, payload: StoredReviewDecisionPayload, user_id: str | None) -> dict[str, object]:
        if not payload.client_id.strip():
            raise HTTPException(status_code=400, detail="client_id is required for persistence")
        self.require_client_access(
            client_id=payload.client_id,
            user_id=user_id,
            allowed_roles=("accountant", "admin"),
        )
        workspace = self.store.get_workspace(payload.client_id)
        event = self.review_learning_event(payload.decision)
        event = enrich_learning_event(
            event,
            client_id=payload.client_id,
            decision=payload.decision.model_dump(),
            document=workspace_document(workspace, payload.decision.document_ref),
            prior_learning_events=workspace.get("learning_events") or (),
        )
        saved = self.store.save_review_decision(
            client_id=payload.client_id,
            decision=payload.decision.model_dump(),
            learning_event=event,
        )
        document_ref = payload.decision.document_ref
        if (
            payload.decision.corrected_account_code.strip()
            or payload.decision.corrected_counterparty_code.strip()
            or payload.decision.draft_lines
            or payload.decision.statement_line_no
        ):
            self.store.record_document_pipeline_event(
                client_id=payload.client_id,
                document_ref=document_ref,
                step="journal_edited",
                status="ok",
                message_tr="Müşavir muhasebe fişine müdahale etti.",
                debug_code="journal_edited",
                details={
                    "action": payload.decision.action,
                    "corrected_account_code": payload.decision.corrected_account_code,
                    "corrected_counterparty_code": payload.decision.corrected_counterparty_code,
                    "statement_line_no": payload.decision.statement_line_no,
                    "draft_line_count": len(payload.decision.draft_lines),
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
                "action": payload.decision.action,
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
                details={"action": payload.decision.action},
            )
        self.record_operation_event(
            store=self.store,
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

