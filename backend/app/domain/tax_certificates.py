from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
import os
import re
import shutil
import subprocess
import tempfile
import unicodedata

from app.domain.business_relevance import ActivityProfile, build_activity_profile
from app.domain.pdf_invoices import extract_pdf_text


@dataclass(frozen=True)
class TaxCertificateExtraction:
    title: str = ""
    tax_id: str = ""
    tckn: str = ""
    vkn: str = ""
    identity_type: str = ""
    tax_identifier: str = ""
    legal_name: str = ""
    trade_name: str = ""
    display_title: str = ""
    tax_office: str = ""
    activity_description: str = ""
    nace_code: str = ""
    workplace_addresses: tuple[str, ...] = ()
    start_date: str = ""
    activity_tags: tuple[str, ...] = ()
    activity_profile: ActivityProfile = field(default_factory=ActivityProfile)
    confidence: int = 0
    extraction_notes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        identifier = self.tax_identifier or self.vkn or self.tckn or self.tax_id
        identity_type = self.identity_type or identity_type_for(identifier)
        tckn = self.tckn or (identifier if identity_type == "tckn" else "")
        vkn = self.vkn or (identifier if identity_type == "vkn" else "")
        title = self.title or self.display_title or self.trade_name or self.legal_name
        legal_name = self.legal_name or title
        display_title = self.display_title or self.trade_name or legal_name or title
        object.__setattr__(self, "tax_identifier", identifier)
        object.__setattr__(self, "identity_type", identity_type)
        object.__setattr__(self, "tckn", tckn)
        object.__setattr__(self, "vkn", vkn)
        object.__setattr__(self, "tax_id", self.tax_id or identifier)
        object.__setattr__(self, "title", title)
        object.__setattr__(self, "legal_name", legal_name)
        object.__setattr__(self, "display_title", display_title)

    def to_payload(self) -> dict[str, object]:
        payload = asdict(self)
        payload["workplace_addresses"] = list(self.workplace_addresses)
        payload["activity_tags"] = list(self.activity_tags)
        payload["activity_profile"] = self.activity_profile.to_payload()
        payload["extraction_notes"] = list(self.extraction_notes)
        return payload


LABEL_ALIASES = {
    "title": (
        "adisoyadiunvani",
        "adisoyadi",
        "adsoyadunvan",
        "unvani",
        "ticariunvani",
        "ticaretunvani",
        "mukellefinunvani",
    ),
    "tax_id": (
        "vergikimliknumarasi",
        "vergikimlikno",
        "tckimliknumarasi",
        "tckimlikno",
        "vergino",
        "vkn",
    ),
    "tax_office": (
        "bagliolduguvergidairesi",
        "vergidairesimudurlugu",
        "vergidairesi",
    ),
    "activity": (
        "anafaaliyetkoduveadi",
        "anafaaliyet",
        "faaliyetkoduveadi",
        "faaliyetkoduadi",
        "faaliyet",
    ),
    "address": (
        "isyeriadresi",
        "isyeriadresi",
        "adres",
    ),
    "start_date": (
        "isebaslamatarihi",
        "isebaslama",
    ),
}


def normalize_spaces(value: str) -> str:
    return re.sub(r"\s+", " ", value.replace("\xa0", " ")).strip(" :-\t")


def normalize_key(value: str) -> str:
    translated = value.translate(str.maketrans({"ı": "i", "İ": "I", "ğ": "g", "Ğ": "G", "ü": "u", "Ü": "U", "ş": "s", "Ş": "S", "ö": "o", "Ö": "O", "ç": "c", "Ç": "C"}))
    decomposed = unicodedata.normalize("NFKD", translated)
    ascii_text = "".join(char for char in decomposed if not unicodedata.combining(char))
    return re.sub(r"[^a-z0-9]+", "", ascii_text.lower())


def normalized_lines(text: str) -> list[str]:
    return [normalize_spaces(line) for line in text.replace("\r", "\n").split("\n") if normalize_spaces(line)]


def is_label_line(line: str) -> bool:
    key = normalize_key(line)
    return any(key == alias or key.startswith(alias) for aliases in LABEL_ALIASES.values() for alias in aliases)


def line_matches_label(line: str, field: str) -> bool:
    key = normalize_key(line)
    return any(key == alias or key.startswith(alias) for alias in LABEL_ALIASES[field])


def strip_label_prefix(line: str, field: str) -> str:
    if ":" in line:
        _, suffix = line.split(":", 1)
        return normalize_spaces(suffix)
    key = normalize_key(line)
    for alias in LABEL_ALIASES[field]:
        if alias in key and len(key) > len(alias):
            return ""
    return ""


def value_after_label(lines: list[str], field: str, *, max_lines: int = 2) -> str:
    for index, line in enumerate(lines):
        if not line_matches_label(line, field):
            continue
        inline_value = strip_label_prefix(line, field)
        if inline_value and not is_label_line(inline_value):
            return inline_value
        values: list[str] = []
        for next_line in lines[index + 1 : index + 1 + max_lines]:
            if is_label_line(next_line):
                break
            values.append(next_line)
        return normalize_spaces(" ".join(values))
    return ""


def inline_title_value(lines: list[str]) -> str:
    patterns = (
        r"^\s*ad[ıi]\s+soyad[ıi](?:\s*/\s*[uü]nvan[ıi]|\s+[uü]nvan[ıi])?\s+(.+)$",
        r"^\s*m[uü]kellefin\s+[uü]nvan[ıi]\s+(.+)$",
    )
    for line in lines:
        normalized = normalize_spaces(line)
        for pattern in patterns:
            match = re.match(pattern, normalized, flags=re.IGNORECASE)
            if match:
                return normalize_spaces(match.group(1))
    return ""


def inline_activity_value(lines: list[str]) -> str:
    for index, line in enumerate(lines):
        key = normalize_key(line)
        if key in {"anafaaliyet", "faaliyet"}:
            for next_line in lines[index + 1 : index + 5]:
                next_key = normalize_key(next_line)
                if next_key in {"koduveadi", "adi"}:
                    continue
                if is_label_line(next_line):
                    break
                return normalize_spaces(next_line)
        if key.startswith("anafaaliyet") or key.startswith("faaliyet"):
            inline = re.sub(r"^\s*(ana\s+faaliyet|faaliyet)(?:\s+kodu\s+ve\s+ad[ıi])?\s*", "", line, flags=re.IGNORECASE)
            inline = normalize_spaces(inline)
            if inline and normalize_key(inline) != key:
                return inline
    return ""


def activity_value_from_nace_line(lines: list[str]) -> str:
    for line in lines:
        if re.search(r"\b\d{6}\s*[-:]", line):
            return normalize_spaces(line)
    return ""


def clean_address(value: str) -> str:
    return normalize_spaces(re.sub(r"\b\d{10,11}\b", " ", value))


def parse_activity(value: str) -> tuple[str, str]:
    match = re.search(r"\b(\d{2}[.\s]?\d{2}[.\s]?\d{2}|\d{6})\b\s*[-:–]?\s*(.*)", value)
    if not match:
        return "", normalize_spaces(value)
    code = re.sub(r"\D", "", match.group(1))
    description = normalize_spaces(match.group(2) or value)
    return code, description


def first_tax_id(text: str) -> str:
    matches = re.findall(r"\b(\d{10,11})\b", text)
    if not matches:
        return ""
    return next((value for value in matches if len(value) == 11), matches[0])


def identity_type_for(identifier: str) -> str:
    digits = re.sub(r"\D", "", identifier or "")
    if len(digits) == 11:
        return "tckn"
    if len(digits) == 10:
        return "vkn"
    return ""


def first_date(text: str) -> str:
    match = re.search(r"\b(\d{2}[./-]\d{2}[./-]\d{4})\b", text)
    return match.group(1) if match else ""


def ocr_psm_candidates() -> tuple[str, ...]:
    configured = os.environ.get("FISORA_TAX_CERTIFICATE_OCR_PSM", "")
    values = tuple(value.strip() for value in configured.split(",") if value.strip())
    return values or ("6", "1", "12")


def score_confidence(*, title: str, tax_id: str, tax_office: str, activity_description: str, nace_code: str, addresses: tuple[str, ...], start_date: str) -> int:
    score = 0
    if title:
        score += 20
    if tax_id:
        score += 30
    if tax_office:
        score += 10
    if activity_description:
        score += 10
    if nace_code:
        score += 10
    if addresses:
        score += 15
    if start_date:
        score += 5
    return min(score, 100)


def _line_is_date(line: str) -> bool:
    return bool(re.fullmatch(r"\d{2}[./-]\d{2}[./-]\d{4}", normalize_spaces(line)))


def _line_is_tax_identifier(line: str) -> bool:
    return bool(re.fullmatch(r"\d{10,11}", normalize_spaces(line)))


def _looks_like_address(line: str) -> bool:
    key = normalize_key(line)
    return any(token in key for token in ("mah", "cad", "sok", "sk", "bulvar", "blv", "no", "istanbul", "ankara", "izmir")) and not is_label_line(line)


def _looks_like_tax_office(line: str) -> bool:
    key = normalize_key(line)
    return "vergidairesi" in key and not is_label_line(line)


def _looks_like_title_candidate(line: str) -> bool:
    key = normalize_key(line)
    if not key or is_label_line(line) or _line_is_date(line) or _line_is_tax_identifier(line):
        return False
    if re.search(r"\b\d{6}\s*[-:]", line) or _looks_like_address(line) or _looks_like_tax_office(line):
        return False
    blocked = ("vergi", "faaliyet", "gelir", "gib", "www", "http", "baskanligi", "turu")
    if any(token in key for token in blocked):
        return False
    return bool(re.search(r"[A-Za-zÄ°Ä±Ã‡Ã§ÄžÄŸÃ–Ã¶ÅžÅŸÃœÃ¼]", line)) and len(line.split()) >= 2


def gib_column_values(lines: list[str]) -> dict[str, str]:
    keys = {normalize_key(line) for line in lines}
    has_column_layout = {"adisoyadi", "isyeriadresi", "vergidairesi"}.issubset(keys) and any(
        key in {"tckimlikno", "vergikimlikno"} for key in keys
    )
    if not has_column_layout:
        return {}

    activity_index = next((index for index, line in enumerate(lines) if re.search(r"\b\d{6}\s*[-:]", line)), -1)
    tax_identifier = ""
    if activity_index >= 0:
        for line in lines[activity_index + 1 :]:
            if _line_is_tax_identifier(line):
                tax_identifier = line
                break
    if not tax_identifier:
        tax_identifier = first_tax_id("\n".join(lines))

    tax_office = next((line for line in lines if _looks_like_tax_office(line)), "")
    address = next((line for line in lines if _looks_like_address(line)), "")
    title = ""
    if address:
        address_index = lines.index(address)
        title = next((line for line in lines[address_index + 1 :] if _looks_like_title_candidate(line)), "")
    if not title:
        title = next((line for line in reversed(lines) if _looks_like_title_candidate(line)), "")

    return {
        "title": title,
        "tax_identifier": tax_identifier,
        "tax_office": tax_office,
        "address": address,
    }


def parse_tax_certificate_text(text: str, *, extraction_notes: tuple[str, ...] = ()) -> TaxCertificateExtraction:
    lines = normalized_lines(text)
    joined_text = "\n".join(lines)
    column_values = gib_column_values(lines)
    title = value_after_label(lines, "title", max_lines=1) or inline_title_value(lines) or column_values.get("title", "")
    tax_id = first_tax_id(value_after_label(lines, "tax_id", max_lines=1)) or column_values.get("tax_identifier", "") or first_tax_id(joined_text)
    tax_office = value_after_label(lines, "tax_office", max_lines=1) or column_values.get("tax_office", "")
    activity_value = activity_value_from_nace_line(lines) or value_after_label(lines, "activity", max_lines=3) or inline_activity_value(lines)
    nace_code, activity_description = parse_activity(activity_value)
    activity_profile = build_activity_profile(
        activity_description=activity_description,
        nace_code=nace_code,
    )
    raw_address = value_after_label(lines, "address", max_lines=4)
    if column_values.get("address") and not _looks_like_address(raw_address):
        raw_address = column_values["address"]
    address = clean_address(raw_address)
    start_date = first_date(value_after_label(lines, "start_date", max_lines=1)) or first_date(joined_text)
    addresses = (address,) if address else ()
    confidence = score_confidence(
        title=title,
        tax_id=tax_id,
        tax_office=tax_office,
        activity_description=activity_description,
        nace_code=nace_code,
        addresses=addresses,
        start_date=start_date,
    )
    notes = tuple(dict.fromkeys((*extraction_notes, "fields_extracted" if confidence else "no_fields_extracted")))
    identity_type = identity_type_for(tax_id)
    return TaxCertificateExtraction(
        title=title,
        tax_id=tax_id,
        tckn=tax_id if identity_type == "tckn" else "",
        vkn=tax_id if identity_type == "vkn" else "",
        identity_type=identity_type,
        tax_identifier=tax_id,
        legal_name=title,
        trade_name="",
        display_title=title,
        tax_office=tax_office,
        activity_description=activity_description,
        nace_code=nace_code,
        workplace_addresses=addresses,
        start_date=start_date,
        activity_tags=activity_profile.activity_tags,
        activity_profile=activity_profile,
        confidence=confidence,
        extraction_notes=notes,
    )


def ocr_image(path: Path) -> tuple[str, tuple[str, ...]]:
    tesseract = shutil.which("tesseract")
    if not tesseract:
        return "", ("ocr_tesseract_missing",)
    language = os.environ.get("FISORA_TAX_CERTIFICATE_OCR_LANG", "tur+eng")
    best_text = ""
    best_notes: tuple[str, ...] = ("ocr_tesseract",)
    best_score = -1
    failures: list[str] = []
    for psm in ocr_psm_candidates():
        try:
            completed = subprocess.run(
                [tesseract, str(path), "stdout", "-l", language, "--psm", psm],
                check=False,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=90,
            )
        except Exception as exc:  # noqa: BLE001
            failures.append(f"ocr_error_psm_{psm}:{type(exc).__name__}")
            continue
        if completed.returncode != 0:
            failures.append(f"ocr_failed_psm_{psm}:{completed.returncode}")
            continue
        candidate_text = completed.stdout
        candidate_score = parse_tax_certificate_text(candidate_text).confidence
        if candidate_score > best_score:
            best_text = candidate_text
            best_score = candidate_score
            best_notes = ("ocr_tesseract", f"ocr_tesseract_psm_{psm}")
    if best_score >= 0:
        return best_text, best_notes
    return "", tuple(failures or ("ocr_failed",))


def ocr_pdf(path: Path) -> tuple[str, tuple[str, ...]]:
    pdftoppm = shutil.which("pdftoppm")
    if not pdftoppm:
        return "", ("pdf_text_empty", "ocr_pdf_renderer_missing")
    notes = ["pdf_text_empty", "ocr_pdf_rendered"]
    with tempfile.TemporaryDirectory() as temp_dir:
        output_prefix = Path(temp_dir) / "tax_certificate_page"
        try:
            rendered = subprocess.run(
                [pdftoppm, "-r", "250", "-png", "-singlefile", str(path), str(output_prefix)],
                check=False,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=90,
            )
        except Exception as exc:  # noqa: BLE001
            return "", tuple((*notes, f"ocr_pdf_render_error:{type(exc).__name__}"))
        if rendered.returncode != 0:
            return "", tuple((*notes, f"ocr_pdf_render_failed:{rendered.returncode}"))
        image_path = output_prefix.with_suffix(".png")
        text, ocr_notes = ocr_image(image_path)
        return text, tuple((*notes, *ocr_notes))


def extract_tax_certificate_text(path: Path) -> tuple[str, tuple[str, ...]]:
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        _, text, pdf_notes = extract_pdf_text(path)
        if text.strip():
            return text, tuple((*pdf_notes, "pdf_text_layer"))
        ocr_text, ocr_notes = ocr_pdf(path)
        return ocr_text, tuple((*pdf_notes, *ocr_notes))
    if suffix in {".png", ".jpg", ".jpeg", ".tif", ".tiff"}:
        return ocr_image(path)
    return "", ("unsupported_tax_certificate_file_type",)


def parse_tax_certificate_file(path: Path) -> TaxCertificateExtraction:
    text, notes = extract_tax_certificate_text(path)
    return parse_tax_certificate_text(text, extraction_notes=notes)
