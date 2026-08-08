from __future__ import annotations

from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.domain.matching_simulation import _accountant_action_hint
from app.domain.utility_invoice_markers import detect_utility_invoice_markers, utility_exception_requires_review


class UtilityInvoiceMarkerTests(unittest.TestCase):
    def test_detects_explicit_device_line_without_flagging_normal_service_lines(self) -> None:
        markers = detect_utility_invoice_markers(
            service_profile="gsm_communication",
            source="xml",
            line_descriptions=("Aylik mobil haberlesme bedeli", "iPhone 16 Pro cihaz bedeli"),
        )

        self.assertEqual(markers, ("utility_device_line",))

    def test_detects_explicit_installment_line_only_for_ubl(self) -> None:
        self.assertEqual(
            detect_utility_invoice_markers(
                service_profile="fixed_internet",
                source="xml",
                line_descriptions=("Modem taksit 3/12",),
            ),
            ("utility_installment_line",),
        )
        self.assertEqual(
            detect_utility_invoice_markers(
                service_profile="fixed_internet",
                source="pdf",
                line_descriptions=("Modem taksit 3/12",),
            ),
            (),
        )

    def test_device_and_installment_markers_are_informational_not_review_blockers(self) -> None:
        self.assertFalse(utility_exception_requires_review(("utility_device_line",), has_profile_authority=False))
        self.assertFalse(utility_exception_requires_review(("utility_device_line",), has_profile_authority=True))

    def test_zero_payable_action_explains_no_posting_to_accountant(self) -> None:
        hint = _accountant_action_hint(
            export_status="review_required",
            blockers=("zero_payable_no_posting",),
            draft_lines=(),
        )

        self.assertEqual(
            hint,
            "Ödenecek tutar 0,00 TL; fatura tamamen indirimle kapandığı için yevmiye kaydı oluşturulmayacak.",
        )


if __name__ == "__main__":
    unittest.main()
