from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence


DEFAULT_DECISION_CHUNK_SIZE = 9


@dataclass(frozen=True)
class AccountingDecisionChunk:
    chunk_index: int
    required_decision_refs: tuple[str, ...]


@dataclass(frozen=True)
class AccountingDecisionCapacityPlan:
    all_required_decision_refs: tuple[str, ...]
    chunks: tuple[AccountingDecisionChunk, ...]
    chunk_size: int

    @property
    def chunking_required(self) -> bool:
        return len(self.chunks) > 1


def plan_accounting_decision_chunks(
    required_decision_refs: Sequence[str],
    *,
    chunk_size: int = DEFAULT_DECISION_CHUNK_SIZE,
) -> AccountingDecisionCapacityPlan:
    """Split accounting decisions without dropping or reordering invoice facts.

    Counterparty context is repeated in every provider call, while every other
    decision reference belongs to exactly one stable chunk.
    """

    if not isinstance(chunk_size, int) or chunk_size < 2:
        raise ValueError("accounting decision chunk_size must be at least 2")
    refs = tuple(str(value).strip() for value in required_decision_refs)
    if not refs or refs[0] != "counterparty":
        raise ValueError("accounting decision refs must start with counterparty")
    if any(not value for value in refs):
        raise ValueError("accounting decision refs cannot be blank")
    if len(set(refs)) != len(refs):
        raise ValueError("accounting decision refs must be unique")

    fact_capacity = chunk_size - 1
    fact_refs = refs[1:]
    chunks = tuple(
        AccountingDecisionChunk(
            chunk_index=index,
            required_decision_refs=("counterparty", *fact_refs[offset : offset + fact_capacity]),
        )
        for index, offset in enumerate(range(0, max(1, len(fact_refs)), fact_capacity))
    )
    return AccountingDecisionCapacityPlan(
        all_required_decision_refs=refs,
        chunks=chunks,
        chunk_size=chunk_size,
    )
