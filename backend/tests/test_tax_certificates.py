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

from app.domain.business_relevance import ActivityProfile
from app.domain.tax_certificates import TaxCertificateExtraction, ocr_image, parse_tax_certificate_text


class FakeCompletedProcess:
    def __init__(self, stdout: str, returncode: int = 0) -> None:
        self.stdout = stdout
        self.returncode = returncode


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
        self.assertIn("hearing_aid", extraction.activity_tags)
        self.assertIn("medical_retail", extraction.activity_tags)
        self.assertEqual(extraction.activity_profile.primary_activity, "hearing_aid_sales_service")
        self.assertFalse(extraction.activity_profile.needs_review)

    def test_ocr_image_prefers_page_segmentation_that_extracts_tax_certificate_fields(self) -> None:
        bad_rotated_output = "—— I | = I | — I | TT —— I | —— = — I"
        readable_output = """
        MÜKELLEFİN VERGİ LEVHASI
        ADI SOYADI İBRAHİM DEĞERLİ
        VERGİ KİMLİK NO 38119521000
        VERGİ DAİRESİ ESENYURT
        İŞ YERİ ADRESİ BAĞLARÇEŞME MAH. ONDOKUZ MAYIS BLV. MG PLAZA NO: 20/10 ESENYURT/ İSTANBUL
        İŞE BAŞLAMA TARİHİ 12.06.2024
        ANA FAALİYET KODU VE ADI 477401-TIBBİ VE ORTOPEDİK ÜRÜNLERİN PERAKENDE TİCARETİ
        """

        def fake_run(command, **_kwargs):
            psm = command[command.index("--psm") + 1]
            return FakeCompletedProcess(readable_output if psm == "1" else bad_rotated_output)

        with patch("app.domain.tax_certificates.shutil.which", return_value="/usr/bin/tesseract"):
            with patch("app.domain.tax_certificates.subprocess.run", side_effect=fake_run):
                text, notes = ocr_image(Path("rotated-tax-certificate.png"))

        self.assertIn("İBRAHİM DEĞERLİ", text)
        self.assertIn("ocr_tesseract_psm_1", notes)

    def test_parse_tax_certificate_text_handles_compact_gib_ocr_layout(self) -> None:
        extraction = parse_tax_certificate_text(
            """
            MÜKELLEFİN VERGİ LEVHASI
            ADI SOYADI İBRAHİM DEĞERLİ ESENYURT
            VERGİ DAİRESİ
            TİCARET ÜNVANI VERGİ KİMLİK
            NO
            TC KİMLİK NO 38119521000
            İŞ YERİ ADRESİ
            BAĞLARÇEŞME MAH. ONDOKUZ MAYIS BLV. MG PLAZA NO:
            38119521000
            20/10 ESENYURT/ İSTANBUL
            İŞE BAŞLAMA TARİHİ 12.06.2024
            ANA FAALİYET
            KODU VE ADI
            477401-TIBBİ VE ORTOPEDİK ÜRÜNLERİN PERAKENDE TİCARETİ
            """
        )

        self.assertIn("İBRAHİM DEĞERLİ", extraction.title)
        self.assertEqual(extraction.tax_id, "38119521000")
        self.assertEqual(extraction.nace_code, "477401")
        self.assertIn("ORTOPEDİK ÜRÜNLERİN PERAKENDE TİCARETİ", extraction.activity_description)
        self.assertIn("BAĞLARÇEŞME MAH.", extraction.workplace_addresses[0])
        self.assertEqual(extraction.start_date, "12.06.2024")
        self.assertGreaterEqual(extraction.confidence, 75)

    def test_parse_tax_certificate_text_separates_gib_column_identity_fields(self) -> None:
        extraction = parse_tax_certificate_text(
            """
            VERGI LEVHASI
            ADI SOYADI
            TICARET UNVANI
            IS YERI ADRESI
            VERGI TURU
            VERGI DAIRESI
            VERGI KIMLIK NO
            TC KIMLIK NO
            FAALIYET KODU VE ADI
            15/02/2021
            477401 - TIBBI VE ORTOPEDIK URUNLERIN PERAKENDE TICARETI
            30052309394
            MASLAK VERGI DAIRESI MUD.
            YILLIK GELIR VERGISI
            SULTAN SELIM MAH. HUMEYRA SK. NO: 7/10 KAGITHANE / ISTANBUL
            ORHAN ELIBOL
            """
        )

        self.assertEqual(extraction.title, "ORHAN ELIBOL")
        self.assertEqual(extraction.legal_name, "ORHAN ELIBOL")
        self.assertEqual(extraction.display_title, "ORHAN ELIBOL")
        self.assertEqual(extraction.tckn, "30052309394")
        self.assertEqual(extraction.vkn, "")
        self.assertEqual(extraction.identity_type, "tckn")
        self.assertEqual(extraction.tax_identifier, "30052309394")
        self.assertEqual(extraction.tax_id, "30052309394")
        self.assertEqual(extraction.tax_office, "MASLAK VERGI DAIRESI MUD.")
        self.assertEqual(extraction.workplace_addresses, ("SULTAN SELIM MAH. HUMEYRA SK. NO: 7/10 KAGITHANE / ISTANBUL",))
        self.assertEqual(extraction.nace_code, "477401")

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
                activity_tags=("hearing_aid", "medical_retail", "retail_trade"),
                activity_profile=ActivityProfile(
                    primary_activity="hearing_aid_sales_service",
                    display_label="Isitme cihazi satis/servis",
                    activity_tags=("hearing_aid", "medical_retail", "retail_trade"),
                    nace_family="retail_trade",
                    relevance_hints=("isitme_cihazi", "isitme_cihazi_pili", "medikal_sarf"),
                    confidence=90,
                    needs_review=False,
                ),
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
                "tckn": "",
                "vkn": "1234567890",
                "identity_type": "vkn",
                "tax_identifier": "1234567890",
                "legal_name": "IBRAHIM DEGERLI",
                "trade_name": "",
                "display_title": "IBRAHIM DEGERLI",
                "tax_office": "CEKMEKOY VERGI DAIRESI",
                "activity_description": "Isitme cihazi satisi",
                "nace_code": "477401",
                "workplace_addresses": ["MECLIS MAH. ISTANBUL"],
                "start_date": "01/01/2025",
                "activity_tags": ["hearing_aid", "medical_retail", "retail_trade"],
                "activity_profile": {
                    "primary_activity": "hearing_aid_sales_service",
                    "display_label": "Isitme cihazi satis/servis",
                    "activity_tags": ["hearing_aid", "medical_retail", "retail_trade"],
                    "nace_family": "retail_trade",
                    "relevance_hints": ["isitme_cihazi", "isitme_cihazi_pili", "medikal_sarf"],
                    "confidence": 90,
                    "needs_review": False,
                },
                "confidence": 92,
                "extraction_notes": ["pdf_text_layer"],
            },
        )

    def test_parse_tax_certificate_text_prefers_commercial_title_value(self) -> None:
        extraction = parse_tax_certificate_text(
            """
            MUKELLEFIN VERGI LEVHASI
            TICARI UNVANI
            ABC ISITME CIHAZLARI LIMITED SIRKETI
            VERGI KIMLIK NO
            1234567890
            ANA FAALIYET KODU VE ADI
            477401-TIBBI VE ORTOPEDIK URUNLERIN PERAKENDE TICARETI
            """
        )

        self.assertEqual(extraction.title, "ABC ISITME CIHAZLARI LIMITED SIRKETI")


if __name__ == "__main__":
    unittest.main()
