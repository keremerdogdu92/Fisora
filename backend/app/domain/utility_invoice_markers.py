from __future__ import annotations

import re
import unicodedata
from typing import Iterable


DEVICE_PATTERN = re.compile(r"\b(?:cihaz|telefon|tablet|modem|iphone|samsung galaxy)\b", re.IGNORECASE)
INSTALLMENT_PATTERN = re.compile(r"\b(?:taksit|installment)\b|\b\d{1,2}\s*/\s*\d{1,2}\b", re.IGNORECASE)


def _normalized(value: str) -> str:
    folded = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    return " ".join(folded.lower().split())


def detect_utility_invoice_markers(
    *,
    service_profile: str,
    source: str,
    line_descriptions: Iterable[str],
) -> tuple[str, ...]:
    """Find only explicit UBL exceptions; ordinary utility rows stay untouched."""

    if source != "xml" or not service_profile:
        return ()
    text = "\n".join(_normalized(value) for value in line_descriptions if str(value).strip())
    markers: list[str] = []
    has_installment = bool(INSTALLMENT_PATTERN.search(text))
    if DEVICE_PATTERN.search(text) and not has_installment:
        markers.append("utility_device_line")
    if has_installment:
        markers.append("utility_installment_line")
    return tuple(markers)


def utility_exception_requires_review(
    markers: Iterable[str],
    *,
    has_profile_authority: bool,
) -> bool:
    # Device and installment rows remain visible evidence, but the accepted
    # utility policy posts them with the related phone/internet expense. They
    # are therefore informational markers, not review blockers.
    del markers, has_profile_authority
    return False
