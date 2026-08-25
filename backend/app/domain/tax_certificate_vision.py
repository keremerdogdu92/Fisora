# File: backend/app/domain/tax_certificate_vision.py
# Summary: Adds AI-first structured tax-certificate reading over the existing Gemini project pool.
from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
import os
from pathlib import Path
import re
from typing import Any, Mapping

from app.domain.gemini_pdf_runtime import build_gemini_pdf_runtime_from_env


TAX_CERTIFICATE_VISION_PROMPT_VERSION = "tax-certificate-reader-v1"
TAX_CERTIFICATE_VISION_SCHEMA_VERSION = "tax-certificate-v1"
_FALSE_VALUES = frozenset({"0", "false", "no", "off"})
_SUPPORTED_IMAGE_SUFFIXES = frozenset({".png", ".jpg", ".jpeg", ".tif", ".tiff"})


@dataclass(frozen=True)
class TaxCertificateVisionRead:
    tckn: str = ""
    vkn: str = ""
    taxpayer_kind: str = "unknown"
    legal_name: str = ""
    trade_name: str = ""
    display_title: str = ""
    tax_office: str = ""
    nace_code: str = ""
    activity_description: str = ""
    workplace_addresses: tuple[str, ...] = ()
    start_date: str = ""
    confidence: int = 0
    warnings: tuple[str, ...] = ()


TAX_CERTIFICATE_VISION_SCHEMA: dict[str, object] = {
    "type": "object",
    "properties": {
        "tckn": {"type": "string"},
        "vkn": {"type": "string"},
        "taxpayer_kind": {"type": "string", "enum": ["individual", "company", "unknown"]},
        "legal_name": {"type": "string"},
        "trade_name": {"type": "string"},
        "display_title": {"type": "string"},
        "tax_office": {"type": "string"},
        "nace_code": {"type": "string"},
        "activity_description": {"type": "string"},
        "workplace_addresses": {"type": "array", "items": {"type": "string"}},
        "start_date": {"type": "string"},
        "confidence": {"type": "integer", "minimum": 0, "maximum": 100},
        "warnings": {"type": "array", "items": {"type": "string"}},
    },
    "required": [
        "tckn",
        "vkn",
        "taxpayer_kind",
        "legal_name",
        "trade_name",
        "display_title",
        "tax_office",
        "nace_code",
        "activity_description",
        "workplace_addresses",
        "start_date",
        "confidence",
        "warnings",
    ],
    "additionalProperties": False,
}


TAX_CERTIFICATE_VISION_INSTRUCTIONS = """
You read Turkish tax certificates (Vergi Levhası) from the attached document.
Return only facts visibly printed in the document. Do not infer or repair uncertain values.
Copy TCKN and VKN only when the corresponding printed field contains that value.
Do not populate one identifier from an unrelated number, tax amount, approval code, or nearby field.
If the printed TCKN or VKN field is blank or unclear, return an empty string for that field.
Copy the legal/person name, trade name, tax office, NACE code and printed activity description.
Return workplace addresses exactly enough to identify the printed address, without inventing details.
Use DD/MM/YYYY for start_date only when the document clearly shows that date.
Set confidence to your confidence in the complete extraction, from 0 to 100.
Put ambiguity or unreadable-field notes in warnings. Never use outside knowledge.
""".strip()


class GeminiTaxCertificateVisionReader:
    def __init__(self, *, provider: Any, model_name: str = "") -> None:
        self.provider = provider
        self.model_name = model_name or str(getattr(provider, "model", "") or "")

    def __call__(self, path: Path) -> TaxCertificateVisionRead:
        document_bytes = _document_as_pdf_bytes(path)
        payload = self.provider.generate_structured_json(
            schema_name="fisora_tax_certificate",
            instructions=TAX_CERTIFICATE_VISION_INSTRUCTIONS,
            user_payload={
                "prompt_version": TAX_CERTIFICATE_VISION_PROMPT_VERSION,
                "schema_version": TAX_CERTIFICATE_VISION_SCHEMA_VERSION,
                "source_file_name": path.name,
            },
            schema=TAX_CERTIFICATE_VISION_SCHEMA,
            document_bytes=document_bytes,
            document_mime_type="application/pdf",
        )
        return normalize_tax_certificate_vision_payload(payload)


def build_tax_certificate_vision_reader_from_env(
    env: Mapping[str, str] | None = None,
) -> GeminiTaxCertificateVisionReader | None:
    source = dict(os.environ if env is None else env)
    enabled = str(source.get("FISORA_TAX_CERTIFICATE_VISION_ENABLED", "true") or "true").strip().lower()
    if enabled in _FALSE_VALUES:
        return None
    model = str(source.get("FISORA_TAX_CERTIFICATE_VISION_MODEL", "") or "").strip()
    if model:
        source["FISORA_GEMINI_PDF_V2_MODEL"] = model
    runtime = build_gemini_pdf_runtime_from_env(source)
    if not runtime.available or runtime.provider is None:
        return None
    return GeminiTaxCertificateVisionReader(
        provider=runtime.provider,
        model_name=str(getattr(runtime.provider, "model", "") or model),
    )


def normalize_tax_certificate_vision_payload(
    payload: Mapping[str, object],
) -> TaxCertificateVisionRead:
    warnings = _string_tuple(payload.get("warnings"))
    raw_tckn = _digits(payload.get("tckn"))
    raw_vkn = _digits(payload.get("vkn"))
    tckn = raw_tckn if is_valid_tckn(raw_tckn) else ""
    vkn = raw_vkn if is_valid_vkn(raw_vkn) else ""
    if raw_tckn and not tckn:
        warnings = (*warnings, "invalid_tckn_checksum")
    if raw_vkn and not vkn:
        warnings = (*warnings, "invalid_vkn_checksum")
    nace_code = normalize_nace_code(payload.get("nace_code"))
    if _text(payload.get("nace_code")) and not nace_code:
        warnings = (*warnings, "invalid_nace_code")
    taxpayer_kind = _text(payload.get("taxpayer_kind")).lower()
    if taxpayer_kind not in {"individual", "company", "unknown"}:
        taxpayer_kind = "unknown"
    confidence = _bounded_confidence(payload.get("confidence"))
    addresses = _string_tuple(payload.get("workplace_addresses"))
    return TaxCertificateVisionRead(
        tckn=tckn,
        vkn=vkn,
        taxpayer_kind=taxpayer_kind,
        legal_name=_text(payload.get("legal_name")),
        trade_name=_text(payload.get("trade_name")),
        display_title=_text(payload.get("display_title")),
        tax_office=_text(payload.get("tax_office")),
        nace_code=nace_code,
        activity_description=_text(payload.get("activity_description")),
        workplace_addresses=addresses,
        start_date=_normalize_date(payload.get("start_date")),
        confidence=confidence,
        warnings=tuple(dict.fromkeys(warnings)),
    )


def is_valid_tckn(value: str) -> bool:
    if not re.fullmatch(r"[1-9]\d{10}", value):
        return False
    digits = [int(char) for char in value]
    tenth = ((sum(digits[0:9:2]) * 7) - sum(digits[1:8:2])) % 10
    eleventh = sum(digits[:10]) % 10
    return digits[9] == tenth and digits[10] == eleventh


def is_valid_vkn(value: str) -> bool:
    if not re.fullmatch(r"\d{10}", value):
        return False
    digits = [int(char) for char in value]
    total = 0
    for index, digit in enumerate(digits[:9]):
        adjusted = (digit + 9 - index) % 10
        if adjusted == 0:
            contribution = 0
        else:
            contribution = (adjusted * (2 ** (9 - index))) % 9
            if contribution == 0:
                contribution = 9
        total += contribution
    expected = (10 - (total % 10)) % 10
    return digits[9] == expected


def normalize_nace_code(value: object) -> str:
    digits = re.sub(r"\D", "", _text(value))
    return digits if len(digits) == 6 else ""


def _document_as_pdf_bytes(path: Path) -> bytes:
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        document_bytes = path.read_bytes()
        if not document_bytes.startswith(b"%PDF"):
            raise ValueError("tax certificate PDF is invalid")
        return document_bytes
    if suffix not in _SUPPORTED_IMAGE_SUFFIXES:
        raise ValueError("unsupported tax certificate file type")
    try:
        from PIL import Image, ImageOps
    except ModuleNotFoundError as exc:
        raise RuntimeError("Pillow is required for tax certificate image reading") from exc
    with Image.open(path) as image:
        normalized = ImageOps.exif_transpose(image)
        if normalized.mode not in {"RGB", "L"}:
            normalized = normalized.convert("RGB")
        buffer = BytesIO()
        normalized.save(buffer, format="PDF")
        return buffer.getvalue()


def _text(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _digits(value: object) -> str:
    return re.sub(r"\D", "", _text(value))


def _string_tuple(value: object) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)):
        return ()
    cleaned = [_text(item) for item in value]
    return tuple(dict.fromkeys(item for item in cleaned if item))


def _bounded_confidence(value: object) -> int:
    try:
        return max(0, min(100, int(value)))
    except (TypeError, ValueError):
        return 0


def _normalize_date(value: object) -> str:
    text = _text(value)
    match = re.fullmatch(r"(\d{2})[./-](\d{2})[./-](\d{4})", text)
    if not match:
        return ""
    return "/".join(match.groups())
