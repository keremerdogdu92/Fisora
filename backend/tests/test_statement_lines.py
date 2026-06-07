from __future__ import annotations

from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.domain.statement_lines import parse_statement_file, parse_statement_text


def simple_text_pdf_bytes(lines: list[str]) -> bytes:
    operators = []
    for index, line in enumerate(lines):
        escaped = line.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
        move = "50 760 Td" if index == 0 else "0 -16 Td"
        operators.append(f"{move} ({escaped}) Tj")
    stream = f"BT /F1 10 Tf {' '.join(operators)} ET".encode("latin-1")
    objects = [
        b"1 0 obj << /Type /Catalog /Pages 2 0 R >> endobj\n",
        b"2 0 obj << /Type /Pages /Kids [3 0 R] /Count 1 >> endobj\n",
        b"3 0 obj << /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >> endobj\n",
        b"4 0 obj << /Type /Font /Subtype /Type1 /BaseFont /Helvetica >> endobj\n",
        b"5 0 obj << /Length " + str(len(stream)).encode("ascii") + b" >> stream\n" + stream + b"\nendstream endobj\n",
    ]
    payload = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for item in objects:
        offsets.append(len(payload))
        payload.extend(item)
    xref_offset = len(payload)
    payload.extend(f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode("ascii"))
    for offset in offsets[1:]:
        payload.extend(f"{offset:010d} 00000 n \n".encode("ascii"))
    payload.extend(f"trailer << /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref_offset}\n%%EOF".encode("ascii"))
    return bytes(payload)


class StatementLineParsingTests(unittest.TestCase):
    def test_xlsx_statement_with_preamble_and_debit_credit_columns(self) -> None:
        try:
            from openpyxl import Workbook
        except ModuleNotFoundError:
            self.skipTest("openpyxl is not installed in this Python environment")

        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temp_dir:
            path = Path(temp_dir) / "ekstre.xlsx"
            workbook = Workbook()
            sheet = workbook.active
            sheet.append(["Firma", "Demo"])
            sheet.append(["Hesap hareketleri"])
            sheet.append([])
            sheet.append(["Tarih", "Açıklama", "Borç", "Alacak", "Bakiye"])
            sheet.append(["03.06.2026", "GIB ODEME", "100,00", "", "900,00"])
            sheet.append(["04.06.2026", "Musteri tahsilat", "", "250,50", "1.150,50"])
            workbook.save(path)

            lines = parse_statement_file(path)

        self.assertEqual(len(lines), 2)
        self.assertEqual(lines[0].transaction_date, "03.06.2026")
        self.assertEqual(lines[0].amount, "100.00")
        self.assertEqual(lines[0].direction, "out")
        self.assertEqual(lines[0].balance_after, "900,00")
        self.assertEqual(lines[0].transaction_type, "tax_payment")
        self.assertEqual(lines[1].amount, "250.50")
        self.assertEqual(lines[1].direction, "in")
        self.assertEqual(lines[1].balance_after, "1.150,50")

    def test_xls_text_export_skips_preamble_and_uses_debit_credit_columns(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "ekstre.xls"
            path.write_text(
                "Demo banka ekstresi\n"
                "Sube hesap hareketleri\n"
                "Tarih\tAciklama\tBorc\tAlacak\tBakiye\n"
                "03.06.2026\tSGK PRIM\t700,00 TL\t\t8.800,00 TL\n"
                "04.06.2026\tPOS TAHSILAT\t\t1.200,00 TL\t10.000,00 TL\n",
                encoding="utf-8",
            )

            lines = parse_statement_file(path)

        self.assertEqual(len(lines), 2)
        self.assertEqual(lines[0].transaction_type, "sgk_payment")
        self.assertEqual(lines[0].direction, "out")
        self.assertEqual(lines[0].amount, "700.00")
        self.assertEqual(lines[1].transaction_type, "pos_collection")
        self.assertEqual(lines[1].direction, "in")
        self.assertEqual(lines[1].amount, "1200.00")

    def test_xls_text_export_is_parsed_like_statement_rows(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "ekstre.xls"
            path.write_text(
                "transaction_date\tdescription\tamount\tdirection\tbalance_after\n"
                "2026-06-01\tGIB ODEME\t100.00\tout\t900.00\n",
                encoding="utf-8",
            )

            lines = parse_statement_file(path)

        self.assertEqual(len(lines), 1)
        self.assertEqual(lines[0].transaction_date, "2026-06-01")
        self.assertEqual(lines[0].transaction_type, "tax_payment")
        self.assertEqual(lines[0].suggested_account_code, "360")

    def test_text_pdf_statement_export_is_parsed_from_extracted_rows(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "ekstre.pdf"
            path.write_bytes(
                simple_text_pdf_bytes(
                    [
                        "transaction_date description amount direction",
                        "2026-06-01 SGK PRIM 250.00 out",
                    ]
                )
            )

            lines = parse_statement_file(path)

        self.assertEqual(len(lines), 1)
        self.assertEqual(lines[0].transaction_date, "2026-06-01")
        self.assertEqual(lines[0].transaction_type, "sgk_payment")
        self.assertEqual(lines[0].suggested_account_code, "361")

    def test_text_pdf_statement_rows_with_debit_credit_balance_are_parsed(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "ekstre.pdf"
            path.write_bytes(
                simple_text_pdf_bytes(
                    [
                        "Tarih Aciklama Borc Alacak Bakiye",
                        "03.06.2026 GIB ODEME 100,00 0,00 900,00",
                        "04.06.2026 POS TAHSILAT 0,00 1.250,75 2.150,75",
                    ]
                )
            )

            lines = parse_statement_file(path)

        self.assertEqual(len(lines), 2)
        self.assertEqual(lines[0].transaction_type, "tax_payment")
        self.assertEqual(lines[0].direction, "out")
        self.assertEqual(lines[0].amount, "100.00")
        self.assertEqual(lines[0].balance_after, "900,00")
        self.assertEqual(lines[1].transaction_type, "pos_collection")
        self.assertEqual(lines[1].direction, "in")
        self.assertEqual(lines[1].amount, "1250.75")
        self.assertEqual(lines[1].balance_after, "2.150,75")

    def test_text_pdf_statement_uses_signed_amount_before_currency_suffix(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "ekstre.pdf"
            path.write_bytes(
                simple_text_pdf_bytes(
                    [
                        "Tarih Aciklama Tutar Bakiye",
                        "19/03/2026 19:54:50 Diger OTOMATIK ODEME -3.272,55 TL 0,00",
                    ]
                )
            )

            lines = parse_statement_file(path)

        self.assertEqual(len(lines), 1)
        self.assertEqual(lines[0].transaction_date, "19/03/2026")
        self.assertEqual(lines[0].amount, "3272.55")
        self.assertEqual(lines[0].direction, "out")

    def test_rule_engine_assigns_transaction_family_account_and_review_risk(self) -> None:
        lines = parse_statement_text(
            "transaction_date,description,amount,direction,balance_after\n"
            "2026-06-01,BANKA MASRAF KOMISYON,42.50,out,9957.50\n"
            "2026-06-02,MAAS ODEMESI MAYIS,15000.00,out,-5042.50\n"
            "2026-06-03,GELEN EFT MUSTERI TAHSILATI,2500.00,in,-2542.50\n"
            "2026-06-04,KREDI TAKSIT ODEMESI,1200.00,out,-3742.50\n"
            "2026-06-05,IADE TERS KAYIT,1200.00,in,-2542.50\n"
        )

        self.assertEqual(
            [(line.transaction_type, line.suggested_account_code) for line in lines],
            [
                ("bank_fee", "780"),
                ("salary_payment", "335"),
                ("bank_transfer_in", "120"),
                ("loan_payment", "300"),
                ("refund_or_reversal", ""),
            ],
        )
        self.assertEqual(lines[0].confidence, 82)
        self.assertIn("statement_review_required", lines[0].risk_flags)
        self.assertIn("reversal_review_required", lines[4].risk_flags)


if __name__ == "__main__":
    unittest.main()
