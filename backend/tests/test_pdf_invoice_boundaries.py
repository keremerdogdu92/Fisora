from __future__ import annotations

import sys
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.domain.pdf_invoice_boundaries import PdfPageText, detect_multiple_invoice_identities
from app.domain.pdf_invoices import parse_pdf_invoice
from unittest.mock import patch


def page(page_no: int, *, number: str = "", ettn: str = "", rows: int = 2) -> PdfPageText:
    identity = f"Fatura No: {number}\nETTN: {ettn}\nSatici VKN: 1234567890\nAlici VKN: 0987654321\nTarih: 01.02.2026\nOdenecek Tutar: 1.234,56 TL"
    return PdfPageText(page_no, f"{identity}\n" + "\n".join(f"Urun satiri {i}" for i in range(rows)))


class PdfInvoiceBoundaryTests(unittest.TestCase):
    def test_long_single_invoice_fixtures_are_not_split(self) -> None:
        fixtures = [
            tuple(page(index, number="ABC2026000000001", rows=30) for index in range(1, 9)),
            tuple(page(index, number="ABC2026000000002", rows=20) for index in range(1, 7)),
            tuple(page(index, number="ABC2026000000003", rows=12) for index in range(1, 5)),
            tuple(page(index, number="ABC2026000000004", rows=8) for index in range(1, 4)),
            (page(1, number="ABC2026000000005", rows=100),),
        ]
        for pages in fixtures:
            decision = detect_multiple_invoice_identities(pages)
            self.assertEqual(decision.status, "single_invoice")
            self.assertNotIn("multiple_invoice", decision.reason_codes)

    def test_two_coherent_identity_clusters_confirm_multiple(self) -> None:
        pages = (
            page(1, number="ABC2026000000001", ettn="123e4567-e89b-12d3-a456-426614174000"),
            page(2, number="ABC2026000000001", ettn="123e4567-e89b-12d3-a456-426614174000"),
            page(3, number="ABC2026000000002", ettn="123e4567-e89b-12d3-a456-426614174001"),
            page(4, number="ABC2026000000002", ettn="123e4567-e89b-12d3-a456-426614174001"),
        )
        decision = detect_multiple_invoice_identities(pages)
        self.assertEqual(decision.status, "confirmed_multiple")
        self.assertEqual(decision.identity_cluster_count, 2)
        self.assertEqual(decision.reason_codes, ("distinct_invoice_identities",))

    def test_number_like_strings_without_coherent_headers_are_insufficient(self) -> None:
        decision = detect_multiple_invoice_identities(
            (
                PdfPageText(1, "Referans ABC2026000000001 ve ABC2026000000002"),
                PdfPageText(2, "Urun satirlari ve toplamlar"),
            )
        )
        self.assertEqual(decision.status, "insufficient_identity")
        self.assertNotIn("multiple_invoice", decision.reason_codes)

    def test_parser_stops_on_confirmed_multiple_container(self) -> None:
        pages = (
            page(1, number="ABC2026000000001", ettn="123e4567-e89b-12d3-a456-426614174000"),
            page(2, number="ABC2026000000002", ettn="123e4567-e89b-12d3-a456-426614174001"),
        )
        with patch("app.domain.pdf_invoices.extract_pdf_pages", return_value=(pages, ())):
            invoice = parse_pdf_invoice(Path("combined.pdf"))

        self.assertEqual(invoice.suggested_route, "review_queue")
        self.assertIn("multi_invoice_container_confirmed", invoice.risk_flags)
        self.assertIn("separate_invoice_upload_required", invoice.parse_notes)


if __name__ == "__main__":
    unittest.main()
