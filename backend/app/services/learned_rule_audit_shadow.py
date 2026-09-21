# File: backend/app/services/learned_rule_audit_shadow.py
# Summary: Produces validated three-stage learned-rule audit corrections; the workflow applies only safe corrections with provenance.
from __future__ import annotations

from dataclasses import dataclass
from time import perf_counter
from typing import Any, Mapping, Sequence

from app.domain.learning_intelligence import normalize_text


PROMPT_VERSION = "learned-rule-audit-v5-semantic-blind-20260919"
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
CANDIDATE_ASSESSMENT_SCHEMA = {
    "type": "object",
    "properties": {
        "candidate_ref": {
            "type": "string",
            "pattern": "^C[1-9][0-9]*$",
        },
        "verdict": {
            "type": "string",
            "enum": ["applies", "not_applicable", "uncertain"],
        },
        "reason": TEXT,
    },
    "required": ["candidate_ref", "verdict", "reason"],
    "additionalProperties": False,
}
FINAL_SCHEMA = {
    "type": "object",
    "properties": {
        "row_resolutions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "row_id": TEXT,
                    "candidate_assessments": {
                        "type": "array",
                        "items": CANDIDATE_ASSESSMENT_SCHEMA,
                    },
                    "status": {
                        "type": "string",
                        "enum": ["resolved", "no_applicable_rule", "unresolved"],
                    },
                    "candidate_ref": {
                        "type": "string",
                        "pattern": "^(?:C[1-9][0-9]*|)$",
                    },
                    "resolved_account": TEXT,
                    "reason": TEXT,
                },
                "required": [
                    "row_id",
                    "candidate_assessments",
                    "status",
                    "candidate_ref",
                    "resolved_account",
                    "reason",
                ],
                "additionalProperties": False,
            },
        }
    },
    "required": ["row_resolutions"],
    "additionalProperties": False,
}

SEARCH_INSTRUCTIONS = """
You are stage 1 of an independent learned-rule audit.
The normal accounting draft has already been produced, but its account choices are intentionally hidden from you.
Do not redo accounting and do not change tax, amount, direction, counterparty, or journal structure.
Return exactly one search plan for every supplied row.
For each row generate distinct useful learned-rule search queries from the exact product/service meaning
and supplied counterparty context. Normally use three genuinely different searches when evidence supports
them: a distinctive phrase, a shorter product/service family, and counterparty plus product/service.
Every row must be searched even when no rule is expected. Do not pad the plan with word-order variants.
Return only row_plans.
""".strip()

CANDIDATE_INSTRUCTIONS = """
You are stage 2 of an independent learned-rule audit. You receive row-local candidate summaries returned by
completed rule-store searches. Candidate refs such as C1, C2 are opaque and local to one row.
For every row select every candidate whose compact summary could plausibly cover that exact row and therefore
needs its full rule content opened. Search matches, titles, declared terms, scope, binding_mode, semantic_role,
semantic_intent and fixed account codes are discovery signals only. A broad candidate does not eliminate a
narrower one. Select only refs listed for that same row.
Do not decide whether a rule actually applies and do not make accounting decisions.
Return exactly one row_candidates item per row.
""".strip()

FINAL_INSTRUCTIONS = """
You are stage 3 of an independent learned-rule audit.

Critical separation of responsibility:
- The normal accounting AI's current/draft account is intentionally NOT provided. Do not infer it.
- First assess every opened FULL learned rule for the exact invoice row.
- Only after at least one opened rule is assessed applies may you resolve an account.
- The host, not you, will later compare resolved_account with the existing draft and decide correction/no-change.

Opened rules have human-readable summary/trigger/action/guardrail plus authoritative machine fields.
There are two binding modes:
1) fixed_account: if the rule applies, its account_code is the exact authoritative result.
2) semantic_role: the rule intentionally stores NO historical/source exact account. If it applies, semantic_role
   and semantic_intent define the accounting meaning. Resolve the exact CURRENT detail account only from the
   invoice row, counterparty context, and current_client_chart_by_row supplied for that row.

For EVERY row assess EVERY opened candidate exactly once as applies/not_applicable/uncertain.
Hard gate:
- If zero candidates apply, MUST return no_applicable_rule with candidate_ref="" and resolved_account="".
- Do NOT independently classify/account a row from invoice text or chart when no learned rule applies.

Return:
- resolved: at least one opened rule applies, candidate_ref names an applies candidate, and that rule determines
  one exact current result.
- no_applicable_rule: zero opened rules apply; candidate_ref and resolved_account must be empty.
- unresolved: applicability conflicts/uncertainty, required conditions are unknown, or an applicable semantic rule
  still leaves more than one exact current detail account genuinely plausible.

For resolved:
- candidate_ref MUST be non-empty and assessed applies.
- fixed_account => resolved_account MUST exactly equal that rule's account_code.
- semantic_role => resolved_account MUST be copied exactly from current_client_chart_by_row.
For no_applicable_rule/unresolved, candidate_ref and resolved_account must be empty.

Applicability:
- Full trigger/scope/counterparty/direction/line-match/guardrail are authoritative.
- Search overlap is never authority.
- An all_lines client_counterparty rule is supplier-wide authority: ordinary row wording alone does not defeat it
  unless the rule trigger/guardrail explicitly excludes that row or a narrower applicable rule overrides it.
- When multiple applicable rules overlap, a line-specific normalized_terms_all rule is narrower than an all_lines
  supplier/service rule and governs that row. The broad rule remains the fallback for other rows.
- When a narrower fixed_account rule overlaps a broader semantic_role rule, the narrower fixed account is the
  authoritative exact result for that row.
- Product/service family rules match after ordinary normalization of case, Turkish diacritics, punctuation and
  spacing. Extra model/generation/size/side/serial suffixes do not defeat a direct family match unless explicitly
  excluded by the rule.
- Never invent a narrower variant restriction that is not written in the opened rule.
- A short legal/brand alias may match a longer invoice legal name only when it clearly identifies the same entity.

Semantic resolution:
- Never invent or reconstruct a historical/source account.
- First obey semantic_role/semantic_intent, then choose the most specific matching CURRENT detail account.
- If two current detail accounts remain genuinely plausible, return unresolved rather than guessing.
- Product subtype matters: hearing-device stock is not accessory/KIT stock; cargo is not generic expense;
  personnel meal is not representation; exemption revenue is not ordinary taxable revenue.

Do not change tax, amounts, direction, counterparty or row structure.
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
    expected_direction: str = "",
) -> dict[str, Any]:
    started = perf_counter()
    rules = [_rule_document(item) for item in active_rules if _usable_rule(item)]
    raw_direction = str(semantic_plan.get("accounting_direction") or "").strip()
    invoice_mode = _invoice_mode_from_source_package(source_package, semantic_plan)
    direction = raw_direction
    if raw_direction == "return":
        fallback_direction = str(expected_direction or "").strip()
        direction = fallback_direction if fallback_direction in {"purchase", "sales"} else ""
    rules = [
        item
        for item in rules
        if item["direction"] == direction and item["invoice_mode"] == invoice_mode
    ]
    rows, skipped_rows = _auditable_rows(source_package, final_output)

    base = {
        "mode": "shadow",
        "prompt_version": PROMPT_VERSION,
        "direction": direction,
        "source_direction": raw_direction,
        "invoice_mode": invoice_mode,
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

    invoice_context = {
        "direction": direction,
        "invoice_mode": invoice_mode,
        "counterparty": str(semantic_plan.get("counterparty_name") or ""),
        "counterparty_identifier": str(semantic_plan.get("counterparty_identifier") or ""),
        "rows": [_independent_row_view(row) for row in rows],
    }

    search_stage = _structured(
        provider,
        schema_name="learned_rule_audit_shadow_search",
        instructions=SEARCH_INSTRUCTIONS,
        payload={"invoice_context": invoice_context},
        schema=SEARCH_PLAN_SCHEMA,
    )
    search_plan = _row_map(search_stage.value.get("row_plans"), rows, "search_plan")
    search_results: dict[str, list[dict[str, Any]]] = {}
    search_call_count = 0
    errors: list[str] = []
    for row in rows:
        row_id = row["row_id"]
        queries = _unique_texts(search_plan[row_id].get("queries") or ())
        if not queries:
            raise ValueError(f"learned_rule_audit_empty_search_plan:{row_id}")
        results = []
        for query in queries:
            search_result = _search_rules(
                rules,
                query=query,
                direction=direction,
                counterparty_identifier=str(invoice_context.get("counterparty_identifier") or ""),
            )
            results.append(search_result)
            search_call_count += 1
            if search_result.get("overflow"):
                errors.append(
                    f"search_result_overflow:{row_id}:{query}:{search_result.get('total_matches', 0)}"
                )
        search_results[row_id] = results

    catalogs, ref_maps = _candidate_catalogs(search_results)
    candidate_stage = _structured(
        provider,
        schema_name="learned_rule_audit_shadow_candidates",
        instructions=CANDIDATE_INSTRUCTIONS,
        payload={
            "invoice_context": invoice_context,
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

    chart_by_row = _current_chart_by_row(opened_by_row, workspace)
    final_stage = _structured(
        provider,
        schema_name="learned_rule_audit_shadow_final",
        instructions=FINAL_INSTRUCTIONS,
        payload={
            "invoice_context": invoice_context,
            "current_client_chart_by_row": chart_by_row,
            "opened_candidates_by_row": _public_opened(opened_by_row),
            "candidate_open_errors": list(errors),
        },
        schema=FINAL_SCHEMA,
    )
    resolutions = _row_map(final_stage.value.get("row_resolutions"), rows, "final_resolution")
    chart_codes = _chart_codes(workspace)

    row_audits: list[dict[str, Any]] = []
    corrections: list[dict[str, Any]] = []
    for row in rows:
        row_id = row["row_id"]
        draft_code = row["account_code"]
        resolution = resolutions[row_id]
        status = str(resolution.get("status") or "")
        candidate_ref = str(resolution.get("candidate_ref") or "")
        resolved_account = str(resolution.get("resolved_account") or "")
        reason = str(resolution.get("reason") or "")
        opened = opened_by_row[row_id]

        assessments = list(resolution.get("candidate_assessments") or ())
        assessment_map: dict[str, str] = {}
        for raw in assessments:
            if not isinstance(raw, Mapping):
                errors.append(f"invalid_candidate_assessment:{row_id}")
                continue
            ref = str(raw.get("candidate_ref") or "")
            verdict = str(raw.get("verdict") or "")
            if ref in assessment_map:
                errors.append(f"duplicate_candidate_assessment:{row_id}:{ref}")
            assessment_map[ref] = verdict
            if ref not in opened:
                errors.append(f"assessment_candidate_not_opened:{row_id}:{ref}")
        opened_refs = set(opened)
        assessed_refs = set(assessment_map)
        if assessed_refs != opened_refs:
            missing = sorted(opened_refs - assessed_refs)
            extra = sorted(assessed_refs - opened_refs)
            if missing:
                errors.append(f"candidate_assessment_missing:{row_id}:{','.join(missing)}")
            if extra:
                errors.append(f"candidate_assessment_extra:{row_id}:{','.join(extra)}")

        applies = [ref for ref, verdict in assessment_map.items() if verdict == "applies"]
        uncertain = [ref for ref, verdict in assessment_map.items() if verdict == "uncertain"]
        rule = opened.get(candidate_ref) if candidate_ref else None
        derived_status = status
        rule_id = ""

        if status == "resolved":
            if rule is None or assessment_map.get(candidate_ref) != "applies":
                errors.append(f"resolved_candidate_not_opened_applies:{row_id}:{candidate_ref}")
            else:
                rule_id = rule["rule_id"]
                mode = str(rule.get("binding_mode") or "fixed_account")
                if not resolved_account:
                    errors.append(f"resolved_account_missing:{row_id}")
                elif mode == "fixed_account":
                    prescribed = str(rule.get("account_code") or "")
                    if resolved_account != prescribed:
                        errors.append(f"resolved_fixed_account_mismatch:{row_id}:{candidate_ref}")
                    if resolved_account not in chart_codes:
                        errors.append(f"resolved_account_not_in_chart:{row_id}:{resolved_account}")
                elif mode == "semantic_role":
                    row_chart_codes = {
                        str(item.get("account_code") or "")
                        for item in chart_by_row.get(row_id, ())
                        if isinstance(item, Mapping)
                    }
                    if resolved_account not in row_chart_codes:
                        errors.append(f"resolved_semantic_account_not_in_row_chart:{row_id}:{resolved_account}")
                    semantic_role = str(rule.get("semantic_role") or "")
                    if not _account_code_matches_semantic_role(resolved_account, semantic_role):
                        errors.append(
                            f"resolved_semantic_role_mismatch:{row_id}:{resolved_account}:{semantic_role}"
                        )
                else:
                    errors.append(f"resolved_unknown_binding_mode:{row_id}:{mode}")

                _validate_applicable_rule_compatibility(
                    row_id=row_id,
                    applies=applies,
                    opened=opened,
                    selected_ref=candidate_ref,
                    resolved_account=resolved_account,
                    errors=errors,
                )

                if resolved_account == draft_code:
                    derived_status = "confirmed_unchanged"
                elif resolved_account:
                    derived_status = "correction"
                    corrections.append(
                        {
                            "row_id": row_id,
                            "rule_id": rule_id,
                            "from_account": draft_code,
                            "to_account": resolved_account,
                            "reason": reason,
                        }
                    )
        elif status == "no_applicable_rule":
            derived_status = "no_applicable_rule_found"
            if candidate_ref or resolved_account:
                errors.append(f"no_applicable_rule_fields_must_be_empty:{row_id}")
            if applies:
                errors.append(f"applicable_rule_silently_ignored:{row_id}:{','.join(applies)}")
            if uncertain:
                errors.append(f"uncertain_rule_not_unresolved:{row_id}:{','.join(uncertain)}")
        elif status == "unresolved":
            derived_status = "unresolved"
            if candidate_ref or resolved_account:
                errors.append(f"unresolved_fields_must_be_empty:{row_id}")
            if not uncertain and len(applies) <= 1:
                errors.append(f"unresolved_without_conflict_or_uncertainty:{row_id}")
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



def _independent_row_view(row: Mapping[str, str]) -> dict[str, str]:
    """AI-visible row context deliberately excludes the normal accountant AI's account/reason."""
    return {
        "row_id": str(row.get("row_id") or ""),
        "description": str(row.get("description") or ""),
        "source_text": str(row.get("source_text") or ""),
        "role": str(row.get("role") or ""),
    }


def _current_chart_by_row(
    opened_by_row: Mapping[str, Mapping[str, Mapping[str, Any]]],
    workspace: Mapping[str, object],
) -> dict[str, list[dict[str, object]]]:
    accounts = _chart_account_rows(workspace)
    result: dict[str, list[dict[str, object]]] = {}
    for row_id, opened in opened_by_row.items():
        roles = {
            str(rule.get("semantic_role") or "").strip()
            for rule in opened.values()
            if str(rule.get("binding_mode") or "fixed_account").strip() == "semantic_role"
            and str(rule.get("semantic_role") or "").strip()
        }
        if not roles:
            result[row_id] = []
            continue
        result[row_id] = [
            account
            for account in accounts
            if any(
                _chart_account_matches_semantic_role(account, role)
                for role in roles
            )
        ]
    return result


def _chart_account_rows(workspace: Mapping[str, object]) -> list[dict[str, object]]:
    chart = workspace.get("chart_accounts")
    chart = chart if isinstance(chart, Mapping) else {}
    values = chart.get("accounts") or workspace.get("accounts") or ()
    if not isinstance(values, Sequence) or isinstance(values, (str, bytes)):
        return []
    result: list[dict[str, object]] = []
    for raw in values:
        if not isinstance(raw, Mapping):
            continue
        if raw.get("is_detail_account") is False or raw.get("is_active") is False:
            continue
        code = str(
            raw.get("normalized_account_code")
            or raw.get("account_code")
            or raw.get("code")
            or raw.get("raw_account_code")
            or ""
        ).strip()
        if not code:
            continue
        raw_roles = raw.get("semantic_roles") or raw.get("semantic_role") or ()
        if isinstance(raw_roles, str):
            raw_roles = (raw_roles,)
        result.append(
            {
                "account_code": code,
                "account_name": str(raw.get("account_name") or raw.get("name") or raw.get("title") or ""),
                "semantic_roles": [str(item) for item in raw_roles if str(item).strip()],
            }
        )
    return result


def _chart_account_matches_semantic_role(account: Mapping[str, object], semantic_role: str) -> bool:
    code = str(account.get("account_code") or "")
    role = str(semantic_role or "").strip()
    raw_roles = account.get("semantic_roles") or ()
    normalized_roles = {normalize_text(item).replace(" ", "_") for item in raw_roles}
    if role == "stock":
        return code.startswith(("150", "151", "152", "153")) or any("stock" in item for item in normalized_roles)
    if role == "expense":
        return code.startswith(("730", "740", "750", "760", "770", "780")) or "expense" in normalized_roles
    if role == "non_deductible":
        return code.startswith("689") or "non_deductible" in normalized_roles
    if role == "revenue":
        return code.startswith(("600", "601", "602")) or any("revenue" in item for item in normalized_roles)
    return role in normalized_roles


def _account_code_matches_semantic_role(account_code: str, semantic_role: str) -> bool:
    return _chart_account_matches_semantic_role(
        {"account_code": account_code, "semantic_roles": []},
        semantic_role,
    )


def _validate_applicable_rule_compatibility(
    *,
    row_id: str,
    applies: Sequence[str],
    opened: Mapping[str, Mapping[str, Any]],
    selected_ref: str,
    resolved_account: str,
    errors: list[str],
) -> None:
    applicable = [ref for ref in applies if ref in opened]
    if not applicable:
        return
    highest_specificity = max(_rule_specificity(opened[ref]) for ref in applicable)
    effective_applies = [
        ref
        for ref in applicable
        if _rule_specificity(opened[ref]) == highest_specificity
    ]
    if selected_ref and selected_ref not in effective_applies:
        errors.append(
            f"less_specific_rule_selected:{row_id}:{selected_ref}:{','.join(sorted(effective_applies))}"
        )
    fixed_codes = {
        str(opened[ref].get("account_code") or "")
        for ref in effective_applies
        if str(opened[ref].get("binding_mode") or "fixed_account") == "fixed_account"
        and str(opened[ref].get("account_code") or "")
    }
    semantic_keys = {
        (
            str(opened[ref].get("semantic_role") or ""),
            str(opened[ref].get("semantic_intent") or ""),
        )
        for ref in effective_applies
        if str(opened[ref].get("binding_mode") or "fixed_account") == "semantic_role"
    }
    if len(fixed_codes) > 1:
        errors.append(f"conflicting_fixed_rules:{row_id}:{','.join(sorted(fixed_codes))}")
    if len(semantic_keys) > 1:
        errors.append(f"conflicting_semantic_rules:{row_id}")
    if fixed_codes and resolved_account not in fixed_codes:
        errors.append(
            f"fixed_semantic_resolution_conflict:{row_id}:{resolved_account}:{','.join(sorted(fixed_codes))}"
        )


def _rule_specificity(rule: Mapping[str, Any]) -> int:
    line_score = 100 if str(rule.get("line_match_mode") or "all_lines") == "normalized_terms_all" else 0
    scope_score = {
        "client_counterparty": 30,
        "client_service_profile": 20,
        "client_phrase": 10,
    }.get(str(rule.get("scope") or ""), 0)
    return line_score + scope_score

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
    if (
        str(value.get("status") or "") != "active"
        or not str(value.get("rule_id") or value.get("id") or "").strip()
        or str(value.get("direction") or "").strip() not in {"purchase", "sales"}
    ):
        return False
    binding_mode = str(value.get("binding_mode") or "fixed_account").strip()
    if binding_mode == "fixed_account":
        return bool(str(value.get("account_code") or "").strip())
    if binding_mode == "semantic_role":
        return bool(
            str(value.get("semantic_role") or "").strip()
            and (
                str(value.get("semantic_intent") or "").strip()
                or str(value.get("meaning_label") or "").strip()
                or str(value.get("category") or "").strip()
                or str(value.get("reason") or "").strip()
            )
        )
    return False


def _rule_document(value: Mapping[str, Any]) -> dict[str, Any]:
    normalized_terms = [
        str(item).strip()
        for item in value.get("normalized_terms") or ()
        if str(item).strip()
    ]
    binding_mode = str(value.get("binding_mode") or "fixed_account").strip()
    account_code = str(value.get("account_code") or "").strip() if binding_mode == "fixed_account" else ""
    semantic_role = str(value.get("semantic_role") or "").strip()
    semantic_intent = str(value.get("semantic_intent") or "").strip()
    invoice_mode = str(value.get("invoice_mode") or "ordinary").strip()
    if invoice_mode not in {"ordinary", "return"}:
        invoice_mode = "ordinary"
    summary = str(
        value.get("meaning_label")
        or semantic_intent
        or value.get("reason")
        or value.get("category")
        or value.get("rule_key")
        or ""
    ).strip()
    title = str(
        value.get("meaning_label")
        or value.get("category")
        or semantic_intent
        or value.get("rule_key")
        or "Accountant-confirmed learned rule"
    ).strip()
    trigger = str(value.get("trigger_tr") or "").strip() or _fallback_trigger(value, normalized_terms)
    action = str(value.get("action_tr") or value.get("applied_effect_tr") or "").strip()
    if not action:
        if binding_mode == "fixed_account":
            action = f"Use exact account {account_code}."
        else:
            action = (
                f"Apply semantic_role={semantic_role}, semantic_intent={semantic_intent or semantic_role}; "
                "choose the exact current detail account from the current chart and invoice row."
            )
    search_terms = _unique_texts(
        [
            *normalized_terms,
            str(value.get("service_profile") or ""),
            semantic_intent,
            str(value.get("category") or ""),
            summary,
        ]
    )
    return {
        "rule_id": str(value.get("rule_id") or value.get("id") or "").strip(),
        "title": title,
        "direction": str(value.get("direction") or "").strip(),
        "invoice_mode": invoice_mode,
        "scope": str(value.get("scope") or "").strip(),
        "counterparty": str(value.get("counterparty_tax_id") or "").strip(),
        "search_terms": search_terms,
        "meaning": summary,
        "summary": summary,
        "trigger": trigger,
        "action": action,
        "guardrail": str(value.get("guardrail_tr") or "").strip(),
        "binding_mode": binding_mode,
        "line_match_mode": str(value.get("line_match_mode") or "").strip(),
        "normalized_terms": normalized_terms,
        "semantic_role": semantic_role,
        "semantic_intent": semantic_intent,
        "service_profile": str(value.get("service_profile") or "").strip(),
        "account_code": account_code,
    }


def _fallback_trigger(value: Mapping[str, Any], normalized_terms: Sequence[str]) -> str:
    parts = [f"direction={str(value.get('direction') or '').strip()}"]
    counterparty = str(value.get("counterparty_tax_id") or "").strip()
    service_profile = str(value.get("service_profile") or "").strip()
    if counterparty:
        parts.append(f"counterparty={counterparty}")
    if service_profile:
        parts.append(f"service_profile={service_profile}")
    if normalized_terms:
        parts.append("terms=" + " | ".join(normalized_terms[:4]))
    return "; ".join(part for part in parts if part and not part.endswith("="))


def _invoice_mode_from_source_package(
    source_package: Mapping[str, object],
    semantic_plan: Mapping[str, object],
) -> str:
    # Return invoices are an explicit edge case. Ordinary remains the default so existing
    # supplier-wide rules keep their current behavior when no return evidence is present.
    if str(semantic_plan.get("accounting_direction") or "").strip() == "return":
        return "return"
    for item in source_package.get("document_header") or ():
        if not isinstance(item, Mapping):
            continue
        label = normalize_text(item.get("label") or "")
        if not any(token in label for token in ("fatura tipi", "belge tipi", "invoice type", "document type")):
            continue
        value = normalize_text(item.get("value") or "")
        if "iade" in value.split() or "return" in value.split():
            return "return"
    return "ordinary"


def _search_rules(
    rules: Sequence[Mapping[str, Any]],
    *,
    query: str,
    direction: str,
    counterparty_identifier: str = "",
    result_limit: int = 100,
) -> dict[str, Any]:
    """Return boolean discovery matches without score thresholds or top-k ranking."""
    query_text = normalize_text(query)
    query_terms = {term for term in query_text.split() if term}
    counterparty_digits = "".join(character for character in counterparty_identifier if character.isdigit())
    matches: list[dict[str, Any]] = []

    for rule in rules:
        if rule.get("direction") != direction:
            continue

        declared_terms = [
            normalize_text(item)
            for item in rule.get("search_terms") or ()
            if normalize_text(item)
        ]
        searchable_parts = [
            normalize_text(rule.get("title") or ""),
            normalize_text(rule.get("meaning") or ""),
            normalize_text(rule.get("service_profile") or ""),
            *declared_terms,
        ]
        searchable_text = " ".join(part for part in searchable_parts if part)
        searchable_terms = {term for term in searchable_text.split() if term}
        rule_counterparty = "".join(
            character for character in str(rule.get("counterparty") or "") if character.isdigit()
        )

        match_classes: list[str] = []
        if counterparty_digits and rule_counterparty and counterparty_digits == rule_counterparty:
            match_classes.append("exact_counterparty")

        if query_text:
            if query_text in searchable_text:
                match_classes.append("phrase")
            if query_terms and query_terms.issubset(searchable_terms):
                match_classes.append("all_query_terms")
            if any(
                declared
                and (declared in query_text or query_text in declared)
                for declared in declared_terms
            ):
                match_classes.append("declared_term")

        if not match_classes:
            continue

        matches.append(
            {
                "rule_id": str(rule.get("rule_id") or ""),
                "title": str(rule.get("title") or ""),
                "scope": str(rule.get("scope") or ""),
                "counterparty": str(rule.get("counterparty") or ""),
                "direction": str(rule.get("direction") or ""),
                "search_terms": list(rule.get("search_terms") or ()),
                "meaning": str(rule.get("meaning") or ""),
                "service_profile": str(rule.get("service_profile") or ""),
                "binding_mode": str(rule.get("binding_mode") or "fixed_account"),
                "line_match_mode": str(rule.get("line_match_mode") or "all_lines"),
                "normalized_terms": list(rule.get("normalized_terms") or ()),
                "semantic_role": str(rule.get("semantic_role") or ""),
                "semantic_intent": str(rule.get("semantic_intent") or ""),
                "account_code": str(rule.get("account_code") or ""),
                "match_classes": list(dict.fromkeys(match_classes)),
            }
        )

    matches.sort(key=lambda item: str(item.get("rule_id") or ""))
    overflow = len(matches) > result_limit
    return {
        "query": query,
        "total_matches": len(matches),
        "overflow": overflow,
        "items": matches[:result_limit],
    }


def _candidate_catalogs(
    search_results: Mapping[str, Sequence[Mapping[str, Any]]],
) -> tuple[dict[str, list[dict[str, Any]]], dict[str, dict[str, str]]]:
    catalogs: dict[str, list[dict[str, Any]]] = {}
    ref_maps: dict[str, dict[str, str]] = {}
    for row_id, results in search_results.items():
        items_by_rule_id: dict[str, dict[str, Any]] = {}
        refs: dict[str, str] = {}
        index = 1
        for result in results:
            query = str(result.get("query") or "")
            for raw in result.get("items") or ():
                if not isinstance(raw, Mapping):
                    continue
                rule_id = str(raw.get("rule_id") or "")
                if not rule_id:
                    continue
                existing = items_by_rule_id.get(rule_id)
                if existing is not None:
                    origins = existing["discovered_by_queries"]
                    if query and query not in origins:
                        origins.append(query)
                    classes = existing["match_classes"]
                    for match_class in raw.get("match_classes") or ():
                        value = str(match_class)
                        if value and value not in classes:
                            classes.append(value)
                    continue

                candidate_ref = f"C{index}"
                index += 1
                refs[candidate_ref] = rule_id
                items_by_rule_id[rule_id] = {
                    "candidate_ref": candidate_ref,
                    "title": str(raw.get("title") or ""),
                    "scope": str(raw.get("scope") or ""),
                    "counterparty": str(raw.get("counterparty") or ""),
                    "direction": str(raw.get("direction") or ""),
                    "search_terms": list(raw.get("search_terms") or ()),
                    "meaning": str(raw.get("meaning") or ""),
                    "service_profile": str(raw.get("service_profile") or ""),
                    "binding_mode": str(raw.get("binding_mode") or "fixed_account"),
                    "line_match_mode": str(raw.get("line_match_mode") or "all_lines"),
                    "normalized_terms": list(raw.get("normalized_terms") or ()),
                    "semantic_role": str(raw.get("semantic_role") or ""),
                    "semantic_intent": str(raw.get("semantic_intent") or ""),
                    "account_code": str(raw.get("account_code") or ""),
                    "match_classes": [str(item) for item in raw.get("match_classes") or () if str(item)],
                    "discovered_by_queries": [query] if query else [],
                }
        catalogs[row_id] = list(items_by_rule_id.values())
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
