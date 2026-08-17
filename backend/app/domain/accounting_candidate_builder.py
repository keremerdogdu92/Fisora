from __future__ import annotations

from dataclasses import dataclass, replace
from decimal import Decimal, InvalidOperation
import math
import re
from typing import Iterable, Mapping, Sequence
import unicodedata

from app.domain.chart_accounts import normalize_account_code


DEFAULT_INITIAL_CANDIDATE_LIMIT = 40
DEFAULT_EXPANSION_CANDIDATE_LIMIT = 40
_ROLE_ORDER = (
    "counterparty",
    "line_expense",
    "line_revenue",
    "vat",
    "special_tax",
)
_FALSE_STATE_VALUES = frozenset(
    {
        "",
        "0",
        "false",
        "inactive",
        "pasif",
        "disabled",
        "closed",
        "archived",
        "deleted",
        "suspended",
        "arsivlenmis",
        "silinmis",
        "askida",
        "askiya alinmis",
    }
)
_TRUE_STATE_VALUES = frozenset(
    {"1", "true", "active", "aktif", "enabled", "open", "yes", "evet"}
)


@dataclass(frozen=True)
class AccountingCandidate:
    candidate_id: str
    code: str
    name: str
    roles: tuple[str, ...]
    normalized_tax_id: str
    tax_office: str
    active: bool
    origin_round: int
    aliases: tuple[str, ...] = ()
    vat_rates: tuple[str, ...] = ()


@dataclass(frozen=True)
class AccountingCandidateCatalog:
    """Active tenant candidates plus the immutable, accumulated sent slice."""

    real_candidates: tuple[AccountingCandidate, ...]
    sent_candidates: tuple[AccountingCandidate, ...]
    initial_candidate_ids: tuple[str, ...]
    relevance_order: tuple[AccountingCandidate, ...]

    @property
    def all_candidate_ids(self) -> tuple[str, ...]:
        return tuple(item.candidate_id for item in self.real_candidates)

    @property
    def sent_candidate_ids(self) -> tuple[str, ...]:
        return tuple(item.candidate_id for item in self.sent_candidates)

    @property
    def initial_sent_slice(self) -> tuple[AccountingCandidate, ...]:
        initial_ids = frozenset(self.initial_candidate_ids)
        return tuple(
            item for item in self.sent_candidates if item.candidate_id in initial_ids
        )

    @property
    def accumulated_real_candidates(self) -> tuple[AccountingCandidate, ...]:
        return self.sent_candidates

    @property
    def universe_count(self) -> int:
        return len(self.real_candidates)

    @property
    def coverage_ratio(self) -> float:
        return (
            len(self.sent_candidates) / len(self.real_candidates)
            if self.real_candidates
            else 1.0
        )

    def candidate_by_id(self, candidate_id: str) -> AccountingCandidate:
        for candidate in (*self.sent_candidates, *self.real_candidates):
            if candidate.candidate_id == candidate_id:
                return candidate
        raise KeyError(candidate_id)

    def expansion_search(
        self,
        search_terms: Sequence[str],
        *,
        limit: int = DEFAULT_EXPANSION_CANDIDATE_LIMIT,
    ) -> tuple[AccountingCandidate, ...]:
        terms = tuple(
            (text, digits)
            for value in search_terms
            for text in (_search_key(value),)
            for digits in (_normalize_tax_id(value),)
            if text or digits
        )
        if not terms or limit <= 0:
            return ()
        sent_ids = frozenset(self.sent_candidate_ids)
        ranked = sorted(
            (
                (_match_rank(candidate, terms), candidate.code, candidate.candidate_id, candidate)
                for candidate in self.real_candidates
                if candidate.candidate_id not in sent_ids
                if _match_rank(candidate, terms) is not None
            ),
            key=lambda item: (item[0], item[1], item[2]),
        )
        return tuple(item[3] for item in ranked[:limit])

    def with_expansion(
        self,
        search_terms: Sequence[str],
        *,
        origin_round: int,
        limit: int = DEFAULT_EXPANSION_CANDIDATE_LIMIT,
    ) -> AccountingCandidateCatalog:
        if origin_round < 1 or origin_round > 2:
            raise ValueError("candidate expansion origin_round must be 1 or 2")
        sent_by_id = {item.candidate_id: item for item in self.sent_candidates}
        for candidate in self.expansion_search(search_terms, limit=limit):
            if candidate.candidate_id not in sent_by_id:
                sent_by_id[candidate.candidate_id] = replace(
                    candidate, origin_round=origin_round
                )
        return replace(self, sent_candidates=tuple(sent_by_id.values()))

    def for_round(
        self,
        round_index: int,
        *,
        search_terms: Sequence[str] = (),
    ) -> AccountingCandidateCatalog:
        if round_index not in {0, 1, 2}:
            raise ValueError("candidate round index must be 0, 1, or 2")
        if round_index == 0:
            return self
        universe_count = len(self.relevance_order)
        target = (
            min(universe_count, max(80, math.ceil(universe_count / 2)))
            if round_index == 1
            else universe_count
        )
        sent_ids = set(self.sent_candidate_ids)
        unseen = tuple(
            candidate
            for candidate in self.relevance_order
            if candidate.candidate_id not in sent_ids
        )
        terms = tuple(
            (text, digits)
            for value in search_terms
            for text in (_search_key(value),)
            for digits in (_normalize_tax_id(value),)
            if text or digits
        )
        if terms:
            unseen = tuple(
                item[3]
                for item in sorted(
                    (
                        (
                            _match_rank(candidate, terms) is None,
                            _match_rank(candidate, terms) or (9, 0),
                            candidate.code,
                            candidate,
                        )
                        for candidate in unseen
                    ),
                    key=lambda item: (item[0], item[1], item[2], item[3].candidate_id),
                )
            )
        additions = unseen[: max(0, target - len(self.sent_candidates))]
        return replace(
            self,
            sent_candidates=(
                *self.sent_candidates,
                *(replace(candidate, origin_round=round_index) for candidate in additions),
            ),
        )


def build_accounting_candidates(
    workspace: Mapping[str, object],
    projection: Mapping[str, object],
) -> AccountingCandidateCatalog:
    """Build a bounded initial slice from active, real tenant chart accounts."""

    real_candidates: list[AccountingCandidate] = []
    seen_ids: set[str] = set()
    seen_codes: set[str] = set()
    for account in sorted(_workspace_accounts(workspace), key=_raw_account_sort_key):
        if not _account_is_active(account):
            continue
        if "is_detail_account" in account and not _parse_boolean_state(
            account.get("is_detail_account"), default=False
        ):
            continue
        code = str(
            account.get("normalized_account_code")
            or account.get("raw_account_code")
            or account.get("code")
            or ""
        ).strip()
        candidate_id = str(account.get("candidate_id") or code).strip()
        code_key = normalize_account_code(code)
        if (
            not code
            or not code_key
            or not candidate_id
            or candidate_id in seen_ids
            or code_key in seen_codes
        ):
            continue
        seen_ids.add(candidate_id)
        seen_codes.add(code_key)
        name = str(account.get("account_name") or account.get("name") or "").strip()
        normalized_tax_id = _account_tax_id(account)
        tax_office = str(account.get("tax_office") or "").strip()
        aliases = _string_tuple(account.get("aliases") or account.get("account_aliases"))
        explicit_roles = _string_tuple(
            account.get("roles") or account.get("semantic_roles")
        )
        roles = _ordered_unique(
            (*explicit_roles, *_inferred_roles(code, name, normalized_tax_id, projection))
        )
        vat_rates = _account_vat_rates(account, name=name)
        real_candidates.append(
            AccountingCandidate(
                candidate_id=candidate_id,
                code=code,
                name=name,
                roles=roles,
                normalized_tax_id=normalized_tax_id,
                tax_office=tax_office,
                active=True,
                origin_round=0,
                aliases=aliases,
                vat_rates=vat_rates,
            )
        )

    counterparty_tax_id = _counterparty_tax_id(projection)
    ranked = sorted(real_candidates, key=_initial_rank)
    exact_ids = tuple(
        item.candidate_id
        for item in ranked
        if counterparty_tax_id and item.normalized_tax_id == counterparty_tax_id
    )
    initial_ids = _bounded_initial_ids(
        ranked,
        exact_ids=exact_ids,
        projection=projection,
    )
    initial_id_set = frozenset(initial_ids)
    sent_candidates = tuple(
        item for item in real_candidates if item.candidate_id in initial_id_set
    )
    sent_by_id = {item.candidate_id: item for item in sent_candidates}
    sent_candidates = tuple(sent_by_id[candidate_id] for candidate_id in initial_ids)
    relevance_by_id = {item.candidate_id: item for item in ranked}
    relevance_order = tuple(
        relevance_by_id[candidate_id]
        for candidate_id in (
            *initial_ids,
            *(
                item.candidate_id
                for item in ranked
                if item.candidate_id not in initial_id_set
            ),
        )
    )
    return AccountingCandidateCatalog(
        real_candidates=tuple(real_candidates),
        sent_candidates=sent_candidates,
        initial_candidate_ids=initial_ids,
        relevance_order=relevance_order,
    )


def _workspace_accounts(
    workspace: Mapping[str, object],
) -> tuple[Mapping[str, object], ...]:
    chart = workspace.get("chart_accounts")
    chart_mapping = chart if isinstance(chart, Mapping) else {}
    raw_accounts = chart_mapping.get("accounts") or workspace.get("accounts") or ()
    if not isinstance(raw_accounts, Sequence) or isinstance(raw_accounts, (str, bytes)):
        return ()
    return tuple(item for item in raw_accounts if isinstance(item, Mapping))


def _account_is_active(account: Mapping[str, object]) -> bool:
    if "is_active" in account:
        return _parse_boolean_state(account.get("is_active"), default=False)
    if "active" in account:
        return _parse_boolean_state(account.get("active"), default=False)
    if "status" not in account:
        return True
    status = _search_key(account.get("status"))
    if status in _FALSE_STATE_VALUES or status == "passive":
        return False
    return True


def _parse_boolean_state(value: object, *, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    normalized = _search_key(value)
    if normalized in _FALSE_STATE_VALUES:
        return False
    if normalized in _TRUE_STATE_VALUES:
        return True
    return default


def _account_tax_id(account: Mapping[str, object]) -> str:
    for key in (
        "normalized_tax_id",
        "tax_id",
        "vkn",
        "tckn",
        "tax_identifier",
        "vergi_no",
    ):
        normalized = _normalize_tax_id(account.get(key))
        if normalized:
            return normalized
    return ""


def _raw_account_sort_key(
    account: Mapping[str, object],
) -> tuple[str, int, str, str]:
    code = str(
        account.get("normalized_account_code")
        or account.get("raw_account_code")
        or account.get("code")
        or ""
    ).strip()
    candidate_id = str(account.get("candidate_id") or code).strip()
    normalized_code = normalize_account_code(code)
    return normalized_code, int(code != normalized_code), candidate_id, code


def _counterparty_tax_id(projection: Mapping[str, object]) -> str:
    direction = str(projection.get("document_direction") or "purchase").strip().lower()
    party_key = "customer_party" if direction == "sales" else "supplier_party"
    party = projection.get(party_key)
    party_mapping = party if isinstance(party, Mapping) else {}
    return _normalize_tax_id(
        party_mapping.get("normalized_tax_id") or party_mapping.get("tax_id")
    )


def _inferred_roles(
    code: str,
    name: str,
    normalized_tax_id: str,
    projection: Mapping[str, object],
) -> tuple[str, ...]:
    direction = str(projection.get("document_direction") or "purchase").strip().lower()
    text = _search_key(f"{code} {name}")
    roles: list[str] = []
    if normalized_tax_id and normalized_tax_id == _counterparty_tax_id(projection):
        roles.append("counterparty")
    if direction == "sales":
        if code.startswith("6") or "satis" in text or "gelir" in text:
            roles.append("line_revenue")
        if code.startswith("391") or "hesaplanan kdv" in text:
            roles.append("vat")
        if code.startswith("120"):
            roles.append("counterparty")
    else:
        if code.startswith(("15", "25", "7", "689")) or any(
            value in text for value in ("gider", "maliyet", "demirbas")
        ):
            roles.append("line_expense")
        if code.startswith("191") or "indirilecek kdv" in text:
            roles.append("vat")
        if code.startswith("320"):
            roles.append("counterparty")
    return _ordered_unique(roles)


def _bounded_initial_ids(
    ranked: Sequence[AccountingCandidate],
    *,
    exact_ids: Sequence[str],
    projection: Mapping[str, object],
) -> tuple[str, ...]:
    selected: list[str] = []
    for candidate_id in exact_ids:
        if candidate_id not in selected:
            selected.append(candidate_id)
        if len(selected) == DEFAULT_INITIAL_CANDIDATE_LIMIT:
            return tuple(selected)

    for vat_rate in _required_vat_rates(projection):
        match = next(
            (
                candidate
                for candidate in ranked
                if "vat" in candidate.roles
                and vat_rate in candidate.vat_rates
                and candidate.candidate_id not in selected
            ),
            None,
        )
        if match is not None:
            selected.append(match.candidate_id)
        if len(selected) == DEFAULT_INITIAL_CANDIDATE_LIMIT:
            return tuple(selected)

    for terms in _required_special_tax_terms(projection):
        match = next(
            (
                candidate
                for candidate in ranked
                if "special_tax" in candidate.roles
                and candidate.candidate_id not in selected
                and _candidate_matches_terms(candidate, terms)
            ),
            None,
        )
        if match is not None:
            selected.append(match.candidate_id)
        if len(selected) == DEFAULT_INITIAL_CANDIDATE_LIMIT:
            return tuple(selected)

    for role in _ROLE_ORDER:
        match = next(
            (
                candidate
                for candidate in ranked
                if role in candidate.roles and candidate.candidate_id not in selected
            ),
            None,
        )
        if match is not None:
            selected.append(match.candidate_id)
        if len(selected) == DEFAULT_INITIAL_CANDIDATE_LIMIT:
            return tuple(selected)

    role_queues = {
        role: tuple(candidate for candidate in ranked if role in candidate.roles)
        for role in _ROLE_ORDER
    }
    while len(selected) < DEFAULT_INITIAL_CANDIDATE_LIMIT:
        added = False
        for role in _ROLE_ORDER:
            match = next(
                (
                    candidate
                    for candidate in role_queues[role]
                    if candidate.candidate_id not in selected
                ),
                None,
            )
            if match is None:
                continue
            selected.append(match.candidate_id)
            added = True
            if len(selected) == DEFAULT_INITIAL_CANDIDATE_LIMIT:
                return tuple(selected)
        if not added:
            break

    for candidate in ranked:
        if candidate.candidate_id in selected:
            continue
        selected.append(candidate.candidate_id)
        if len(selected) == DEFAULT_INITIAL_CANDIDATE_LIMIT:
            break
    return tuple(selected)


def _account_vat_rates(
    account: Mapping[str, object],
    *,
    name: str,
) -> tuple[str, ...]:
    raw_values: list[object] = []
    for key in ("vat_rate", "vat_rates", "tax_rate", "kdv_rate"):
        value = account.get(key)
        if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
            raw_values.extend(value)
        elif value not in (None, ""):
            raw_values.append(value)
    label = _search_key(name)
    raw_values.extend(
        match.group(1)
        for match in re.finditer(
            r"(?:%|yuzde|kdv)\s*(\d+(?:[.,]\d+)?)",
            label,
        )
    )
    return _ordered_unique(
        rate
        for value in raw_values
        for rate in (_normalized_rate(value),)
        if rate
    )


def _required_vat_rates(projection: Mapping[str, object]) -> tuple[str, ...]:
    raw_groups = projection.get("vat_summary") or ()
    groups = (
        raw_groups
        if isinstance(raw_groups, Sequence) and not isinstance(raw_groups, (str, bytes))
        else ()
    )
    return _ordered_unique(
        rate
        for item in groups
        if isinstance(item, Mapping)
        for rate in (_normalized_rate(item.get("rate")),)
        if rate
    )


def _normalized_rate(value: object) -> str:
    text = str(value or "").strip().replace("%", "").replace(",", ".")
    if not text:
        return ""
    try:
        parsed = Decimal(text)
    except InvalidOperation:
        return ""
    if parsed < 0:
        return ""
    return format(parsed.normalize(), "f")


def _required_special_tax_terms(
    projection: Mapping[str, object],
) -> tuple[tuple[str, ...], ...]:
    raw_components = projection.get("tax_components") or ()
    components = (
        raw_components
        if isinstance(raw_components, Sequence)
        and not isinstance(raw_components, (str, bytes))
        else ()
    )
    terms: list[tuple[str, ...]] = []
    for item in components:
        if not isinstance(item, Mapping):
            continue
        kind = _search_key(item.get("canonical_tax_kind"))
        component_type = _search_key(item.get("component_type"))
        if kind == "vat" or component_type == "vat":
            continue
        values = _ordered_unique(
            token
            for value in (
                item.get("source_label"),
                item.get("canonical_tax_kind"),
                item.get("component_type"),
                item.get("source_code"),
            )
            for token in _search_key(value).split()
            if len(token) >= 2
        )
        if values and values not in terms:
            terms.append(values)
    return tuple(terms)


def _candidate_matches_terms(
    candidate: AccountingCandidate,
    terms: Sequence[str],
) -> bool:
    searchable = _search_key(
        " ".join((candidate.code, candidate.name, *candidate.aliases))
    )
    return any(term in searchable for term in terms)


def _initial_rank(candidate: AccountingCandidate) -> tuple[int, int, str]:
    role_rank = min(
        (_ROLE_ORDER.index(role) for role in candidate.roles if role in _ROLE_ORDER),
        default=len(_ROLE_ORDER),
    )
    code_priority = (
        3
        if candidate.code.startswith("770")
        else 2
        if candidate.code.startswith(("600", "191", "391", "320", "120", "360"))
        else 1
        if candidate.code.startswith(("15", "25", "7"))
        else 0
    )
    return role_rank, -code_priority, candidate.code


def _match_rank(
    candidate: AccountingCandidate,
    terms: Sequence[tuple[str, str]],
) -> tuple[int, int] | None:
    searchable = _search_key(
        " ".join(
            (
                candidate.normalized_tax_id,
                " ".join(candidate.roles),
                " ".join(candidate.aliases),
                candidate.code,
                re.sub(r"\W+", "", candidate.code),
                candidate.name,
                candidate.tax_office,
            )
        )
    )
    hits = tuple(
        text
        for text, digits in terms
        if text in searchable or (digits and digits in candidate.normalized_tax_id)
    )
    if not hits:
        return None
    exact_tax_id = int(
        not any(
            digits and digits == candidate.normalized_tax_id
            for _, digits in terms
        )
    )
    return exact_tax_id, -sum(len(term) for term in hits)


def _normalize_tax_id(value: object) -> str:
    return re.sub(r"\D+", "", str(value or ""))


def _search_key(value: object) -> str:
    folded = unicodedata.normalize("NFKD", str(value or ""))
    return " ".join(
        "".join(character for character in folded if not unicodedata.combining(character))
        .casefold()
        .replace("ı", "i")
        .split()
    )


def _string_tuple(value: object) -> tuple[str, ...]:
    if isinstance(value, str):
        return (value.strip(),) if value.strip() else ()
    if not isinstance(value, Sequence) or isinstance(value, bytes):
        return ()
    return _ordered_unique(str(item).strip() for item in value if str(item).strip())


def _ordered_unique(values: Iterable[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(values))
