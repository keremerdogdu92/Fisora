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
REVIEW_REQUIRED_ACTIONS = {"wrong_account", "wrong_counterparty", "review_required"}


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
    statement_line_no = _positive_int(decision.get("statement_line_no") or learning_event.get("statement_line_no"))

    if statement_line_no:
        _apply_statement_line_review(
            result,
            line_no=statement_line_no,
            action=action,
            corrected_account=corrected_account,
            corrected_counterparty=corrected_counterparty,
            reviewer=reviewer,
            reason=reason,
            reviewed_at=reviewed_at,
        )
    else:
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

    if statement_line_no:
        _roll_up_statement_review_status(updated, result)
    elif action in APPROVED_EXPORT_ACTIONS:
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


def _positive_int(value: object) -> int:
    try:
        parsed = int(value or 0)
    except (TypeError, ValueError):
        return 0
    return parsed if parsed > 0 else 0


def _apply_statement_line_review(
    result: dict[str, Any],
    *,
    line_no: int,
    action: str,
    corrected_account: str,
    corrected_counterparty: str,
    reviewer: str,
    reason: str,
    reviewed_at: str,
) -> None:
    statement_lines = result.get("statement_lines")
    if not isinstance(statement_lines, list):
        return
    line_index = line_no - 1
    if line_index < 0 or line_index >= len(statement_lines):
        return
    review_status = _statement_review_status(action)
    new_account = corrected_counterparty or corrected_account
    updated_line = dict(statement_lines[line_index])
    if new_account:
        updated_line["suggested_account_code"] = new_account
        updated_line["counterparty_match_code"] = new_account
        updated_line["counterparty_match_confidence"] = 100
        updated_line["counterparty_match_reason"] = "accountant_corrected"
    updated_line["accountant_review_status"] = review_status
    updated_line["accountant_reviewed_by"] = reviewer
    updated_line["accountant_reviewed_at"] = reviewed_at
    updated_line["accountant_review_reason"] = reason
    updated_line["risk_flags"] = list(_reviewed_statement_risks(updated_line.get("risk_flags"), review_status))
    statement_lines[line_index] = updated_line
    result["statement_lines"] = statement_lines

    statement_entries = result.get("statement_entries")
    if not isinstance(statement_entries, list):
        return
    entry_index = _statement_entry_index(statement_entries, line_no=line_no, fallback_index=line_index)
    if entry_index < 0:
        return
    entry = statement_entries[entry_index]
    if not isinstance(entry, dict):
        return
    updated_entry = dict(entry)
    if new_account:
        updated_entry["lines"] = _replace_statement_counterpart_account(list(updated_entry.get("lines") or []), new_account)
    updated_entry["accountant_review_status"] = review_status
    updated_entry["accountant_reviewed_by"] = reviewer
    updated_entry["accountant_reviewed_at"] = reviewed_at
    updated_entry["accountant_review_reason"] = reason
    updated_entry["risk_flags"] = list(_reviewed_statement_risks(updated_entry.get("risk_flags"), review_status))
    statement_entries[entry_index] = updated_entry
    result["statement_entries"] = statement_entries


def _statement_review_status(action: str) -> str:
    if action in APPROVED_EXPORT_ACTIONS:
        return "approved"
    if action in REJECTED_EXPORT_ACTIONS:
        return "rejected"
    return "review_required"


def _reviewed_statement_risks(value: object, review_status: str) -> tuple[str, ...]:
    if isinstance(value, list | tuple):
        flags = tuple(str(flag) for flag in value if str(flag).strip())
    else:
        flags = ()
    if review_status == "approved":
        removable = {
            "ai_invalid_schema",
            "counterparty_match_review_required",
            "counterparty_not_found",
            "learning_rule_review_required",
            "statement_accountant_approval_required",
            "statement_review_required",
        }
        return tuple(flag for flag in flags if flag not in removable)
    if review_status == "rejected":
        return tuple(dict.fromkeys((*flags, "statement_line_rejected")))
    return tuple(dict.fromkeys((*flags, "statement_review_required")))


def _replace_statement_counterpart_account(lines: list[Any], new_code: str) -> list[dict[str, Any]]:
    updated_lines: list[dict[str, Any]] = []
    replaced = False
    for line in lines:
        if not isinstance(line, dict):
            continue
        updated_line = dict(line)
        account_code = str(updated_line.get("account_code") or "").strip()
        if not replaced and account_code and not account_code.startswith("102"):
            updated_line["account_code"] = new_code
            replaced = True
        updated_lines.append(updated_line)
    return updated_lines


def _statement_entry_index(entries: list[Any], *, line_no: int, fallback_index: int) -> int:
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            continue
        if _positive_int(entry.get("statement_line_no")) == line_no:
            return index
    return fallback_index if 0 <= fallback_index < len(entries) else -1


def _roll_up_statement_review_status(updated: dict[str, Any], result: dict[str, Any]) -> None:
    statement_entries = result.get("statement_entries")
    if not isinstance(statement_entries, list) or not statement_entries:
        result["accountant_export_override"] = False
        result["export_status"] = "review_required"
        updated["export_status"] = "review_required"
        return
    approved_count = 0
    rejected_count = 0
    review_required_count = 0
    for entry in statement_entries:
        if not isinstance(entry, dict):
            review_required_count += 1
            continue
        status = str(entry.get("accountant_review_status") or "")
        if status == "approved":
            approved_count += 1
        elif status == "rejected":
            rejected_count += 1
        else:
            review_required_count += 1
    result["statement_review_summary"] = {
        "approved_count": approved_count,
        "rejected_count": rejected_count,
        "review_required_count": review_required_count,
    }
    all_approved = approved_count == len(statement_entries) and rejected_count == 0 and review_required_count == 0
    result["accountant_export_override"] = all_approved
    result["export_status"] = "export_ready" if all_approved else "review_required"
    updated["export_status"] = result["export_status"]


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
