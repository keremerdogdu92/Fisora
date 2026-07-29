from __future__ import annotations

import hashlib
from pathlib import Path
import shutil
from typing import Any
from uuid import uuid4

from app.persistence.normalized_accounting_repository import build_line_allocation_plan


class ProtectedCorpusError(RuntimeError):
    pass


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _is_within(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


class ProtectedCorpusService:
    def __init__(
        self,
        *,
        store: Any,
        protected_root: Path | str,
        document_root: Path | str,
        export_root: Path | str,
    ) -> None:
        self.store = store
        self.protected_root = Path(protected_root).resolve()
        self.document_root = Path(document_root).resolve()
        self.export_root = Path(export_root).resolve()
        if (
            _is_within(self.protected_root, self.document_root)
            or _is_within(self.document_root, self.protected_root)
            or _is_within(self.protected_root, self.export_root)
            or _is_within(self.export_root, self.protected_root)
        ):
            raise ProtectedCorpusError("protected_root_overlaps_reset_root")

    def create_corpus(
        self,
        *,
        corpus_key: str,
        version: int,
        target_purchase_count: int = 35,
        target_sales_count: int = 15,
        actor: str,
    ) -> dict[str, Any]:
        if not corpus_key.strip() or version < 1:
            raise ProtectedCorpusError("invalid_corpus_identity")
        if target_purchase_count < 0 or target_sales_count < 0:
            raise ProtectedCorpusError("invalid_corpus_targets")
        try:
            return self.store.create_protected_corpus(
                corpus_key=corpus_key.strip(),
                version=version,
                target_purchase_count=target_purchase_count,
                target_sales_count=target_sales_count,
                created_by=actor,
            )
        except ValueError as exc:
            raise ProtectedCorpusError(str(exc)) from exc

    def enroll_document(
        self,
        *,
        corpus_id: str,
        client_id: str,
        document_ref: str,
        direction: str,
        actor: str,
    ) -> dict[str, Any]:
        if direction not in {"purchase", "sale"}:
            raise ProtectedCorpusError("invalid_corpus_direction")
        corpus = self.store.get_protected_corpus(corpus_id)
        if not corpus:
            raise ProtectedCorpusError("corpus_not_found")
        if corpus.get("status") != "draft":
            raise ProtectedCorpusError("corpus_frozen")
        workspace = self.store.get_workspace(client_id)
        document = next(
            (
                row
                for row in workspace.get("uploaded_documents") or []
                if str(row.get("document_ref") or row.get("document_id") or "") == document_ref
            ),
            None,
        )
        if not document:
            raise ProtectedCorpusError("source_document_not_found")
        processed_document = next(
            (
                row
                for row in workspace.get("documents") or []
                if str(row.get("document_ref") or row.get("document_id") or "") == document_ref
            ),
            {},
        )
        processed_result = processed_document.get("result") if isinstance(processed_document, dict) else {}
        if not isinstance(processed_result, dict):
            processed_result = {}
        evidence_direction = str(
            processed_result.get("accounting_direction") or document.get("accounting_direction") or ""
        ).strip()
        if evidence_direction == "sales":
            evidence_direction = "sale"
        if evidence_direction not in {"purchase", "sale"}:
            raise ProtectedCorpusError("direction_evidence_missing")
        if direction != evidence_direction:
            raise ProtectedCorpusError("direction_evidence_mismatch")
        source_path = Path(str(document.get("storage_path") or "")).resolve()
        if not source_path.is_file() or not _is_within(source_path, self.document_root):
            raise ProtectedCorpusError("source_file_unavailable")
        stored_sha256 = str(document.get("sha256") or "").lower()
        actual_sha256 = _sha256_file(source_path)
        if len(stored_sha256) != 64 or actual_sha256 != stored_sha256:
            raise ProtectedCorpusError("source_hash_mismatch")

        suffix = source_path.suffix.lower() or ".bin"
        target = self.protected_root / corpus_id / f"{actual_sha256}{suffix}"
        target.parent.mkdir(parents=True, exist_ok=True)
        existed = target.exists()
        temporary = target.with_name(f".{target.name}.{uuid4().hex}.tmp")
        if not existed:
            try:
                shutil.copyfile(source_path, temporary)
                if _sha256_file(temporary) != actual_sha256:
                    raise ProtectedCorpusError("source_hash_mismatch")
                temporary.replace(target)
            except Exception:
                temporary.unlink(missing_ok=True)
                raise
        elif _sha256_file(target) != actual_sha256:
            raise ProtectedCorpusError("protected_source_hash_mismatch")

        try:
            return self.store.add_protected_corpus_item(
                item={
                    "corpus_id": corpus_id,
                    "client_id": client_id,
                    "document_ref": document_ref,
                    "source_ref": str(document.get("document_ref") or document_ref),
                    "source_sha256": actual_sha256,
                    "protected_storage_path": str(target),
                    "direction": direction,
                    "source_snapshot": {
                        "original_file_name": str(document.get("original_file_name") or ""),
                        "size_bytes": int(document.get("size_bytes") or source_path.stat().st_size),
                        "sha256": actual_sha256,
                    },
                    "canonical_snapshot": {
                        "canonical_invoice": processed_result.get("canonical_invoice") or {},
                        "canonical_validation_status": str(
                            processed_result.get("canonical_validation_status") or ""
                        ),
                        "line_decisions": processed_result.get("line_decisions") or [],
                        "line_decision_coverage": processed_result.get("line_decision_coverage") or {},
                    },
                    "chart_snapshot": workspace.get("chart_accounts") or {},
                    "created_by": actor,
                }
            )
        except ValueError as exc:
            if not existed and str(exc) != "duplicate_corpus_source":
                target.unlink(missing_ok=True)
            raise ProtectedCorpusError(str(exc)) from exc

    def get_corpus(self, corpus_id: str) -> dict[str, Any]:
        corpus = self.store.get_protected_corpus(corpus_id)
        if not corpus:
            raise ProtectedCorpusError("corpus_not_found")
        items = self.store.list_protected_items(corpus_id)
        target_purchase_count = int(corpus.get("target_purchase_count") or 0)
        target_sales_count = int(corpus.get("target_sales_count") or 0)
        enrolled_purchase_count = sum(1 for item in items if item.get("direction") == "purchase")
        enrolled_sales_count = sum(1 for item in items if item.get("direction") in {"sale", "sales"})
        reference_ready_count = sum(1 for item in items if item.get("status") == "reference_ready")
        return {
            **corpus,
            "items": items,
            "target_purchase_count": target_purchase_count,
            "target_sales_count": target_sales_count,
            "enrolled_purchase_count": enrolled_purchase_count,
            "enrolled_sales_count": enrolled_sales_count,
            "reference_ready_count": reference_ready_count,
            "missing_reference_count": max(target_purchase_count + target_sales_count - reference_ready_count, 0),
            "status": str(corpus.get("status") or "draft"),
        }

    def capture_reference_if_enrolled(
        self,
        *,
        client_id: str,
        document_ref: str,
        saved_review: dict[str, Any],
        learning_event: dict[str, Any],
        actor: str,
    ) -> dict[str, Any] | None:
        item = self.store.protected_item_for_document(
            client_id=client_id,
            document_ref=document_ref,
        )
        if not item:
            return None
        corrected_document = saved_review.get("corrected_document") or {}
        result = corrected_document.get("result") if isinstance(corrected_document, dict) else {}
        if not isinstance(result, dict):
            result = {}
        proposal = result.get("proposal_snapshot") or {}
        final = result.get("accountant_final_decision") or {}
        quality_delta = result.get("quality_delta") or {}
        changed_fields = quality_delta.get("changed_fields") if isinstance(quality_delta, dict) else []
        canonical_validation = result.get("canonical_validation") or {}
        canonical_status = str(
            result.get("canonical_validation_status")
            or (canonical_validation.get("status") if isinstance(canonical_validation, dict) else "")
        ).strip().lower()
        line_decision_coverage = result.get("line_decision_coverage") or {}
        line_allocation_coverage = result.get("line_allocation_coverage") or {}
        line_decisions = result.get("line_decisions") or []
        canonical_invoice = result.get("canonical_invoice") or {}
        canonical_lines = canonical_invoice.get("line_items") if isinstance(canonical_invoice, dict) else []
        if (
            (not isinstance(line_allocation_coverage, dict) or not line_allocation_coverage)
            and isinstance(canonical_lines, list)
            and isinstance(result.get("draft_lines"), list)
        ):
            _allocation_plan, line_allocation_coverage = build_line_allocation_plan(
                canonical_lines=canonical_lines,
                draft_lines=result.get("draft_lines") or [],
                line_decisions=line_decisions,
            )
        authoritative = bool(result.get("is_balanced")) and str(result.get("export_status") or "") == "export_ready"
        if canonical_status not in {"ok", "valid", "passed"}:
            authoritative = False
        if not isinstance(line_decision_coverage, dict) or line_decision_coverage.get("status") != "valid":
            authoritative = False
        if not isinstance(line_allocation_coverage, dict) or line_allocation_coverage.get("status") != "valid":
            authoritative = False
        if not isinstance(proposal, dict) or not isinstance(final, dict) or not proposal or not final:
            authoritative = False
        quality_label = "unusable"
        if authoritative:
            change_count = len(changed_fields) if isinstance(changed_fields, list) else 0
            quality_label = "unchanged" if change_count == 0 else ("minor" if change_count == 1 else "material")
        outcome = self.store.append_reference_outcome(
            corpus_item_id=str(item.get("corpus_item_id") or item.get("item_id") or ""),
            outcome={
                "source_review_decision_id": str(saved_review.get("id") or ""),
                "quality_label": quality_label,
                "proposal_snapshot": proposal if isinstance(proposal, dict) else {},
                "accountant_final_decision": final if isinstance(final, dict) else {},
                "journal_snapshot": {
                    "draft_lines": result.get("draft_lines") or [],
                    "is_balanced": bool(result.get("is_balanced")),
                    "export_status": str(result.get("export_status") or ""),
                },
                "allocation_snapshot": {
                    "line_decision_coverage": line_decision_coverage,
                    "line_allocation_coverage": line_allocation_coverage,
                    "line_decisions": line_decisions if isinstance(line_decisions, list) else [],
                },
                "provenance": {
                    "canonical_validation": canonical_validation,
                    "quality_delta": quality_delta,
                    "document_ref": document_ref,
                    "review_record_id": str(saved_review.get("id") or ""),
                },
                "reviewer": actor,
                "reason": str(final.get("reason") or "") if isinstance(final, dict) else "",
                "is_authoritative": authoritative,
            },
        )
        protected_rule = self._capture_confirmed_rule(
            item=item,
            reference_version=int(outcome["version"]),
            learning_event=learning_event,
            actor=actor,
            authoritative=authoritative,
        )
        if protected_rule is not None:
            outcome["protected_rule"] = protected_rule
        return outcome

    def _capture_confirmed_rule(
        self,
        *,
        item: dict[str, Any],
        reference_version: int,
        learning_event: dict[str, Any],
        actor: str,
        authoritative: bool,
    ) -> dict[str, Any] | None:
        interpretation = learning_event.get("rule_interpretation") or {}
        confirmation = str(learning_event.get("learning_confirmation") or "").strip()
        if (
            not authoritative
            or confirmation != "save_rule"
            or not isinstance(interpretation, dict)
            or interpretation.get("source") != "accountant_confirmed"
        ):
            return None
        rule_key = str(interpretation.get("rule_key") or "").strip()
        if not rule_key:
            rule_key = hashlib.sha256(repr(sorted(interpretation.items())).encode("utf-8")).hexdigest()
        return self.store.append_protected_rule(
            corpus_item_id=str(item.get("corpus_item_id") or item.get("item_id") or ""),
            rule={
                "reference_version": reference_version,
                "rule_key": rule_key,
                "status": "active",
                "scope_snapshot": {"scope": str(learning_event.get("scope") or "client_rule")},
                "rule_snapshot": interpretation,
                "confirmed_by": actor,
            },
        )

    def verify_corpus_integrity(self, corpus_id: str) -> dict[str, Any]:
        corpus = self.store.get_protected_corpus(corpus_id)
        if not corpus:
            raise ProtectedCorpusError("corpus_not_found")
        items = self.store.list_protected_items(corpus_id)
        purchase_count = sum(1 for item in items if item.get("direction") == "purchase")
        sales_count = sum(1 for item in items if item.get("direction") == "sale")
        if purchase_count != int(corpus.get("target_purchase_count") or 0) or sales_count != int(
            corpus.get("target_sales_count") or 0
        ):
            raise ProtectedCorpusError("corpus_direction_count_mismatch")
        for item in items:
            if item.get("status") != "reference_ready":
                raise ProtectedCorpusError("reference_not_ready")
            path = Path(str(item.get("protected_storage_path") or ""))
            if not path.is_file() or _sha256_file(path) != str(item.get("source_sha256") or ""):
                raise ProtectedCorpusError("protected_source_hash_mismatch")
            references = self.store.list_reference_outcomes(
                str(item.get("corpus_item_id") or item.get("item_id") or "")
            )
            authoritative = [reference for reference in references if reference.get("is_authoritative")]
            if not authoritative:
                raise ProtectedCorpusError("reference_not_ready")
            latest = authoritative[-1]
            journal = latest.get("journal_snapshot") or {}
            if not isinstance(journal, dict) or not journal.get("is_balanced"):
                raise ProtectedCorpusError("reference_journal_unbalanced")
            proposal = latest.get("proposal_snapshot") or {}
            line_count = int(proposal.get("canonical_line_count") or 0) if isinstance(proposal, dict) else 0
            allocation = latest.get("allocation_snapshot") or {}
            decision_coverage = allocation.get("line_decision_coverage") if isinstance(allocation, dict) else {}
            allocation_coverage = allocation.get("line_allocation_coverage") if isinstance(allocation, dict) else {}
            expected_ids = decision_coverage.get("expected_ids") if isinstance(decision_coverage, dict) else []
            received_ids = decision_coverage.get("received_ids") if isinstance(decision_coverage, dict) else []
            if (
                line_count < 1
                or not isinstance(expected_ids, list)
                or not isinstance(received_ids, list)
                or len(expected_ids) != line_count
                or len(received_ids) != line_count
                or len(set(expected_ids)) != line_count
                or set(expected_ids) != set(received_ids)
                or decision_coverage.get("status") != "valid"
                or not isinstance(allocation_coverage, dict)
                or allocation_coverage.get("status") != "valid"
            ):
                raise ProtectedCorpusError("canonical_allocation_incomplete")
        return {
            "corpus_id": corpus_id,
            "purchase_count": purchase_count,
            "sales_count": sales_count,
            "reference_ready_count": len(items),
            "integrity": "ok",
        }

    def freeze_corpus(self, corpus_id: str) -> dict[str, Any]:
        integrity = self.verify_corpus_integrity(corpus_id)
        try:
            frozen = self.store.freeze_protected_corpus(corpus_id)
        except ValueError as exc:
            raise ProtectedCorpusError(str(exc)) from exc
        return {**frozen, "integrity": integrity}
