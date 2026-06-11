from __future__ import annotations

from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

try:
    from fastapi.testclient import TestClient

    from app.api import phase0
    from app.main import app
except ModuleNotFoundError:
    TestClient = None
    phase0 = None
    app = None

from app.domain.tax_certificates import TaxCertificateExtraction, parse_tax_certificate_text


class TaxCertificateParserTests(unittest.TestCase):
    def test_parse_tax_certificate_text_extracts_client_fields(self) -> None:
        extraction = parse_tax_certificate_text(
            """
            T.C. GELIR IDARESI BASKANLIGI
            VERGI LEVHASI
            Adi Soyadi / Unvani
            IBRAHIM DEGERLI
            Vergi Kimlik Numarasi
            1234567890
            Bagli Oldugu Vergi Dairesi
            CEKMEKOY VERGI DAIRESI MUDURLUGU
            Ana Faaliyet Kodu ve Adi
            477401 - Belirli bir mala tahsis edilmis magazalarda isitme cihazlari satisi
            Is Yeri Adresi
            MECLIS MAH. ATATURK CAD. NO: 10 SANCAKTEPE / ISTANBUL
            Ise Baslama Tarihi
            01/01/2025
            """
        )

        self.assertEqual(extraction.title, "IBRAHIM DEGERLI")
        self.assertEqual(extraction.tax_id, "1234567890")
        self.assertEqual(extraction.tax_office, "CEKMEKOY VERGI DAIRESI MUDURLUGU")
        self.assertEqual(extraction.nace_code, "477401")
        self.assertIn("isitme cihazlari", extraction.activity_description.lower())
        self.assertEqual(extraction.workplace_addresses, ("MECLIS MAH. ATATURK CAD. NO: 10 SANCAKTEPE / ISTANBUL",))
        self.assertEqual(extraction.start_date, "01/01/2025")
        self.assertGreaterEqual(extraction.confidence, 80)

    def test_tax_certificate_parse_endpoint_returns_fields_without_storing_file(self) -> None:
        if TestClient is None or phase0 is None or app is None:
            self.skipTest("fastapi is not installed in this Python environment")

        with patch.object(
            phase0,
            "parse_tax_certificate_file",
            return_value=TaxCertificateExtraction(
                title="IBRAHIM DEGERLI",
                tax_id="1234567890",
                tax_office="CEKMEKOY VERGI DAIRESI",
                activity_description="Isitme cihazi satisi",
                nace_code="477401",
                workplace_addresses=("MECLIS MAH. ISTANBUL",),
                start_date="01/01/2025",
                confidence=92,
                extraction_notes=("pdf_text_layer",),
            ),
        ):
            response = TestClient(app).post(
                "/phase0/tax-certificate/parse",
                files={"file": ("levha.pdf", b"%PDF-1.7", "application/pdf")},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {
                "title": "IBRAHIM DEGERLI",
                "tax_id": "1234567890",
                "tax_office": "CEKMEKOY VERGI DAIRESI",
                "activity_description": "Isitme cihazi satisi",
                "nace_code": "477401",
                "workplace_addresses": ["MECLIS MAH. ISTANBUL"],
                "start_date": "01/01/2025",
                "confidence": 92,
                "extraction_notes": ["pdf_text_layer"],
            },
        )


if __name__ == "__main__":
    unittest.main()
