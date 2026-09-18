# File: backend/app/services/learned_rule_audit_shadow.py
# Summary: Runs a non-authoritative three-stage learned-rule audit beside production accounting without mutating the draft.
from __future__ import annotations

from dataclasses import dataclass
from time import perf_counter
import re
from typing import Any, Mapping, Sequence

from app.domain.learning_intelligence import normalize_text


PROMPT_VERSION = "learned-rule-audit-shadow-v3-20260918"
_ENABLED_VALUES = {"1", "true", "yes", "on"}

TEXT = {"type": "string"}
SEARCH_PLAN_SCHEMA = {
    "type": "object",
    "properties": {
        "row_plans": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "row_id": TEXT,
                    "queries": {
                        "type": "array",
                        "items": TEXT,
                        "minItems": 1,
                        "maxItems": 6,
                    },
                    "reason": TEXT,
                },
                "required": ["row_id", "queries", "reason"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["row_plans"],
    "additionalProperties": False,
}
CANDIDATE_PLAN_SCHEMA = {
    "type": "object",
    "properties": {
        "row_candidates": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "row_id": TEXT,
                    "candidate_refs": {
                        "type": "array",
                        "items": TEXT,
                        "maxItems": 16,
                    },
                    "reason": TEXT,
                },
                "required": ["row_id", "candidate_refs", "reason"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["row_candidates"],
    "additionalProperties": False,
}
FINAL_SCHEMA = {
    "type": "object",
    "properties": {
        "row_decisions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "row_id": TEXT,
                    "status": {
                        "type": "string",
                        "enum": ["correction", "no_change", "unresolved"],
                    },
                    "candidate_ref": {
                        "type": "string",
                        "pattern": "^(?:C[1-9][0-9]*|)$",
                    },
                    "from_account": TEXT,
                    "to_account": TEXT,
                    "reason": TEXT,
                },
                "required": [
                    "row_id",
                    "status",
                    "candidate_ref",
                    "from_account",
                    "to_account",
                    "reason",
                ],
                "additionalProperties": False,
            },
        }
    },
    "required": ["row_decisions"],
    "additionalProperties": False,
}

SEARCH_INSTRUCTIONS = """
You are stage 1 of a learned-rule audit that checks an existing accounting draft.
Do not redo accounting and do not change tax, amount, direction, counterparty, or journal structure.
Return exactly one search plan for every supplied row.
For each row generate distinct useful learned-rule search queries from the exact product/service meaning
and supplied counterparty context. Normally use three genuinely different searches when evidence supports
them: a distinctive phrase, a shorter product/service family, and counterparty plus product/service.
Do not omit a row because its draft account looks plausible. Do not pad the plan with word-order variants.
Return only row_plans.
""".strip()

CANDIDATE_INSTRUCTIONS = """
You are stage 2 of a learned-rule audit. You receive row-local candidate summaries returned by completed
rule-store searches. Candidate refs such as C1, C2 are opaque and local to one row.
For every row select every candidate whose summary could plausibly cover that exact row and therefore needs
its full rule content opened. Search rank, lexical overlap, title, and account code are discovery signals only.
A broad candidate does not eliminate a narrower one. Select only refs listed for that same row.
Do not decide whether a rule actually applies and do not make accounting decisions.
Return exactly one row_candidates item per row.
""".strip()

FINAL_INSTRUCTIONS = """
You are stage 3 of a learned-rule audit over an existing accounting draft.
The host already owns search/open telemetry. Return exactly one decision per row.

You receive row-local opened candidate refs with their full learned-rule content.
Search overlap and candidate selection are not authority. Applicability must be decided from the full rule:
meaning, scope, counterparty restriction, direction, conditions, exclusions, and exact product/service semantics.
Do not broaden generic words such as shell, service, repair, accessory, cargo, supplier, device, or part.

An accountant-confirmed product-family rule is applicable when its family meaning directly matches the row
after ordinary normalization of case, Turkish diacritics, punctuation, spacing, and extra model/size/side codes,
provided counterparty restrictions match and no explicit condition or exclusion contradicts it.
Extra variant codes alone do not defeat a direct family match.

Statuses:
- correction: an opened rule clearly applies and prescribes a different account.
- no_change: an opened rule clearly applies and confirms the draft account, or no opened rule applies.
- unresolved: applicability is genuinely uncertain, required conditions are unknown, or applicable rules conflict.

For correction, candidate_ref must be the applicable opened ref; from_account must equal the draft; to_account
must equal the rule account and differ from the draft.
For no_change with an applicable confirming rule, return its candidate_ref and echo the draft in from/to.
For no_change because no opened rule applies, leave candidate_ref/from_account/to_account empty.
For unresolved, leave candidate_ref/from_account/to_account empty.
Do not modify anything except a correction's row account.
""".strip()


@dataclass(frozen=True)
class _StageResult:
    value: dict[str, Any]
    elapsed_ms: int
    usage: dict[str, int]


def learned_rule_audit_shadow_enabled(env: Mapping[str, str]) -> bool:
    return str(env.get("FISORA_LEARNED_RULE_AUDIT_SHADOW_ENABLED") or "").strip().lower() in _ENABLED_VALUES


def learned_rule_audit_shadow_client_allowed(env: Mapping[str, str], client_id: str) -> bool:
    raw = str(env.get("FISORA_LEARNED_RULE_AUDIT_SHADOW_CLIENT_IDS") or "").strip()
    if not raw:
        return True
    allowed = {item.strip() for item in raw.split(",") if item.strip()}
    return str(client_id or "").strip() in allowed


def learned_rule_audit_shadow_model(env: Mapping[str, str]) -> str:
    return str(
        env.get("FISORA_LEARNED_RULE_AUDIT_SHADOW_MODEL")
        or "gemini-3.5-flash-lite"
    ).strip()


def run_learned_rule_audit_shadow(
    *,
    provider: object,
    active_rules: Sequence[Mapping[str, Any]],
    source_package: Mapping[str, object],
    semantic_plan: Mapping[str, object],
    final_output: Mapping[str, object],
    workspace: Mapping[str, object],
) -> dict[str, Any]:
    started = perf_counter()
    rules = [_rule_document(item) for item in active_rules if _usable_rule(item)]
    direction = str(semantic_plan.get("accounting_direction") or "").strip()
    rules = [item for item in rules if item["direction"] == direction]
    rows, skipped_rows = _auditable_rows(source_package, final_output)

    base = {
        "mode": "shadow",
        "prompt_version": PROMPT_VERSION,
        "direction": direction,
        "active_rule_count": len(rules),
        "audited_row_count": len(rows),
        "skipped_row_count": skipped_rows,
        "mutated_accounting": False,
    }
    if direction not in {"purchase", "sales"}:
        return {**base, "status": "skipped", "reason": "unsupported_direction", "elapsed_ms": 0}
    if not rules:
        return {**base, "status": "skipped", "reason": "no_active_rules", "elapsed_ms": 0}
    if not rows:
        return {**base, "status": "skipped", "reason": "no_auditable_rows", "elapsed_ms": 0}

    invoice = {
        "direction": direction,
        "counterparty": str(semantic_plan.get("counterparty_name") or ""),
        "counterparty_identifier": str(semantic_plan.get("counterparty_identifier") or ""),
        "rows": rows,
    }

    search_stage = _structured(
        provider,
        schema_name="learned_rule_audit_shadow_search",
        instructions=SEARCH_INSTRUCTIONS,
        payload={"invoice_and_draft": invoice},
        schema=SEARCH_PLAN_SCHEMA,
    )
    search_plan = _row_map(search_stage.value.get("row_plans"), rows, "search_plan")
    search_results: dict[str, list[dict[str, Any]]] = {}
    search_call_count = 0
    for row in rows:
        row_id = row["row_id"]
        queries = _unique_texts(search_plan[row_id].get("queries") or ())
        if not queries:
            raise ValueError(f"learned_rule_audit_empty_search_plan:{row_id}")
        results = []
        for query in queries:
            results.append(_search_rules(rules, query=query, direction=direction))
            search_call_count += 1
        search_results[row_id] = results

    catalogs, ref_maps = _candidate_catalogs(search_results)
    candidate_stage = _structured(
        provider,
        schema_name="learned_rule_audit_shadow_candidates",
        instructions=CANDIDATE_INSTRUCTIONS,
        payload={
            "invoice_and_draft": invoice,
            "candidate_catalog_by_row": catalogs,
        },
        schema=CANDIDATE_PLAN_SCHEMA,
    )
    candidate_plan = _row_map(
        candidate_stage.value.get("row_candidates"),
        rows,
        "candidate_plan",
    )

    opened_by_row: dict[str, dict[str, dict[str, Any]]] = {}
    get_rule_call_count = 0
    errors: list[str] = []
    rule_by_id = {item["rule_id"]: item for item in rules}
    for row in rows:
        row_id = row["row_id"]
        allowed = ref_maps[row_id]
        selected_refs = _unique_texts(candidate_plan[row_id].get("candidate_refs") or ())
        opened: dict[str, dict[str, Any]] = {}
        for candidate_ref in selected_refs:
            rule_id = allowed.get(candidate_ref)
            if not rule_id:
                errors.append(f"invalid_row_local_candidate_ref:{row_id}:{candidate_ref}")
                continue
            rule = rule_by_id.get(rule_id)
            get_rule_call_count += 1
            if rule is None:
                errors.append(f"rule_not_found:{row_id}:{candidate_ref}")
                continue
            opened[candidate_ref] = rule
        opened_by_row[row_id] = opened

    final_stage = _structured(
        provider,
        schema_name="learned_rule_audit_shadow_final",
        instructions=FINAL_INSTRUCTIONS,
        payload={
            "invoice_and_draft": invoice,
            "opened_candidates_by_row": _public_opened(opened_by_row),
            "candidate_open_errors": list(errors),
        },
        schema=FINAL_SCHEMA,
    )
    decisions = _row_map(final_stage.value.get("row_decisions"), rows, "final_decision")
    chart_codes = _chart_codes(workspace)

    row_audits: list[dict[str, Any]] = []
    corrections: list[dict[str, Any]] = []
    for row in rows:
        row_id = row["row_id"]
        draft_code = row["account_code"]
        decision = decisions[row_id]
        status = str(decision.get("status") or "")
        candidate_ref = str(decision.get("candidate_ref") or "")
        from_account = str(decision.get("from_account") or "")
        to_account = str(decision.get("to_account") or "")
        reason = str(decision.get("reason") or "")
        opened = opened_by_row[row_id]
        rule = opened.get(candidate_ref) if candidate_ref else None
        derived_status = status
        rule_id = ""

        if status == "correction":
            if rule is None:
                errors.append(f"correction_candidate_not_opened:{row_id}:{candidate_ref}")
            else:
                rule_id = rule["rule_id"]
                prescribed = rule["account_code"]
                if from_account != draft_code:
                    errors.append(f"correction_from_account_mismatch:{row_id}")
                if to_account != prescribed:
                    errors.append(f"correction_rule_account_mismatch:{row_id}:{candidate_ref}")
                if to_account == draft_code:
                    derived_status = "confirmed_unchanged"
                elif to_account not in chart_codes:
                    errors.append(f"correction_account_not_in_chart:{row_id}:{to_account}")
                else:
                    corrections.append(
                        {
                            "row_id": row_id,
                            "rule_id": rule_id,
                            "from_account": draft_code,
                            "to_account": to_account,
                            "reason": reason,
                        }
                    )
        elif status == "no_change":
            if candidate_ref:
                if rule is None:
                    errors.append(f"no_change_candidate_not_opened:{row_id}:{candidate_ref}")
                else:
                    rule_id = rule["rule_id"]
                    if rule["account_code"] != draft_code:
                        errors.append(f"no_change_rule_does_not_confirm_draft:{row_id}:{candidate_ref}")
                    derived_status = "confirmed_unchanged"
            else:
                derived_status = "no_applicable_rule_found"
        elif status == "unresolved":
            derived_status = "unresolved"
        else:
            errors.append(f"invalid_status:{row_id}:{status}")

        row_audits.append(
            {
                "row_id": row_id,
                "status": derived_status,
                "rule_id": rule_id,
                "reason": reason,
            }
        )

    unresolved = [item["row_id"] for item in row_audits if item["status"] == "unresolved"]
    audit_status = "incomplete" if unresolved or errors else "complete"
    total_usage = _sum_usage(search_stage.usage, candidate_stage.usage, final_stage.usage)
    elapsed_ms = round((perf_counter() - started) * 1000)

    return {
        **base,
        "status": "completed",
        "audit_status": audit_status,
        "elapsed_ms": elapsed_ms,
        "model_calls": 3,
        "rule_tool_calls": search_call_count + get_rule_call_count,
        "search_call_count": search_call_count,
        "get_rule_call_count": get_rule_call_count,
        "token_usage": total_usage,
        "stage_elapsed_ms": {
            "search_plan": search_stage.elapsed_ms,
            "candidate_selection": candidate_stage.elapsed_ms,
            "final_audit": final_stage.elapsed_ms,
        },
        "correction_count": len(corrections),
        "corrections": corrections,
        "row_audits": row_audits,
        "unresolved_rows": unresolved,
        "validation_errors": errors,
    }


def _structured(
    provider: object,
    *,
    schema_name: str,
    instructions: str,
    payload: Mapping[str, object],
    schema: Mapping[str, object],
) -> _StageResult:
    started = perf_counter()
    public = getattr(provider, "generate_structured_json", None)
    if callable(public):
        raw = public(
            schema_name=schema_name,
            instructions=instructions,
            user_payload=payload,
            schema=schema,
        )
    else:
        private = getattr(provider, "_post_structured_json")
        raw = private(
            schema_name=schema_name,
            instructions=instructions,
            user_payload=payload,
            schema=schema,
        )
    elapsed_ms = round((perf_counter() - started) * 1000)
    attempt = getattr(raw, "attempt", None)
    usage = dict(getattr(attempt, "token_usage", {}) or {})
    return _StageResult(
        value=dict(raw),
        elapsed_ms=elapsed_ms,
        usage={str(key): int(value or 0) for key, value in usage.items() if isinstance(value, (int, float))},
    )


def _auditable_rows(
    source_package: Mapping[str, object],
    final_output: Mapping[str, object],
) -> tuple[list[dict[str, str]], int]:
    source_rows = {
        str(item.get("source_position") or ""): item
        for item in source_package.get("invoice_table_rows") or ()
        if isinstance(item, Mapping)
    }
    rows: list[dict[str, str]] = []
    skipped = 0
    for raw in final_output.get("row_decisions") or ():
        if not isinstance(raw, Mapping):
            continue
        row_id = str(raw.get("source_position") or "").strip()
        account_code = str(raw.get("account_code") or "").strip()
        if not row_id or not account_code:
            skipped += 1
            continue
        source = source_rows.get(row_id, {})
        rows.append(
            {
                "row_id": row_id,
                "description": str(source.get("description") or ""),
                "source_text": str(source.get("source_text") or ""),
                "role": str(raw.get("role") or ""),
                "account_code": account_code,
                "reason": str(raw.get("reason") or ""),
            }
        )
    return rows, skipped


def _usable_rule(value: Mapping[str, Any]) -> bool:
    return bool(
        str(value.get("status") or "") == "active"
        and str(value.get("rule_id") or value.get("id") or "").strip()
        and str(value.get("account_code") or "").strip()
        and str(value.get("direction") or "").strip() in {"purchase", "sales"}
    )


def _rule_document(value: Mapping[str, Any]) -> dict[str, Any]:
    normalized_terms = [
        str(item).strip()
        for item in value.get("normalized_terms") or ()
        if str(item).strip()
    ]
    meaning = str(
        value.get("meaning_label")
        or value.get("semantic_intent")
        or value.get("reason")
        or value.get("category")
        or value.get("rule_key")
        or ""
    ).strip()
    title = str(
        value.get("meaning_label")
        or value.get("category")
        or value.get("semantic_intent")
        or value.get("rule_key")
        or "Accountant-confirmed learned rule"
    ).strip()
    search_terms = _unique_texts(
        [
            *normalized_terms,
            str(value.get("service_profile") or ""),
            str(value.get("semantic_intent") or ""),
            str(value.get("category") or ""),
            meaning,
        ]
    )
    return {
        "rule_id": str(value.get("rule_id") or value.get("id") or "").strip(),
        "title": title,
        "direction": str(value.get("direction") or "").strip(),
        "scope": str(value.get("scope") or "").strip(),
        "counterparty": str(value.get("counterparty_tax_id") or "").strip(),
        "search_terms": search_terms,
        "meaning": meaning,
        "guardrail": str(value.get("guardrail_tr") or "").strip(),
        "line_match_mode": str(value.get("line_match_mode") or "").strip(),
        "normalized_terms": normalized_terms,
        "semantic_role": str(value.get("semantic_role") or "").strip(),
        "semantic_intent": str(value.get("semantic_intent") or "").strip(),
        "service_profile": str(value.get("service_profile") or "").strip(),
        "account_code": str(value.get("account_code") or "").strip(),
    }


def _search_rules(
    rules: Sequence[Mapping[str, Any]],
    *,
    query: str,
    direction: str,
) -> dict[str, Any]:
    query_text = normalize_text(query)
    query_terms = set(query_text.split())
    query_compact = re.sub(r"[^a-z0-9]+", "", query_text)
    scored: list[tuple[int, Mapping[str, Any]]] = []
    for rule in rules:
        if rule.get("direction") != direction:
            continue
        text = normalize_text(
            " ".join(
                (
                    str(rule.get("title") or ""),
                    str(rule.get("counterparty") or ""),
                    " ".join(str(item) for item in rule.get("search_terms") or ()),
                    str(rule.get("meaning") or ""),
                    str(rule.get("guardrail") or ""),
                )
            )
        )
        terms = set(text.split())
        score = 12 * len(query_terms & terms)
        compact = re.sub(r"[^a-z0-9]+", "", text)
        if len(query_compact) >= 5 and (
            query_compact in compact or compact in query_compact
        ):
            score += 80
        if score > 0:
            scored.append((score, rule))
    scored.sort(key=lambda item: (-item[0], str(item[1].get("rule_id") or "")))
    items = [
        {
            "rule_id": str(rule.get("rule_id") or ""),
            "title": str(rule.get("title") or ""),
            "scope": str(rule.get("scope") or ""),
            "counterparty": str(rule.get("counterparty") or ""),
            "direction": str(rule.get("direction") or ""),
            "search_score": score,
        }
        for score, rule in scored[:8]
    ]
    return {"query": query, "total_matches": len(scored), "items": items}


def _candidate_catalogs(
    search_results: Mapping[str, Sequence[Mapping[str, Any]]],
) -> tuple[dict[str, list[dict[str, Any]]], dict[str, dict[str, str]]]:
    catalogs: dict[str, list[dict[str, Any]]] = {}
    ref_maps: dict[str, dict[str, str]] = {}
    for row_id, results in search_results.items():
        seen: set[str] = set()
        items: list[dict[str, Any]] = []
        refs: dict[str, str] = {}
        index = 1
        for result in results:
            for raw in result.get("items") or ():
                if not isinstance(raw, Mapping):
                    continue
                rule_id = str(raw.get("rule_id") or "")
                if not rule_id or rule_id in seen:
                    continue
                seen.add(rule_id)
                candidate_ref = f"C{index}"
                index += 1
                refs[candidate_ref] = rule_id
                items.append(
                    {
                        "candidate_ref": candidate_ref,
                        "title": str(raw.get("title") or ""),
                        "scope": str(raw.get("scope") or ""),
                        "counterparty": str(raw.get("counterparty") or ""),
                        "direction": str(raw.get("direction") or ""),
                    }
                )
        catalogs[row_id] = items
        ref_maps[row_id] = refs
    return catalogs, ref_maps


def _public_opened(
    opened_by_row: Mapping[str, Mapping[str, Mapping[str, Any]]],
) -> dict[str, list[dict[str, Any]]]:
    return {
        row_id: [
            {
                "candidate_ref": candidate_ref,
                "rule": {
                    key: value
                    for key, value in rule.items()
                    if key != "rule_id"
                },
            }
            for candidate_ref, rule in mapping.items()
        ]
        for row_id, mapping in opened_by_row.items()
    }


def _row_map(
    items: object,
    rows: Sequence[Mapping[str, str]],
    label: str,
) -> dict[str, dict[str, Any]]:
    expected = [str(row["row_id"]) for row in rows]
    mapped: dict[str, dict[str, Any]] = {}
    for raw in items or ():
        if not isinstance(raw, Mapping):
            continue
        row_id = str(raw.get("row_id") or "")
        if row_id in mapped:
            raise ValueError(f"learned_rule_audit_duplicate_{label}_row:{row_id}")
        mapped[row_id] = dict(raw)
    if sorted(mapped) != sorted(expected):
        raise ValueError(f"learned_rule_audit_{label}_coverage_mismatch")
    return mapped


def _chart_codes(workspace: Mapping[str, object]) -> set[str]:
    chart = workspace.get("chart_accounts")
    chart = chart if isinstance(chart, Mapping) else {}
    values = chart.get("accounts") or workspace.get("accounts") or ()
    result: set[str] = set()
    if not isinstance(values, Sequence) or isinstance(values, (str, bytes)):
        return result
    for raw in values:
        if not isinstance(raw, Mapping):
            continue
        if raw.get("is_detail_account") is False or raw.get("is_active") is False:
            continue
        code = str(
            raw.get("normalized_account_code")
            or raw.get("account_code")
            or raw.get("code")
            or ""
        ).strip()
        if code:
            result.add(code)
    return result


def _unique_texts(values: Sequence[object]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = str(value or "").strip()
        key = normalize_text(text)
        if not text or not key or key in seen:
            continue
        seen.add(key)
        out.append(text)
    return out


def _sum_usage(*usages: Mapping[str, int]) -> dict[str, int]:
    keys = {key for usage in usages for key in usage}
    return {
        key: sum(int(usage.get(key) or 0) for usage in usages)
        for key in sorted(keys)
    }
