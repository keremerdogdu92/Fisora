from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Iterable


@dataclass(frozen=True)
class PdfPageText:
    page_no: int
    text: str


@dataclass(frozen=True)
class PageInvoiceIdentity:
    page_no: int
    invoice_no: str
    ettn: str
    tax_ids: tuple[str, ...]
    issue_date: str
    payable_total: str

    @property
    def identity_key(self) -> str:
        return self.ettn or self.invoice_no

    @property
    def coherent(self) -> bool:
        return bool(
            self.identity_key
            and self.tax_ids
            and self.issue_date
            and self.payable_total
        )


@dataclass(frozen=True)
class MultiInvoiceBoundaryDecision:
    status: str
    identity_cluster_count: int
    reason_codes: tuple[str, ...]
    identities: tuple[PageInvoiceIdentity, ...] = ()


_ETTN_RE = re.compile(r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b")
_INVOICE_NO_RE = re.compile(r"\b(?:[A-Z]{2,4}\d{8,16}|[A-Z]\d[A-Z]\d{8,16})\b")
_DATE_RE = re.compile(r"(?<!\d)([0-3]?\d)[./-]([01]?\d)[./-](20\d{2})(?!\d)")
_TAX_ID_RE = re.compile(r"\b(?:VKN|TCKN|Vergi\s+No|TC\s*Kimlik\s*No)\s*:?[ \t]*([0-9]{10,11})\b", re.IGNORECASE)
_AMOUNT_RE = re.compile(r"(-?\d{1,3}(?:[.\s]\d{3})*(?:,\d{2})|-?\d+(?:,\d{2}))")


def _page_identity(page: PdfPageText) -> PageInvoiceIdentity:
    text = page.text or ""
    invoice_match = _INVOICE_NO_RE.search(text)
    ettn_match = _ETTN_RE.search(text)
    date_match = _DATE_RE.search(text)
    tax_ids = tuple(dict.fromkeys(match.group(1) for match in _TAX_ID_RE.finditer(text)))
    payable_total = ""
    for line in text.splitlines():
        if re.search(r"ödenecek|odenecek|fatura tutarı|fatura tutari|genel toplam|toplam tutar", line, re.IGNORECASE):
            amounts = list(_AMOUNT_RE.finditer(line))
            if amounts:
                payable_total = amounts[-1].group(1)
                break
    return PageInvoiceIdentity(
        page_no=page.page_no,
        invoice_no=invoice_match.group(0) if invoice_match else "",
        ettn=ettn_match.group(0).lower() if ettn_match else "",
        tax_ids=tax_ids,
        issue_date=date_match.group(0) if date_match else "",
        payable_total=payable_total,
    )


def detect_multiple_invoice_identities(
    pages: Iterable[PdfPageText],
) -> MultiInvoiceBoundaryDecision:
    page_list = tuple(pages)
    identities = tuple(_page_identity(page) for page in page_list)
    by_key: dict[str, PageInvoiceIdentity] = {}
    for page, identity in zip(page_list, identities):
        if identity.identity_key:
            by_key.setdefault(identity.identity_key, identity)
        if not identity.ettn:
            for candidate in _INVOICE_NO_RE.findall(page.text or ""):
                by_key.setdefault(
                    candidate,
                    PageInvoiceIdentity(page.page_no, candidate, "", (), "", ""),
                )
    clusters = tuple(by_key.values())
    coherent = tuple(identity for identity in clusters if identity.coherent)
    if len(coherent) >= 2:
        return MultiInvoiceBoundaryDecision(
            status="confirmed_multiple",
            identity_cluster_count=len(clusters),
            reason_codes=("distinct_invoice_identities",),
            identities=coherent,
        )
    if len(clusters) >= 2:
        return MultiInvoiceBoundaryDecision(
            status="insufficient_identity",
            identity_cluster_count=len(clusters),
            reason_codes=("insufficient_coherent_headers",),
            identities=clusters,
        )
    return MultiInvoiceBoundaryDecision(
        status="single_invoice",
        identity_cluster_count=len(clusters),
        reason_codes=(),
        identities=clusters,
    )
