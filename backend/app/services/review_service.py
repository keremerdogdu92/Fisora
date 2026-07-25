from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastapi import HTTPException

from app.api.phase0_review_export import workspace_document
from app.api.phase0_schemas import (
    JournalLinePayload,
    JournalReopenPayload,
    ReviewDecisionPayload,
    ReviewRulePreviewPayload,
    StoredReviewDecisionPayload,
)
from app.domain.chart_accounts import normalize_account_code
from app.domain.learning_intelligence import enrich_learning_event
from app.domain.review_rule_interpretation import build_review_rule_interpretation
from app.domain.review_learning import ReviewDecision, build_learning_event
from app.persistence.normalized_accounting_repository import (
    NormalizedAccountingError,
    NormalizedRevisionConflict,
)


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
        protected_corpus_service: Any | None = None,
    ) -> None:
        self.store = store
        self.record_operation_event = record_operation_event
        self.require_client_access = require_client_access
        self.rule_interpreter = rule_interpreter
        self.protected_corpus_service = protected_corpus_service

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
        if payload.learning_confirmation.strip() and payload.learning_confirmation.strip() != "none":
            event_payload["learning_confirmation"] = payload.learning_confirmation.strip()
        if payload.suppress_rule_prompt_key.strip():
            event_payload["suppress_rule_prompt_key"] = payload.suppress_rule_prompt_key.strip()
        return event_payload

    def preview_review_rule(self, *, payload: ReviewRulePreviewPayload, user_id: str | None) -> dict[str, object]:
        if not payload.client_id.strip():
            raise HTTPException(status_code=400, detail="client_id is required for rule preview")
        self.require_client_access(
            client_id=payload.client_id,
            user_id=user_id,
            allowed_roles=("accountant", "admin"),
        )
        authenticated_actor = str(user_id or "authenticated_session")
        payload = payload.model_copy(
            update={
                "decision": payload.decision.model_copy(
                    update={"reviewer": authenticated_actor}
                )
            }
        )
        workspace = self.store.get_workspace(payload.client_id)
        document = workspace_document(workspace, payload.decision.document_ref)
        decision = self._validated_review_decision(payload.decision, workspace=workspace, document=document)
        event = self._enriched_learning_event(
            client_id=payload.client_id,
            decision=decision,
            workspace=workspace,
            document=document,
        )
        interpretation = self._rule_interpretation(event=event, document=document, decision=decision)
        if interpretation is not None:
            event["rule_interpretation"] = interpretation
        return {
            "learning_event": event,
            "natural_language_rule_candidate": event.get("natural_language_rule_candidate") or {},
            "rule_interpretation": interpretation,
            "rule_prompt": event.get("rule_prompt") or {},
        }

    def store_review_decision(self, *, payload: StoredReviewDecisionPayload, user_id: str | None) -> dict[str, object]:
        if not payload.client_id.strip():
            raise HTTPException(status_code=400, detail="client_id is required for persistence")
        self.require_client_access(
            client_id=payload.client_id,
            user_id=user_id,
            allowed_roles=("accountant", "admin"),
        )
        if payload.decision.action in {
            "approve",
            "approve_with_changes",
            "suggest_for_similar",
        }:
            holds_reader = getattr(
                self.store,
                "active_document_safety_holds",
                None,
            )
            holds = (
                holds_reader(
                    client_id=payload.client_id,
                    document_refs=[payload.decision.document_ref],
                )
                if callable(holds_reader)
                else []
            )
            if holds:
                raise HTTPException(
                    status_code=409,
                    detail={
                        "reason": "qnb_external_status_hold",
                        "document_ref": payload.decision.document_ref,
                        "hold_codes": sorted(
                            {
                                str(hold.get("hold_code") or "")
                                for hold in holds
                                if str(hold.get("hold_code") or "")
                            }
                        ),
                    },
                )
        workspace = self.store.get_workspace(payload.client_id)
        document = workspace_document(workspace, payload.decision.document_ref)
        decision = self._validated_review_decision(payload.decision, workspace=workspace, document=document)
        event = self._enriched_learning_event(
            client_id=payload.client_id,
            decision=decision,
            workspace=workspace,
            document=document,
        )
        rule_interpretation = self._rule_interpretation(event=event, document=document, decision=decision)
        if rule_interpretation is not None:
            event["rule_interpretation"] = rule_interpretation
        try:
            saved = self.store.save_review_decision(
                client_id=payload.client_id,
                decision=decision.model_dump(),
                learning_event=event,
            )
        except NormalizedRevisionConflict as exc:
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "journal_revision_conflict",
                    "expected_revision": exc.expected,
                    "actual_revision": exc.actual,
                },
            ) from exc
        except NormalizedAccountingError as exc:
            raise HTTPException(status_code=409, detail={"code": "normalized_journal_error", "message": str(exc)}) from exc
        if self.protected_corpus_service is not None:
            try:
                self.protected_corpus_service.capture_reference_if_enrolled(
                    client_id=payload.client_id,
                    document_ref=decision.document_ref,
                    saved_review=saved,
                    learning_event=event,
                    actor=decision.reviewer,
                )
            except Exception as exc:
                self.record_operation_event(
                    store=self.store,
                    client_id=payload.client_id,
                    event_type="protected_reference_capture_failed",
                    status="error",
                    message="Korumali musavir referansi kaydedilemedi; ana review kaydi korundu.",
                    metadata={
                        "document_ref": decision.document_ref,
                        "error": str(exc),
                    },
                )
        self._record_learning_pipeline_events(
            client_id=payload.client_id,
            document_ref=decision.document_ref,
            event=event,
            interpretation=rule_interpretation,
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

    def reopen_journal(self, *, payload: JournalReopenPayload, user_id: str | None) -> dict[str, object]:
        self.require_client_access(
            client_id=payload.client_id,
            user_id=user_id,
            allowed_roles=("accountant", "admin"),
        )
        authenticated_actor = str(user_id or "authenticated_session")
        try:
            return self.store.reopen_journal(
                client_id=payload.client_id,
                document_ref=payload.document_ref,
                expected_revision=payload.expected_revision,
                reviewer=authenticated_actor,
                reason=payload.reason,
            )
        except NormalizedRevisionConflict as exc:
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "journal_revision_conflict",
                    "expected_revision": exc.expected,
                    "actual_revision": exc.actual,
                },
            ) from exc
        except (NormalizedAccountingError, RuntimeError) as exc:
            raise HTTPException(status_code=409, detail={"code": "journal_reopen_failed", "message": str(exc)}) from exc

    def _record_learning_pipeline_events(
        self,
        *,
        client_id: str,
        document_ref: str,
        event: dict[str, object],
        interpretation: dict[str, object] | None,
    ) -> None:
        if not hasattr(self.store, "record_document_pipeline_event"):
            return
        candidate = event.get("natural_language_rule_candidate")
        if isinstance(candidate, dict) and candidate:
            self.store.record_document_pipeline_event(
                client_id=client_id,
                document_ref=document_ref,
                step="learning_candidate_built",
                status="ok",
                message_tr="Musavir karar notundan kural adayi olusturuldu.",
                debug_code="learning_candidate_built",
                details={
                    "scope": str(candidate.get("scope") or event.get("scope") or ""),
                    "action": str(event.get("action") or ""),
                    "accounting_intent": str(event.get("accounting_intent") or candidate.get("semantic_accounting_intent") or ""),
                    "matched_terms": list(event.get("normalized_terms") or []),
                    "match_score": int(event.get("accounting_intent_confidence") or 0),
                    "suggested_account_code": str(candidate.get("suggested_account_code") or ""),
                    "suggested_counterparty_code": str(event.get("corrected_counterparty_code") or ""),
                    "reason_codes": ["natural_language_rule_candidate"],
                },
            )
        if isinstance(interpretation, dict) and interpretation:
            self.store.record_document_pipeline_event(
                client_id=client_id,
                document_ref=document_ref,
                step="learning_rule_interpreted",
                status="ok" if str(interpretation.get("status") or "") == "ready" else "warning",
                message_tr="Fisora karar notunu anlasilir kurala cevirdi.",
                debug_code="learning_rule_interpreted",
                details={
                    "scope": str((candidate or {}).get("scope") or event.get("scope") or "") if isinstance(candidate, dict) else str(event.get("scope") or ""),
                    "action": str(event.get("action") or ""),
                    "accounting_intent": str(event.get("accounting_intent") or ""),
                    "matched_terms": list(event.get("normalized_terms") or []),
                    "match_score": int(interpretation.get("confidence") or event.get("accounting_intent_confidence") or 0),
                    "suggested_account_code": str((candidate or {}).get("suggested_account_code") or event.get("corrected_account_code") or "") if isinstance(candidate, dict) else str(event.get("corrected_account_code") or ""),
                    "suggested_counterparty_code": str(event.get("corrected_counterparty_code") or ""),
                    "understood_rule_tr": str(interpretation.get("summary_tr") or ""),
                    "trigger_tr": str(interpretation.get("trigger_tr") or ""),
                    "applied_effect_tr": str(interpretation.get("action_tr") or ""),
                    "guardrail_tr": str(interpretation.get("guardrail_tr") or ""),
                    "reason_codes": [str(item) for item in interpretation.get("reason_codes") or [] if str(item).strip()],
                },
            )

    def _enriched_learning_event(
        self,
        *,
        client_id: str,
        decision: ReviewDecisionPayload,
        workspace: dict[str, object],
        document: dict[str, object] | None,
    ) -> dict[str, object]:
        event = self.review_learning_event(decision)
        return enrich_learning_event(
            event,
            client_id=client_id,
            decision=decision.model_dump(),
            document=document,
            client_profile=(workspace.get("client") or {}).get("profile") or {},
            prior_learning_events=workspace.get("learning_events") or (),
        )

    def _rule_interpretation(
        self,
        *,
        event: dict[str, object],
        document: dict[str, object] | None,
        decision: ReviewDecisionPayload,
    ) -> dict[str, object] | None:
        confirmed = _normalized_rule_interpretation(decision.confirmed_rule_interpretation)
        if confirmed:
            confirmed["source"] = "accountant_confirmed"
            confirmed["provider"] = "accountant_review_modal"
            return confirmed
        return build_review_rule_interpretation(
            event=event,
            document=document,
            provider=self.rule_interpreter,
        )

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


def _normalized_rule_interpretation(value: dict[str, object] | None) -> dict[str, object]:
    if not isinstance(value, dict) or not value:
        return {}

    def text(*keys: str) -> str:
        for key in keys:
            candidate = value.get(key)
            if candidate is not None and str(candidate).strip():
                return str(candidate).strip()
        return ""

    status = text("status") or "needs_clarification"
    if status not in {"ready", "needs_clarification", "not_available"}:
        status = "needs_clarification"
    try:
        confidence = int(value.get("confidence") or 0)
    except (TypeError, ValueError):
        confidence = 0
    reason_codes = value.get("reason_codes")
    if not isinstance(reason_codes, list):
        reason_codes = value.get("reasonCodes")
    return {
        "status": status,
        "summary_tr": text("summary_tr", "summaryTr"),
        "trigger_tr": text("trigger_tr", "triggerTr"),
        "action_tr": text("action_tr", "actionTr"),
        "guardrail_tr": text("guardrail_tr", "guardrailTr") or "Ilk uygulamalarda musavir kontrolu istenir.",
        "confidence": min(max(confidence, 0), 100),
        "reason_codes": [str(item) for item in reason_codes or [] if str(item).strip()],
    }
