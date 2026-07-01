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
from app.domain.tax_certificates import (
    TaxCertificateExtraction,
    merge_tax_certificate_extractions,
    ocr_image,
    parse_tax_certificate_file,
    parse_tax_certificate_text,
)


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

    def test_parse_tax_certificate_text_handles_grid_layout_with_separate_tckn_and_vkn(self) -> None:
        extraction = parse_tax_certificate_text(
            """
            VERGI LEVHASI
            ADI SOYADI
            TICARET UNVANI
            IS YERI ADRESI
            VERGI TURU
            VERGI
            DAIRESI
            VERGI KIMLIK
            NO
            TC KIMLIK NO
            ISE BASLAMA
            TARIHI
            ANA FAALIYET
            KODU VE ADI
            MUKELLEFIN
            OMER YAGCI
            FEYZULLAH MAH. BAGDAT CAD. NO: 336 -338F MALTEPE/ ISTANBUL
            YILLIK GELIR VERGISI
            KUCUKYALI
            9270740926
            45661316282
            04.01.2023
            477401-TIBBI VE ORTOPEDIK URUNLERIN PERAKENDE TICARETI
            """
        )

        self.assertEqual(extraction.legal_name, "OMER YAGCI")
        self.assertEqual(extraction.trade_name, "")
        self.assertEqual(extraction.display_title, "OMER YAGCI")
        self.assertEqual(extraction.title, "OMER YAGCI")
        self.assertEqual(extraction.vkn, "9270740926")
        self.assertEqual(extraction.tckn, "45661316282")
        self.assertEqual(extraction.tax_identifier, "9270740926")
        self.assertEqual(extraction.tax_id, "9270740926")
        self.assertEqual(extraction.identity_type, "tckn_vkn")
        self.assertEqual(extraction.tax_office, "KUCUKYALI")
        self.assertEqual(
            extraction.workplace_addresses,
            ("FEYZULLAH MAH. BAGDAT CAD. NO: 336 -338F MALTEPE/ ISTANBUL",),
        )
        self.assertEqual(extraction.start_date, "04.01.2023")
        self.assertEqual(extraction.nace_code, "477401")

    def test_parse_tax_certificate_text_handles_rana_grid_layout_without_label_leakage(self) -> None:
        extraction = parse_tax_certificate_text(
            """
            VERGI LEVHASI
            ADI SOYADI
            TICARET UNVANI
            IS YERI ADRESI
            VERGI TURU
            VERGI
            DAIRESI
            VERGI KIMLIK
            NO
            TC KIMLIK NO
            ISE BASLAMA
            TARIHI
            ANA FAALIYET
            KODU VE ADI
            MUKELLEFIN
            RANAMED MEDIKAL TIBBI MALZEME URUNLERI SANAYI VE TICARET LIMITED SIRKETI
            KAZIM KARABEKIR MAH. ADEM YAVUZ CAD. NO: 22 IC KAPI NO: 2 UMRANIYE / ISTANBUL
            KURUMLAR VERGISI
            UMRANIYE
            7342497874
            01.09.2022
            464601-CERRAHI, TIBBI VE ORTOPEDIK ALET VE CIHAZLARIN TOPTAN TICARETI
            """
        )

        self.assertEqual(extraction.title, "RANAMED MEDIKAL TIBBI MALZEME URUNLERI SANAYI VE TICARET LIMITED SIRKETI")
        self.assertEqual(extraction.legal_name, "RANAMED MEDIKAL TIBBI MALZEME URUNLERI SANAYI VE TICARET LIMITED SIRKETI")
        self.assertEqual(extraction.vkn, "7342497874")
        self.assertEqual(extraction.tckn, "")
        self.assertEqual(extraction.tax_office, "UMRANIYE")
        self.assertEqual(extraction.nace_code, "464601")
        self.assertEqual(extraction.activity_description, "CERRAHI, TIBBI VE ORTOPEDIK ALET VE CIHAZLARIN TOPTAN TICARETI")
        self.assertEqual(
            extraction.workplace_addresses,
            ("KAZIM KARABEKIR MAH. ADEM YAVUZ CAD. NO: 22 IC KAPI NO: 2 UMRANIYE / ISTANBUL",),
        )
        self.assertEqual(extraction.start_date, "01.09.2022")

    def test_parse_tax_certificate_text_rejects_label_fragments_as_values(self) -> None:
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
            ANA FAALIYET KODU VE ADI
            MUKELLEFIN
            VE ADLARI
            TCKN
            DAIRESI
            SIRKETI NO 7342497874
            RANAMED MEDIKAL TIBBI MALZEME URUNLERI SANAYI VE TICARET LIMITED SIRKETI
            KAZIM KARABEKIR MAH. ADEM YAVUZ CAD. NO: 22 IC KAPI NO: 2 UMRANIYE / ISTANBUL
            KURUMLAR VERGISI
            UMRANIYE
            7342497874
            464601-CERRAHI, TIBBI VE ORTOPEDIK ALET VE CIHAZLARIN TOPTAN TICARETI
            """
        )

        self.assertNotIn(extraction.title, {"VE ADLARI", "TCKN", "DAIRESI", "SIRKETI NO 7342497874"})
        self.assertEqual(extraction.title, "RANAMED MEDIKAL TIBBI MALZEME URUNLERI SANAYI VE TICARET LIMITED SIRKETI")
        self.assertEqual(extraction.tax_office, "UMRANIYE")

    def test_parse_tax_certificate_text_prefers_trade_name_for_display_but_keeps_legal_name(self) -> None:
        extraction = parse_tax_certificate_text(
            """
            VERGI LEVHASI
            ADI SOYADI
            AYSE YILMAZ
            TICARET UNVANI
            AYSE YILMAZ ISITME CIHAZLARI
            VERGI KIMLIK NO
            1234567890
            TC KIMLIK NO
            12345678901
            """
        )

        self.assertEqual(extraction.legal_name, "AYSE YILMAZ")
        self.assertEqual(extraction.trade_name, "AYSE YILMAZ ISITME CIHAZLARI")
        self.assertEqual(extraction.display_title, "AYSE YILMAZ ISITME CIHAZLARI")
        self.assertEqual(extraction.title, "AYSE YILMAZ ISITME CIHAZLARI")

    def test_parse_tax_certificate_file_supplements_missing_identity_from_pdf_ocr(self) -> None:
        text_layer = """
        VERGI LEVHASI
        ADI SOYADI
        TICARET UNVANI
        IS YERI ADRESI
        VERGI TURU
        VERGI
        DAIRESI
        VERGI KIMLIK
        NO
        TC KIMLIK NO
        ISE BASLAMA
        TARIHI
        ANA FAALIYET
        KODU VE ADI
        MUKELLEFIN
        OMER YAGCI
        FEYZULLAH MAH. BAGDAT CAD. NO: 336 -338F MALTEPE/ ISTANBUL
        YILLIK GELIR VERGISI
        KUCUKYALI
        04.01.2023
        477401-TIBBI VE ORTOPEDIK URUNLERIN PERAKENDE TICARETI
        """
        ocr_layer = f"{text_layer}\n45661316282\n9270740926\n"

        with patch("app.domain.tax_certificates.extract_pdf_text", return_value=(1, text_layer, ("pdf_text_layer",))):
            with patch("app.domain.tax_certificates.ocr_pdf", return_value=(ocr_layer, ("ocr_pdf_rendered", "ocr_tesseract"))):
                extraction = parse_tax_certificate_file(Path("omer-vergi-levhasi.pdf"))

        self.assertEqual(extraction.tckn, "45661316282")
        self.assertEqual(extraction.vkn, "9270740926")
        self.assertEqual(extraction.tax_identifier, "9270740926")
        self.assertIn("ocr_pdf_rendered", extraction.extraction_notes)

    def test_parse_tax_certificate_file_skips_full_ocr_when_text_layer_has_tckn_and_core_fields(self) -> None:
        text_layer = """
        VERGI LEVHASI
        ADI SOYADI
        MUHAMMET YAKUP DELI
        IS YERI ADRESI
        FATIH / ISTANBUL
        VERGI DAIRESI
        FATIH
        TC KIMLIK NO
        21106530840
        ANA FAALIYET KODU VE ADI
        477401-TIBBI VE ORTOPEDIK URUNLERIN PERAKENDE TICARETI
        """

        with patch("app.domain.tax_certificates.extract_pdf_text", return_value=(1, text_layer, ("pdf_text_layer",))):
            with patch("app.domain.tax_certificates.ocr_pdf") as ocr_pdf:
                extraction = parse_tax_certificate_file(Path("muhammed-yakup-vergi-levhasi.pdf"))

        ocr_pdf.assert_not_called()
        self.assertEqual(extraction.tckn, "21106530840")
        self.assertEqual(extraction.vkn, "")
        self.assertEqual(extraction.nace_code, "477401")
        self.assertFalse(extraction.processing_metrics["used_ocr"])

    def test_parse_tax_certificate_file_uses_identity_roi_before_full_ocr(self) -> None:
        text_layer = """
        VERGI LEVHASI
        TICARET UNVANI
        GKN GIG ISITME CIHAZLARI SANAYI VE TICARET LIMITED SIRKETI
        VERGI DAIRESI
        GOZTEPE
        ANA FAALIYET KODU VE ADI
        477401-TIBBI VE ORTOPEDIK URUNLERIN PERAKENDE TICARETI
        """

        with patch("app.domain.tax_certificates.extract_pdf_text", return_value=(1, text_layer, ("pdf_text_layer",))):
            with patch(
                "app.domain.tax_certificates.ocr_pdf_identity_region",
                return_value=("3961668006", ("ocr_pdf_identity_rendered", "ocr_tesseract", "ocr_attempts_1")),
                create=True,
            ):
                with patch("app.domain.tax_certificates.ocr_pdf") as ocr_pdf:
                    extraction = parse_tax_certificate_file(Path("gkn-vergi-levhasi.pdf"))

        ocr_pdf.assert_not_called()
        self.assertEqual(extraction.vkn, "3961668006")
        self.assertNotEqual(extraction.trade_name, "3961668006")
        self.assertTrue(extraction.processing_metrics["used_ocr"])
        self.assertEqual(extraction.processing_metrics["ocr_attempts"], 1)

    def test_merge_tax_certificate_extractions_keeps_clean_primary_names(self) -> None:
        text_layer = parse_tax_certificate_text(
            """
            VERGI LEVHASI
            ADI SOYADI
            OMER YAGCI
            VERGI DAIRESI
            KUCUKYALI
            TC KIMLIK NO
            45661316282
            ANA FAALIYET KODU VE ADI
            477401-TIBBI VE ORTOPEDIK URUNLERIN PERAKENDE TICARETI
            """
        )
        ocr_layer = TaxCertificateExtraction(
            title="OMER YAGCI",
            legal_name="OMER YAGCI",
            trade_name="9270740926",
            vkn="9270740926",
            tckn="45661316282",
            tax_office="KUCUKYALI",
            nace_code="477401",
            activity_description="TIBBI VE ORTOPEDIK URUNLERIN PERAKENDE TICARETI",
            confidence=100,
        )

        extraction = merge_tax_certificate_extractions(text_layer, ocr_layer)

        self.assertEqual(extraction.vkn, "9270740926")
        self.assertEqual(extraction.tckn, "45661316282")
        self.assertEqual(extraction.trade_name, "")
        self.assertEqual(extraction.legal_name, "OMER YAGCI")

    def test_parse_tax_certificate_text_rejects_identity_label_as_legal_name(self) -> None:
        extraction = parse_tax_certificate_text(
            """
            VERGI LEVHASI
            ADI SOYADI
            . . . oo TC KIMLIK NO
            TICARET UNVANI
            BUNYAMIN AKTAR MECIDIYEKOY
            TC KIMLIK NO
            10649861252
            ANA FAALIYET KODU VE ADI
            471101-BAKKAL VE MARKETLERDE YAPILAN PERAKENDE TICARET
            """
        )

        self.assertEqual(extraction.title, "BUNYAMIN AKTAR MECIDIYEKOY")
        self.assertEqual(extraction.legal_name, "BUNYAMIN AKTAR MECIDIYEKOY")

    def test_parse_tax_certificate_file_keeps_text_layer_without_ocr_when_critical_fields_exist(self) -> None:
        text_layer = """
        VERGI LEVHASI
        ADI SOYADI
        TICARET UNVANI
        IS YERI ADRESI
        VERGI TURU
        VERGI
        DAIRESI
        VERGI KIMLIK
        NO
        TC KIMLIK NO
        ISE BASLAMA
        TARIHI
        ANA FAALIYET
        KODU VE ADI
        MUKELLEFIN
        RANAMED MEDIKAL TIBBI MALZEME URUNLERI SANAYI VE TICARET LIMITED SIRKETI
        KAZIM KARABEKIR MAH. ADEM YAVUZ CAD. NO: 22 IC KAPI NO: 2 UMRANIYE / ISTANBUL
        KURUMLAR VERGISI
        UMRANIYE
        7342497874
        01.09.2022
        464601-CERRAHI, TIBBI VE ORTOPEDIK ALET VE CIHAZLARIN TOPTAN TICARETI
        """

        with patch("app.domain.tax_certificates.extract_pdf_text", return_value=(1, text_layer, ("pdf_text_layer",))):
            with patch("app.domain.tax_certificates.ocr_pdf") as ocr_pdf:
                extraction = parse_tax_certificate_file(Path("rana-vergi-levhasi.pdf"))

        ocr_pdf.assert_not_called()
        self.assertEqual(extraction.vkn, "7342497874")
        self.assertEqual(extraction.nace_code, "464601")
        self.assertFalse(extraction.processing_metrics["used_ocr"])
        self.assertTrue(extraction.processing_metrics["used_text_layer"])

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
                "processing_metrics": {},
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

    def test_ocr_image_stops_after_high_quality_first_page_segmentation(self) -> None:
        readable_output = """
        VERGI LEVHASI
        ADI SOYADI
        TICARET UNVANI
        IS YERI ADRESI
        VERGI TURU
        VERGI
        DAIRESI
        VERGI KIMLIK
        NO
        TC KIMLIK NO
        ISE BASLAMA
        TARIHI
        ANA FAALIYET
        KODU VE ADI
        MUKELLEFIN
        RANAMED MEDIKAL TIBBI MALZEME URUNLERI SANAYI VE TICARET LIMITED SIRKETI
        KAZIM KARABEKIR MAH. ADEM YAVUZ CAD. NO: 22 IC KAPI NO: 2 UMRANIYE / ISTANBUL
        KURUMLAR VERGISI
        UMRANIYE
        7342497874
        01.09.2022
        464601-CERRAHI, TIBBI VE ORTOPEDIK ALET VE CIHAZLARIN TOPTAN TICARETI
        """
        calls: list[str] = []

        def fake_run(command, **_kwargs):
            psm = command[command.index("--psm") + 1]
            calls.append(psm)
            return FakeCompletedProcess(readable_output)

        with patch("app.domain.tax_certificates.shutil.which", return_value="/usr/bin/tesseract"):
            with patch("app.domain.tax_certificates.subprocess.run", side_effect=fake_run):
                text, notes = ocr_image(Path("rana-tax-certificate.png"))

        self.assertEqual(calls, ["6"])
        self.assertIn("RANAMED MEDIKAL", text)
        self.assertIn("ocr_tesseract_psm_6", notes)
        self.assertIn("ocr_early_exit", notes)

    def test_ocr_image_supplements_low_score_full_page_with_regions(self) -> None:
        weak_output = """
        VERGI LEVHASI
        TICARET UNVANI
        """
        roi_output = """
        RANAMED MEDIKAL TIBBI MALZEME URUNLERI SANAYI VE TICARET LIMITED SIRKETI
        UMRANIYE
        7342497874
        464601-CERRAHI, TIBBI VE ORTOPEDIK ALET VE CIHAZLARIN TOPTAN TICARETI
        KAZIM KARABEKIR MAH. ADEM YAVUZ CAD. NO: 22 IC KAPI NO: 2 UMRANIYE / ISTANBUL
        """

        def fake_run(command, **_kwargs):
            return FakeCompletedProcess(weak_output)

        with patch("app.domain.tax_certificates.shutil.which", return_value="/usr/bin/tesseract"):
            with patch("app.domain.tax_certificates.ocr_psm_candidates", return_value=("6", "1")):
                with patch("app.domain.tax_certificates.subprocess.run", side_effect=fake_run):
                    with patch(
                        "app.domain.tax_certificates._ocr_image_regions",
                        return_value=(roi_output, ("ocr_roi", "ocr_roi_regions_4"), 4),
                    ):
                        text, notes = ocr_image(Path("rana-tax-certificate.png"))

        extraction = parse_tax_certificate_text(text)
        self.assertEqual(extraction.vkn, "7342497874")
        self.assertEqual(extraction.nace_code, "464601")
        self.assertIn("ocr_roi_used", notes)
        self.assertIn("ocr_attempts_6", notes)


if __name__ == "__main__":
    unittest.main()
