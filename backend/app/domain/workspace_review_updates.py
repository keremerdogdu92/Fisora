from __future__ import annotations

from copy import deepcopy
from typing import Any


APPROVED_EXPORT_ACTIONS = {"approve", "approve_with_changes", "suggest_for_similar"}
REJECTED_EXPORT_ACTIONS = {
    "exclude_export",
    "exclude_from_export",
    "out_of_scope",
    "business_out_of_scope",
}
REVIEW_REQUIRED_ACTIONS = {"wrong_account", "wrong_counterparty"}


def apply_review_decision_to_document(
    document: dict[str, Any],
    *,
    decision: dict[str, Any],
    learning_event: dict[str, Any],
    reviewed_at: str,
) -> dict[str, Any]:
    """Apply accountant approval/correction effects to a stored workspace document."""

    updated = deepcopy(document)
    result = deepcopy(updated.get("result") or {})
    if not isinstance(result, dict) or not result:
        return updated

    action = str(decision.get("action") or "")
    corrected_account = str(decision.get("corrected_account_code") or "").strip()
    corrected_counterparty = str(decision.get("corrected_counterparty_code") or "").strip()
    reviewer = str(decision.get("reviewer") or "").strip()
    reason = str(decision.get("reason") or learning_event.get("reason") or "").strip()

    old_expense_account = str(result.get("selected_expense_account") or "").strip()
    old_supplier_account = str(result.get("selected_supplier_account") or "").strip()
    old_counterparty_account = str(result.get("counterparty_match_code") or "").strip()

    if corrected_account:
        result["draft_lines"] = _replace_line_accounts(
            list(result.get("draft_lines") or []),
            old_codes={old_expense_account},
            new_code=corrected_account,
        )
        _replace_statement_entry_accounts(result, {old_expense_account}, corrected_account)
        result["selected_expense_account"] = corrected_account

    if corrected_counterparty:
        supplier_targets = {old_supplier_account, old_counterparty_account}
        result["draft_lines"] = _replace_line_accounts(
            list(result.get("draft_lines") or []),
            old_codes=supplier_targets,
            new_code=corrected_counterparty,
        )
        _replace_statement_entry_accounts(result, supplier_targets, corrected_counterparty)
        result["selected_supplier_account"] = corrected_counterparty
        result["counterparty_match_code"] = corrected_counterparty
        result["counterparty_match_confidence"] = 100
        result["counterparty_match_reason"] = "accountant_corrected"

    if corrected_account or corrected_counterparty:
        result["learning_rule_applied"] = True
        result["learning_rule_scope"] = str(learning_event.get("scope") or "client_rule")
        result["learning_rule_reason"] = reason or "Musavir duzeltmesi kalici taslaga uygulandi."

    result["accountant_decision_action"] = action
    result["accountant_decision_reason"] = reason
    result["accountant_reviewed_at"] = reviewed_at
    result["accountant_reviewed_by"] = reviewer

    if action in APPROVED_EXPORT_ACTIONS:
        result["accountant_export_override"] = True
        result["export_status"] = "export_ready"
        updated["export_status"] = "export_ready"
    elif action in REJECTED_EXPORT_ACTIONS:
        result["accountant_export_override"] = False
        result["export_status"] = "rejected"
        updated["export_status"] = "rejected"
    elif action in REVIEW_REQUIRED_ACTIONS:
        result["accountant_export_override"] = False
        result["export_status"] = "review_required"
        updated["export_status"] = "review_required"

    updated["result"] = result
    updated["updated_at"] = reviewed_at
    return updated


def mark_export_package_downloaded(
    record: dict[str, Any],
    *,
    downloaded_at: str,
) -> dict[str, Any]:
    updated = deepcopy(record)
    package = updated.get("package")
    if not isinstance(package, dict):
        package = {}
        updated["package"] = package
    package["downloaded_at"] = downloaded_at
    package["download_count"] = int(package.get("download_count") or 0) + 1
    updated["updated_at"] = downloaded_at
    return updated


def _replace_statement_entry_accounts(result: dict[str, Any], old_codes: set[str], new_code: str) -> None:
    statement_entries = result.get("statement_entries")
    if not isinstance(statement_entries, list):
        return
    result["statement_entries"] = [
        {
            **entry,
            "lines": _replace_line_accounts(
                list(entry.get("lines") or []),
                old_codes=old_codes,
                new_code=new_code,
            ),
        }
        if isinstance(entry, dict)
        else entry
        for entry in statement_entries
    ]


def _replace_line_accounts(lines: list[Any], *, old_codes: set[str], new_code: str) -> list[dict[str, Any]]:
    normalized_targets = {code for code in old_codes if code}
    updated_lines: list[dict[str, Any]] = []
    for line in lines:
        if not isinstance(line, dict):
            continue
        updated_line = dict(line)
        if normalized_targets and str(updated_line.get("account_code") or "").strip() in normalized_targets:
            updated_line["account_code"] = new_code
        updated_lines.append(updated_line)
    return updated_lines
