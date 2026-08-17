from __future__ import annotations

from pathlib import Path
import sys
import unittest


BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.domain.accounting_decision_capacity import (
    DEFAULT_DECISION_CHUNK_SIZE,
    plan_accounting_decision_chunks,
)


class AccountingDecisionCapacityV2Tests(unittest.TestCase):
    def refs(self, count: int) -> tuple[str, ...]:
        return ("counterparty", *(f"line:line-{index:03d}" for index in range(count - 1)))

    def test_nine_decisions_stay_on_provider_validated_fast_path(self) -> None:
        plan = plan_accounting_decision_chunks(self.refs(9))

        self.assertEqual(DEFAULT_DECISION_CHUNK_SIZE, 9)
        self.assertEqual(1, len(plan.chunks))
        self.assertEqual(self.refs(9), plan.chunks[0].required_decision_refs)
        self.assertFalse(plan.chunking_required)

    def test_ten_decisions_split_without_losing_or_reordering_refs(self) -> None:
        refs = self.refs(10)
        plan = plan_accounting_decision_chunks(refs)

        self.assertEqual([9, 2], [len(chunk.required_decision_refs) for chunk in plan.chunks])
        self.assertTrue(plan.chunking_required)
        self.assertEqual(refs, plan.all_required_decision_refs)
        self.assertEqual(refs[1:], tuple(
            ref
            for chunk in plan.chunks
            for ref in chunk.required_decision_refs
            if ref != "counterparty"
        ))

    def test_forty_plus_decisions_have_stable_general_chunks(self) -> None:
        refs = self.refs(43)
        forward = plan_accounting_decision_chunks(refs)
        repeated = plan_accounting_decision_chunks(refs)

        self.assertEqual([9, 9, 9, 9, 9, 3], [len(chunk.required_decision_refs) for chunk in forward.chunks])
        self.assertEqual(forward, repeated)
        self.assertEqual((0, 1, 2, 3, 4, 5), tuple(chunk.chunk_index for chunk in forward.chunks))
        self.assertEqual(len(refs), len(set(forward.all_required_decision_refs)))

    def test_duplicate_or_blank_refs_are_rejected_instead_of_silently_lost(self) -> None:
        for refs in (
            ("counterparty", "line:a", "line:a"),
            ("counterparty", ""),
            ("line:a",),
        ):
            with self.subTest(refs=refs):
                with self.assertRaises(ValueError):
                    plan_accounting_decision_chunks(refs)


if __name__ == "__main__":
    unittest.main()
