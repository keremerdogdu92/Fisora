# File: backend/tests/test_tax_certificate_vision.py
# Summary: Locks the AI-first tax certificate reader, identifier guards, and OCR fallback boundary.
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from app.domain.tax_certificate_vision import (
    TaxCertificateVisionRead,
    GeminiTaxCertificateVisionReader,
    normalize_tax_certificate_vision_payload,
)
from app.domain.tax_certificates import parse_tax_certificate_file


class _FakeStructuredProvider:
    def __init__(self, payload: dict[str, object]) -> None:
        self.payload = payload
        self.calls: list[dict[str, object]] = []

    def generate_structured_json(self, **kwargs: object) -> dict[str, object]:
        self.calls.append(dict(kwargs))
        return dict(self.payload)


class TaxCertificateVisionTests(unittest.TestCase):
    def test_normalize_payload_keeps_valid_identifiers_and_nace(self) -> None:
        result = normalize_tax_certificate_vision_payload(
            {
                "tckn": "45661316282",
                "vkn": "9270740926",
                "nace_code": "47.74.01",
                "legal_name": "ORNEK LIMITED SIRKETI",
                "tax_office": "KADIKOY",
                "activity_description": "TIBBI URUNLERIN PERAKENDE TICARETI",
                "workplace_addresses": ["ORNEK MAH. NO: 1 ISTANBUL"],
                "confidence": 96,
            }
        )

        self.assertEqual(result.tckn, "45661316282")
        self.assertEqual(result.vkn, "9270740926")
        self.assertEqual(result.nace_code, "477401")
        self.assertEqual(result.confidence, 96)
        self.assertEqual(result.warnings, ())

    def test_normalize_payload_rejects_bad_identifier_checksums(self) -> None:
        result = normalize_tax_certificate_vision_payload(
            {"tckn": "45661316283", "vkn": "9270740927", "nace_code": "ABC"}
        )

        self.assertEqual(result.tckn, "")
        self.assertEqual(result.vkn, "")
        self.assertEqual(result.nace_code, "")
        self.assertIn("invalid_tckn_checksum", result.warnings)
        self.assertIn("invalid_vkn_checksum", result.warnings)
    def test_gemini_reader_sends_pdf_as_structured_document(self) -> None:
        provider = _FakeStructuredProvider(
            {
                "vkn": "9270740926",
                "legal_name": "ORNEK LIMITED SIRKETI",
                "tax_office": "KADIKOY",
                "nace_code": "477401",
                "activity_description": "TIBBI URUNLERIN PERAKENDE TICARETI",
                "workplace_addresses": ["ORNEK MAH. NO: 1 ISTANBUL"],
                "confidence": 94,
            }
        )
        reader = GeminiTaxCertificateVisionReader(provider=provider, model_name="gemini-test")
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "levha.pdf"
            path.write_bytes(b"%PDF-1.4\n%tax-certificate\n")
            result = reader(path)

        self.assertEqual(result.vkn, "9270740926")
        self.assertEqual(len(provider.calls), 1)
        self.assertEqual(provider.calls[0]["document_mime_type"], "application/pdf")
        self.assertEqual(provider.calls[0]["document_bytes"], b"%PDF-1.4\n%tax-certificate\n")
        self.assertEqual(reader.model_name, "gemini-test")

    def test_scanned_pdf_uses_vision_before_tesseract(self) -> None:
        vision_result = TaxCertificateVisionRead(
            vkn="9270740926",
            legal_name="ORNEK LIMITED SIRKETI",
            display_title="ORNEK LIMITED SIRKETI",
            tax_office="KADIKOY",
            nace_code="477401",
            activity_description="TIBBI URUNLERIN PERAKENDE TICARETI",
            workplace_addresses=("ORNEK MAH. NO: 1 ISTANBUL",),
            confidence=95,
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "scan.pdf"
            path.write_bytes(b"%PDF-1.4\n%scan\n")
            with patch(
                "app.domain.tax_certificates.extract_pdf_text",
                return_value=([], "", ("pdf_text_empty",)),
            ), patch(
                "app.domain.tax_certificates.ocr_pdf",
                side_effect=AssertionError("tesseract should remain fallback-only"),
            ):
                extraction = parse_tax_certificate_file(
                    path,
                    vision_reader=lambda _: vision_result,
                )

        self.assertEqual(extraction.vkn, "9270740926")
        self.assertEqual(extraction.nace_code, "477401")
        self.assertEqual(extraction.processing_metrics["used_ai_vision"], True)
        self.assertEqual(extraction.processing_metrics["used_ocr"], False)
        self.assertIn("ai_vision", extraction.extraction_notes)


class TaxCertificateVisionIdentityLockTests(unittest.TestCase):
    def test_text_layer_valid_identity_is_not_expanded_by_vision(self) -> None:
        from app.domain.tax_certificates import (
            TaxCertificateExtraction,
            merge_tax_certificate_vision_extraction,
        )

        base = TaxCertificateExtraction(
            title="ORHAN ELIBOL",
            tckn="30052309394",
            tax_identifier="30052309394",
            nace_code="477401",
        )
        vision = TaxCertificateExtraction(
            title="ORHAN ELIBOL",
            tckn="30052309394",
            vkn="3310145548",
            tax_identifier="3310145548",
            nace_code="477401",
        )

        merged = merge_tax_certificate_vision_extraction(base, vision)

        self.assertEqual(merged.tckn, "30052309394")
        self.assertEqual(merged.vkn, "")
        self.assertEqual(merged.tax_identifier, "30052309394")
        self.assertEqual(merged.identity_type, "tckn")


class TaxCertificateVisionFallbackTests(unittest.TestCase):
    def test_invalid_text_identity_does_not_block_ocr_fallback(self) -> None:
        text_layer = """
        TICARI UNVANI
        ORNEK LIMITED SIRKETI
        VERGI DAIRESI
        KADIKOY
        VERGI KIMLIK NO
        9270740927
        IS YERI ADRESI
        ORNEK MAH. NO: 1 ISTANBUL
        ANA FAALIYET KODU VE ADI
        477401-TIBBI URUNLERIN PERAKENDE TICARETI
        """

        def unavailable_vision(_: Path) -> TaxCertificateVisionRead:
            raise RuntimeError("vision unavailable")

        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "levha.pdf"
            path.write_bytes(b"%PDF-1.4\n%scan\n")
            with patch(
                "app.domain.tax_certificates.extract_pdf_text",
                return_value=([], text_layer, ("pdf_text_layer",)),
            ), patch(
                "app.domain.tax_certificates.ocr_pdf_identity_region",
                return_value=("VERGI KIMLIK NO\n9270740926", ("ocr_tesseract", "ocr_attempts_1")),
            ), patch(
                "app.domain.tax_certificates.ocr_pdf",
                side_effect=AssertionError("identity OCR should be enough"),
            ):
                extraction = parse_tax_certificate_file(
                    path,
                    vision_reader=unavailable_vision,
                )

        self.assertEqual(extraction.vkn, "9270740926")
        self.assertEqual(extraction.tax_identifier, "9270740926")
        self.assertTrue(extraction.processing_metrics["used_ocr"])
        self.assertIn("ai_vision_failed:RuntimeError", extraction.extraction_notes)


if __name__ == "__main__":
    unittest.main()
