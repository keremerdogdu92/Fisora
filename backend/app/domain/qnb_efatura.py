from __future__ import annotations

import base64
from dataclasses import asdict, dataclass
import hashlib
import io
from pathlib import Path
import time
from datetime import UTC, datetime
from typing import Mapping, Protocol
from xml.etree import ElementTree
from xml.sax.saxutils import escape
from uuid import uuid4
import zipfile

import httpx

from app.domain.document_uploads import store_document_content
from app.domain.qnb_credentials import QnbCredentialCipher, qnb_platform_erp_code, validate_qnb_endpoint
from app.workflows.document_processing import parser_kind_for_document_type


SOURCE_PROVIDER = "qnb_esolutions"
SOURCE_DIRECTION = "incoming_efatura"
QNB_USER_NAMESPACE = "http://service.csap.cs.com.tr/"
QNB_CONNECTOR_NAMESPACE = "http://service.connector.uut.cs.com.tr/"
QNB_LIST_PAGE_SIZE = 100
QNB_MAX_COMPRESSED_BYTES = 20 * 1024 * 1024
QNB_MAX_UNCOMPRESSED_BYTES = 50 * 1024 * 1024
QNB_MAX_ZIP_ENTRIES = 20


@dataclass(frozen=True)
class QnbConnectionCredentials:
    base_url: str
    username: str
    password: str
    vkn: str
    erp_code: str


@dataclass(frozen=True)
class QnbInvoiceSummary:
    ettn: str
    invoice_no: str
    sequence_no: str
    issue_date: str
    supplier_tax_id: str
    supplier_title: str
    payable_total: str
    qnb_status: str = ""


@dataclass(frozen=True)
class QnbIncomingInvoicePage:
    items: tuple[QnbInvoiceSummary, ...]
    last_sequence_no: str = ""
    has_more: bool = False


@dataclass(frozen=True)
class QnbDownloadedDocument:
    ettn: str
    file_name: str
    content: bytes
    content_type: str = "application/xml"


@dataclass(frozen=True)
class QnbConnectionTestResult:
    ok: bool
    status: str
    message: str = ""


@dataclass(frozen=True)
class QnbMailboxLabel:
    label: str
    kind: str
    opened_at: str = ""


@dataclass(frozen=True)
class QnbOutgoingInvoiceSendResult:
    document_oid: str
    local_invoice_no: str


@dataclass(frozen=True)
class QnbOutgoingInvoiceStatus:
    document_oid: str
    status_code: str
    processing_state: str
    status_text: str = ""
    description: str = ""
    ettn: str = ""


@dataclass(frozen=True)
class QnbIncomingInvoiceStatus:
    ettn: str
    response_code: str
    normalized_status: str
    response_detail: str = ""
    cancelled_at: str = ""


class QnbEfaturaAdapter(Protocol):
    def test_connection(self, credentials: QnbConnectionCredentials) -> QnbConnectionTestResult:
        ...

    def list_incoming_invoices(
        self,
        credentials: QnbConnectionCredentials,
        *,
        start_date: str = "",
        end_date: str = "",
        cursor: str = "",
    ) -> list[QnbInvoiceSummary]:
        ...

    def download_incoming_invoice_ubl(
        self,
        credentials: QnbConnectionCredentials,
        invoice: QnbInvoiceSummary,
    ) -> QnbDownloadedDocument:
        ...

    def download_incoming_invoice_pdf(
        self,
        credentials: QnbConnectionCredentials,
        invoice: QnbInvoiceSummary,
    ) -> QnbDownloadedDocument:
        ...

    def get_outgoing_invoice_status(self, credentials: QnbConnectionCredentials, *, document_oid: str) -> QnbOutgoingInvoiceStatus:
        ...

    def get_incoming_invoice_status(self, credentials: QnbConnectionCredentials, *, ettn: str) -> QnbIncomingInvoiceStatus:
        ...


def build_qnb_adapter_from_env(env: Mapping[str, str]) -> QnbEfaturaAdapter:
    selected = str(env.get("FISORA_QNB_ADAPTER") or env.get("FISORA_QNB_EFATURA_ADAPTER") or "fake").strip().lower()
    if selected in {"soap", "qnb_soap", "real"}:
        return QnbSoapEfaturaAdapter()
    return FakeQnbEfaturaAdapter()


class FakeQnbEfaturaAdapter:
    def __init__(
        self,
        *,
        invoices: list[QnbInvoiceSummary] | None = None,
        downloads: dict[str, bytes] | None = None,
        page_size: int = QNB_LIST_PAGE_SIZE,
        outgoing_statuses: dict[str, QnbOutgoingInvoiceStatus] | None = None,
        incoming_statuses: dict[str, QnbIncomingInvoiceStatus] | None = None,
        pdf_downloads: dict[str, bytes] | None = None,
    ) -> None:
        self.invoices = invoices or []
        self.downloads = downloads or {}
        self.page_size = page_size
        self.outgoing_statuses = outgoing_statuses or {}
        self.incoming_statuses = incoming_statuses or {}
        self.pdf_downloads = pdf_downloads or {}

    def test_connection(self, credentials: QnbConnectionCredentials) -> QnbConnectionTestResult:
        if not credentials.username or not credentials.password:
            return QnbConnectionTestResult(False, "auth_failed", "missing credentials")
        return QnbConnectionTestResult(True, "active")

    def list_incoming_invoices(
        self,
        credentials: QnbConnectionCredentials,
        *,
        start_date: str = "",
        end_date: str = "",
        cursor: str = "",
    ) -> list[QnbInvoiceSummary]:
        return list(
            self.list_incoming_page(
                credentials,
                start_date=start_date,
                end_date=end_date,
                cursor=cursor,
            ).items
        )

    def list_incoming_page(
        self,
        credentials: QnbConnectionCredentials,
        *,
        start_date: str = "",
        end_date: str = "",
        cursor: str = "",
    ) -> QnbIncomingInvoicePage:
        if cursor and (start_date or end_date):
            raise ValueError("QNB cursor cannot be combined with date filters")
        invoices = list(self.invoices)
        if cursor:
            invoices = [invoice for invoice in invoices if _sequence_after(invoice.sequence_no, cursor)]
        page_items = invoices[: max(self.page_size, 1)]
        return QnbIncomingInvoicePage(
            items=tuple(page_items),
            last_sequence_no=page_items[-1].sequence_no if page_items else "",
            has_more=len(invoices) > len(page_items),
        )

    def download_incoming_invoice_ubl(
        self,
        credentials: QnbConnectionCredentials,
        invoice: QnbInvoiceSummary,
    ) -> QnbDownloadedDocument:
        content = self.downloads.get(invoice.ettn)
        if content is None:
            raise ValueError(f"fake QNB download missing for ETTN: {invoice.ettn}")
        return QnbDownloadedDocument(
            ettn=invoice.ettn,
            file_name=f"qnb-{invoice.ettn}.xml",
            content=content,
        )

    def get_outgoing_invoice_status(self, credentials: QnbConnectionCredentials, *, document_oid: str) -> QnbOutgoingInvoiceStatus:
        return self.outgoing_statuses.get(
            document_oid,
            QnbOutgoingInvoiceStatus(document_oid, "", "unknown", description="status unavailable"),
        )

    def download_incoming_invoice_pdf(self, credentials: QnbConnectionCredentials, invoice: QnbInvoiceSummary) -> QnbDownloadedDocument:
        content = self.pdf_downloads.get(invoice.ettn)
        if content is None:
            raise ValueError(f"fake QNB PDF download missing for ETTN: {invoice.ettn}")
        return QnbDownloadedDocument(invoice.ettn, f"qnb-{invoice.ettn}.pdf", content, "application/pdf")

    def get_incoming_invoice_status(self, credentials: QnbConnectionCredentials, *, ettn: str) -> QnbIncomingInvoiceStatus:
        return self.incoming_statuses.get(ettn, QnbIncomingInvoiceStatus(ettn, "", "unknown"))

    def close_session(self, credentials: QnbConnectionCredentials) -> None:
        return None


class QnbSoapEfaturaAdapter:
    def __init__(
        self,
        *,
        http_client=None,
        timeout: int = 30,
        max_attempts: int = 3,
        min_request_interval: float | None = None,
        sleep=None,
        monotonic=None,
    ) -> None:
        self.http_client = http_client or httpx.Client(timeout=timeout)
        self.timeout = timeout
        self.max_attempts = max(max_attempts, 1)
        self.min_request_interval = (
            float(min_request_interval)
            if min_request_interval is not None
            else (60.0 / 150.0 if http_client is None else 0.0)
        )
        self._sleep = sleep or time.sleep
        self._monotonic = monotonic or time.monotonic
        self._last_request_at = 0.0
        self._logged_in_key = ""

    def test_connection(self, credentials: QnbConnectionCredentials) -> QnbConnectionTestResult:
        try:
            self._login(credentials, force=True)
        except Exception as exc:
            return QnbConnectionTestResult(False, "connection_failed", _redacted_error_message(exc))
        return QnbConnectionTestResult(True, "active")

    def list_incoming_invoices(
        self,
        credentials: QnbConnectionCredentials,
        *,
        start_date: str = "",
        end_date: str = "",
        cursor: str = "",
    ) -> list[QnbInvoiceSummary]:
        return list(
            self.list_incoming_page(
                credentials,
                start_date=start_date,
                end_date=end_date,
                cursor=cursor,
            ).items
        )

    def list_incoming_page(
        self,
        credentials: QnbConnectionCredentials,
        *,
        start_date: str = "",
        end_date: str = "",
        cursor: str = "",
    ) -> QnbIncomingInvoicePage:
        if cursor and (start_date or end_date):
            raise ValueError("QNB cursor cannot be combined with date filters")
        self._login(credentials)
        body = _soap_operation(
            "gelenBelgeleriListeleExt",
            _incoming_parameter_xml(
                credentials=credentials,
                start_date=start_date,
                end_date=end_date,
                cursor=cursor,
            ),
            namespace=QNB_CONNECTOR_NAMESPACE,
        )
        response_xml = self._post_soap(_service_url(credentials.base_url, "connectorService"), "gelenBelgeleriListeleExt", body)
        invoices = _parse_qnb_invoice_summaries(response_xml, require_sequence=True)
        return QnbIncomingInvoicePage(
            items=tuple(invoices),
            last_sequence_no=invoices[-1].sequence_no if invoices else "",
            has_more=len(invoices) >= QNB_LIST_PAGE_SIZE,
        )

    def download_incoming_invoice_ubl(
        self,
        credentials: QnbConnectionCredentials,
        invoice: QnbInvoiceSummary,
    ) -> QnbDownloadedDocument:
        self._login(credentials)
        body = _soap_operation(
            "gelenBelgeleriIndirExt",
            _incoming_parameter_xml(
                credentials=credentials,
                ettn=invoice.ettn,
                document_format="UBL",
            ),
            namespace=QNB_CONNECTOR_NAMESPACE,
        )
        response_xml = self._post_soap(_service_url(credentials.base_url, "connectorService"), "gelenBelgeleriIndirExt", body)
        encoded = _first_return_text(response_xml)
        content = _decode_qnb_download_payload(encoded)
        return QnbDownloadedDocument(
            ettn=invoice.ettn,
            file_name=f"qnb-{invoice.ettn}.xml",
            content=content,
        )

    def download_incoming_invoice_pdf(self, credentials: QnbConnectionCredentials, invoice: QnbInvoiceSummary) -> QnbDownloadedDocument:
        self._login(credentials)
        body = _soap_operation(
            "gelenBelgeleriIndirExt",
            _incoming_parameter_xml(credentials=credentials, ettn=invoice.ettn, document_format="PDF"),
            namespace=QNB_CONNECTOR_NAMESPACE,
        )
        response_xml = self._post_soap(_service_url(credentials.base_url, "connectorService"), "gelenBelgeleriIndirExt", body)
        content = _decode_qnb_download_payload(_first_return_text(response_xml), expected_suffix=".pdf")
        return QnbDownloadedDocument(invoice.ettn, f"qnb-{invoice.ettn}.pdf", content, "application/pdf")

    def list_active_mailbox_labels(self, credentials: QnbConnectionCredentials) -> list[QnbMailboxLabel]:
        self._login(credentials)
        body = _soap_operation(
            "getMukellefAktifEtiketList",
            f"<VKN>{escape(credentials.vkn)}</VKN>",
            namespace=QNB_CONNECTOR_NAMESPACE,
        )
        response_xml = self._post_soap(
            _service_url(credentials.base_url, "connectorService"),
            "getMukellefAktifEtiketList",
            body,
        )
        return _parse_qnb_mailbox_labels(response_xml)

    def send_outgoing_invoice_ubl(
        self,
        credentials: QnbConnectionCredentials,
        *,
        invoice_no: str,
        content: bytes,
        recipient_label: str = "",
        sender_label: str = "",
    ) -> QnbOutgoingInvoiceSendResult:
        if not str(invoice_no or "").strip():
            raise ValueError("QNB outgoing invoice number is required")
        if not bytes(content or b"").lstrip().startswith(b"<"):
            raise ValueError("QNB outgoing invoice must be UBL XML")
        self._login(credentials)
        body = _soap_operation(
            "belgeGonderExt",
            _outgoing_parameter_xml(
                credentials=credentials,
                invoice_no=invoice_no,
                content=content,
                recipient_label=recipient_label,
                sender_label=sender_label,
            ),
            namespace=QNB_CONNECTOR_NAMESPACE,
        )
        response_xml = self._post_soap(
            _service_url(credentials.base_url, "connectorService"),
            "belgeGonderExt",
            body,
        )
        document_oid = _first_element_text(response_xml, "belgeOid")
        return QnbOutgoingInvoiceSendResult(document_oid=document_oid, local_invoice_no=invoice_no)

    def get_outgoing_invoice_status(
        self,
        credentials: QnbConnectionCredentials,
        *,
        document_oid: str,
    ) -> QnbOutgoingInvoiceStatus:
        if not str(document_oid or "").strip():
            raise ValueError("QNB outgoing document OID is required")
        self._login(credentials)
        inner = "".join(
            [
                f"<vergiTcKimlikNo>{escape(credentials.vkn)}</vergiTcKimlikNo>",
                "<parametreler>",
                f"<belgeNo>{escape(document_oid)}</belgeNo>",
                "<belgeNoTipi>OID</belgeNoTipi>",
                "<belgeTuru>FATURA_UBL</belgeTuru>",
                "<donusTipiVersiyon>5.0</donusTipiVersiyon>",
                "</parametreler>",
            ]
        )
        body = _soap_operation("gidenBelgeDurumSorgulaExt", inner, namespace=QNB_CONNECTOR_NAMESPACE)
        response_xml = self._post_soap(
            _service_url(credentials.base_url, "connectorService"),
            "gidenBelgeDurumSorgulaExt",
            body,
        )
        values = _first_return_values(response_xml)
        return QnbOutgoingInvoiceStatus(
            document_oid=document_oid,
            status_code=values.get("durum", ""),
            processing_state=normalize_qnb_outgoing_processing_state(values.get("durum", "")),
            status_text=values.get("gonderimDurumu") or values.get("yanitDurumu", ""),
            description=values.get("aciklama") or values.get("gonderimCevabiDetayi", ""),
            ettn=values.get("ettn", ""),
        )

    def get_incoming_invoice_status(
        self,
        credentials: QnbConnectionCredentials,
        *,
        ettn: str,
    ) -> QnbIncomingInvoiceStatus:
        normalized_ettn = str(ettn or "").strip()
        if not normalized_ettn:
            raise ValueError("QNB incoming document ETTN is required")
        self._login(credentials)
        inner = "".join(
            [
                "<parametreler>",
                "<belgeFormati>UBL</belgeFormati><belgeTuru>FATURA</belgeTuru><belgeVersiyon>1.0</belgeVersiyon>",
                f"<donusTipiVersiyon>7.0</donusTipiVersiyon><erpKodu>{escape(credentials.erp_code)}</erpKodu>",
                f"<ettn>{escape(normalized_ettn)}</ettn>",
                f"<vergiTcKimlikNo>{escape(credentials.vkn)}</vergiTcKimlikNo>",
                "</parametreler>",
            ]
        )
        body = _soap_operation("gelenBelgeDurumSorgulaExt", inner, namespace=QNB_CONNECTOR_NAMESPACE)
        response_xml = self._post_soap(
            _service_url(credentials.base_url, "connectorService"), "gelenBelgeDurumSorgulaExt", body
        )
        values = _first_return_values(response_xml)
        response_code = values.get("yanitDurumu", "")
        cancelled_at = values.get("iptalTarihi", "")
        return QnbIncomingInvoiceStatus(
            ettn=values.get("ettn") or normalized_ettn,
            response_code=response_code,
            normalized_status=normalize_qnb_incoming_status(response_code, cancelled_at=cancelled_at),
            response_detail=values.get("yanitDetayi", ""),
            cancelled_at=cancelled_at,
        )

    def close_session(self, credentials: QnbConnectionCredentials) -> None:
        if not self._logged_in_key:
            return
        body = _soap_operation("logout", "", namespace=QNB_USER_NAMESPACE)
        try:
            self._post_soap(_service_url(credentials.base_url, "userService"), "logout", body)
        finally:
            self._logged_in_key = ""

    def _login(self, credentials: QnbConnectionCredentials, *, force: bool = False) -> None:
        login_key = f"{credentials.base_url}|{credentials.username}|{credentials.vkn}|{credentials.erp_code}"
        if not force and self._logged_in_key == login_key:
            return
        body = _soap_operation(
            "wsLogin",
            "".join(
                [
                    f"<userId>{escape(credentials.username)}</userId>",
                    f"<password>{escape(credentials.password)}</password>",
                    "<lang>tr</lang>",
                ]
            ),
            namespace=QNB_USER_NAMESPACE,
        )
        self._post_soap(_service_url(credentials.base_url, "userService"), "wsLogin", body)
        self._logged_in_key = login_key

    def _post_soap(self, url: str, action: str, operation_xml: str) -> str:
        envelope = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<soapenv:Envelope xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/">'
            f"<soapenv:Body>{operation_xml}</soapenv:Body>"
            "</soapenv:Envelope>"
        )
        for attempt in range(1, self.max_attempts + 1):
            self._throttle()
            try:
                response = self.http_client.post(
                    url,
                    content=envelope,
                    headers={"Content-Type": "text/xml; charset=utf-8", "SOAPAction": ""},
                    timeout=self.timeout,
                )
                status_code = int(getattr(response, "status_code", 200) or 200)
                if (status_code == 429 or status_code >= 500) and attempt < self.max_attempts:
                    self._sleep(0.5 * (2 ** (attempt - 1)))
                    continue
                if hasattr(response, "raise_for_status"):
                    response.raise_for_status()
                text = str(getattr(response, "text", "") or "")
                _raise_for_soap_fault(text)
                return text
            except (httpx.TimeoutException, httpx.TransportError):
                if attempt >= self.max_attempts:
                    raise
                self._sleep(0.5 * (2 ** (attempt - 1)))
        raise ValueError("QNB SOAP request exhausted retry attempts")

    def _throttle(self) -> None:
        if self.min_request_interval <= 0:
            return
        now = self._monotonic()
        remaining = self.min_request_interval - (now - self._last_request_at)
        if self._last_request_at and remaining > 0:
            self._sleep(remaining)
            now = self._monotonic()
        self._last_request_at = now


def mask_qnb_username(value: str) -> str:
    text = str(value or "")
    if len(text) <= 2:
        return "*" * len(text)
    return f"{text[0]}{'*' * max(len(text) - 2, 0)}{text[-1]}"


def _service_url(base_url: str, service_name: str) -> str:
    base = str(base_url or "").strip().rstrip("/")
    if base.endswith("/userService") or base.endswith("/connectorService"):
        return f"{base.rsplit('/', 1)[0]}/{service_name}"
    return f"{base}/{service_name}"


def _soap_operation(name: str, inner_xml: str, *, namespace: str) -> str:
    return f'<qnb:{name} xmlns:qnb="{namespace}">{inner_xml}</qnb:{name}>'


def _incoming_parameter_xml(
    *,
    credentials: QnbConnectionCredentials,
    start_date: str = "",
    end_date: str = "",
    cursor: str = "",
    ettn: str = "",
    document_format: str = "",
) -> str:
    fields = [
        ("vergiTcKimlikNo", credentials.vkn),
        ("belgeTuru", "FATURA"),
        ("erpKodu", credentials.erp_code),
    ]
    if cursor:
        fields.append(("sonAlinanBelgeSiraNumarasi", cursor))
    if start_date:
        fields.append(("gelisTarihiBaslangic", start_date))
    if end_date:
        fields.append(("gelisTarihiBitis", end_date))
    if ettn:
        fields.append(("ettn", ettn))
    if document_format:
        fields.append(("belgeFormati", document_format))
    inner = "".join(f"<{name}>{escape(str(value or ''))}</{name}>" for name, value in fields)
    return f"<parametreler>{inner}</parametreler>"


def _outgoing_parameter_xml(
    *,
    credentials: QnbConnectionCredentials,
    invoice_no: str,
    content: bytes,
    recipient_label: str = "",
    sender_label: str = "",
) -> str:
    fields = [
        ("alanEtiket", recipient_label),
        ("belgeHash", hashlib.md5(content).hexdigest()),  # noqa: S324 - provider contract requires MD5
        ("belgeNo", invoice_no),
        ("belgeTuru", "FATURA_UBL"),
        ("belgeVersiyon", "1.0"),
        ("erpKodu", credentials.erp_code),
        ("gonderenEtiket", sender_label),
        ("mimeType", "application/xml"),
        ("vergiTcKimlikNo", credentials.vkn),
        ("veri", base64.b64encode(content).decode("ascii")),
    ]
    inner = "".join(
        f"<{name}>{escape(str(value or ''))}</{name}>"
        for name, value in fields
        if str(value or "")
    )
    return f"<parametreler>{inner}</parametreler>"


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1] if "}" in tag else tag


def _children_by_local_name(element) -> dict[str, str]:
    values: dict[str, str] = {}
    for child in list(element):
        values[_local_name(str(child.tag))] = (child.text or "").strip()
    return values


def _parse_xml(text: str):
    try:
        return ElementTree.fromstring(text.encode("utf-8"))
    except ElementTree.ParseError as exc:
        raise ValueError("QNB SOAP response could not be parsed") from exc


def _raise_for_soap_fault(text: str) -> None:
    root = _parse_xml(text)
    for element in root.iter():
        if _local_name(str(element.tag)).lower() in {"faultstring", "message"} and (element.text or "").strip():
            raise ValueError((element.text or "").strip())


def _first_return_text(text: str) -> str:
    root = _parse_xml(text)
    for element in root.iter():
        if _local_name(str(element.tag)) == "return" and (element.text or "").strip():
            return (element.text or "").strip()
    raise ValueError("QNB SOAP response did not include a return payload")


def _first_element_text(text: str, name: str) -> str:
    root = _parse_xml(text)
    for element in root.iter():
        if _local_name(str(element.tag)) == name and (element.text or "").strip():
            return (element.text or "").strip()
    raise ValueError(f"QNB SOAP response did not include {name}")


def _first_return_values(text: str) -> dict[str, str]:
    root = _parse_xml(text)
    for element in root.iter():
        if _local_name(str(element.tag)) == "return":
            return _children_by_local_name(element)
    raise ValueError("QNB SOAP response did not include a return payload")


def _parse_qnb_mailbox_labels(text: str) -> list[QnbMailboxLabel]:
    root = _parse_xml(text)
    labels: list[QnbMailboxLabel] = []
    for element in root.iter():
        if _local_name(str(element.tag)) != "return":
            continue
        values = _children_by_local_name(element)
        label = values.get("etiket", "")
        if not label:
            continue
        labels.append(
            QnbMailboxLabel(
                label=label,
                kind=values.get("tip", ""),
                opened_at=values.get("acilisZamani", ""),
            )
        )
    return labels


def normalize_qnb_outgoing_processing_state(value: str) -> str:
    return {
        "1": "received",
        "2": "processing_error",
        "3": "processed",
    }.get(str(value or "").strip(), "unknown")


def qnb_outgoing_review_severity(processing_state: str) -> str:
    return {"processed": "ok", "received": "info", "processing_error": "error", "unknown": "warning"}.get(
        str(processing_state or ""), "warning"
    )


def normalize_qnb_incoming_status(response_code: str, *, cancelled_at: str = "") -> str:
    if str(cancelled_at or "").strip():
        return "cancelled"
    return {"-1": "received", "0": "received", "1": "rejected", "2": "accepted"}.get(
        str(response_code or "").strip(), "unknown"
    )


def _sequence_after(value: str, cursor: str) -> bool:
    left = str(value or "").strip()
    right = str(cursor or "").strip()
    if left.isdigit() and right.isdigit():
        return int(left) > int(right)
    return left > right


def _parse_qnb_invoice_summaries(text: str, *, require_sequence: bool = False) -> list[QnbInvoiceSummary]:
    root = _parse_xml(text)
    invoices: list[QnbInvoiceSummary] = []
    for element in root.iter():
        if _local_name(str(element.tag)) != "return":
            continue
        values = _children_by_local_name(element)
        ettn = values.get("ettn", "")
        invoice_no = values.get("belgeNo", "")
        if not ettn and not invoice_no:
            continue
        sequence_no = values.get("belgeSiraNo", "").strip()
        if require_sequence and not sequence_no:
            raise ValueError("QNB incoming invoice response omitted belgeSiraNo")
        invoices.append(
            QnbInvoiceSummary(
                ettn=ettn,
                invoice_no=invoice_no,
                sequence_no=sequence_no,
                issue_date=values.get("belgeTarihi", ""),
                supplier_tax_id=values.get("gonderenVknTckn", ""),
                supplier_title=values.get("saticiUnvan") or values.get("gonderenIsim", ""),
                payable_total=values.get("payableAmount", ""),
                qnb_status=values.get("yanitDurumu") or values.get("yanitDetayi", ""),
            )
        )
    return invoices


def _decode_qnb_download_payload(encoded: str, *, expected_suffix: str = ".xml") -> bytes:
    try:
        decoded = base64.b64decode(str(encoded or "").strip(), validate=True)
    except Exception as exc:
        raise ValueError("QNB download payload is not valid base64") from exc
    if len(decoded) > QNB_MAX_COMPRESSED_BYTES:
        raise ValueError("QNB download payload exceeds compressed size limit")
    if expected_suffix == ".xml" and decoded.lstrip().startswith(b"<"):
        if len(decoded) > QNB_MAX_UNCOMPRESSED_BYTES:
            raise ValueError("QNB XML payload exceeds size limit")
        return decoded
    try:
        with zipfile.ZipFile(io.BytesIO(decoded)) as archive:
            entries = [entry for entry in archive.infolist() if not entry.is_dir()]
            if len(entries) > QNB_MAX_ZIP_ENTRIES:
                raise ValueError("QNB download zip includes too many files")
            for entry in entries:
                path = Path(entry.filename)
                if path.is_absolute() or ".." in path.parts:
                    raise ValueError("QNB download zip includes an unsafe path")
                if entry.file_size > QNB_MAX_UNCOMPRESSED_BYTES:
                    raise ValueError("QNB download zip entry exceeds size limit")
            matching_entries = [entry for entry in entries if entry.filename.lower().endswith(expected_suffix)]
            if len(matching_entries) != 1:
                label = "XML" if expected_suffix == ".xml" else expected_suffix.upper().lstrip(".")
                raise ValueError(f"QNB download zip must include exactly one {label} document")
            content = archive.read(matching_entries[0])
            if expected_suffix == ".pdf" and not content.startswith(b"%PDF-"):
                raise ValueError("QNB PDF payload has an invalid header")
            return content
    except zipfile.BadZipFile as exc:
        raise ValueError("QNB download payload is neither XML nor a zip archive") from exc


def _redacted_error_message(exc: Exception) -> str:
    text = str(exc)
    return text if len(text) <= 240 else f"{text[:237]}..."


def public_qnb_connection_payload(record: dict[str, object] | None) -> dict[str, object]:
    source = record or {}
    return {
        "client_id": str(source.get("client_id") or ""),
        "provider": str(source.get("provider") or SOURCE_PROVIDER),
        "username": mask_qnb_username(str(source.get("username") or "")),
        "status": str(source.get("status") or "missing"),
        "last_tested_at": str(source.get("last_tested_at") or ""),
        "last_error": str(source.get("last_error") or ""),
        "environment": str(source.get("environment") or ""),
        "has_credential": bool(source.get("credential_ciphertext")),
        "sync_enabled": str(source.get("status") or "") == "active",
    }


class QnbSyncService:
    def __init__(
        self,
        *,
        store,
        document_storage_path: Path,
        adapter: QnbEfaturaAdapter,
        max_pages: int = 20,
        max_documents: int = 100,
    ) -> None:
        self.store = store
        self.document_storage_path = Path(document_storage_path)
        self.adapter = adapter
        self.max_pages = max(max_pages, 1)
        self.max_documents = max(max_documents, 1)

    def sync_incoming_invoices(
        self,
        *,
        client_id: str,
        credentials: QnbConnectionCredentials,
        start_date: str = "",
        end_date: str = "",
        cursor: str = "",
    ) -> dict[str, object]:
        sync_run_id = str(uuid4())
        mode = "backfill" if start_date or end_date else "cursor"
        if mode == "backfill" and cursor:
            raise ValueError("QNB backfill dates cannot be combined with cursor")
        current_cursor = str(cursor or "").strip()
        result = {
            "sync_run_id": sync_run_id,
            "client_id": client_id,
            "mode": mode,
            "status": "running",
            "page_count": 0,
            "listed_count": 0,
            "downloaded_count": 0,
            "skipped_duplicate_count": 0,
            "queued_processing_count": 0,
            "failed_count": 0,
            "cursor_before": current_cursor,
            "cursor_after": current_cursor,
            "backfill_truncated": False,
            "errors": [],
        }
        for _ in range(self.max_pages):
            page = self._list_page(
                credentials=credentials,
                start_date=start_date if mode == "backfill" else "",
                end_date=end_date if mode == "backfill" else "",
                cursor=current_cursor if mode == "cursor" else "",
            )
            result["page_count"] += 1
            result["listed_count"] += len(page.items)
            page_failed = False
            for invoice in page.items:
                if int(result["downloaded_count"]) >= self.max_documents:
                    result["status"] = "partial_completed"
                    result["limit_reached"] = True
                    break
                if self._is_duplicate(client_id=client_id, invoice=invoice):
                    result["skipped_duplicate_count"] += 1
                    self._record_operation(client_id, "qnb_duplicate_skipped", sync_run_id, {"ettn": invoice.ettn})
                    continue
                identity_key = _qnb_identity_key(invoice)
                claimed = True
                if identity_key and hasattr(self.store, "claim_qnb_document_identity"):
                    claimed = bool(
                        self.store.claim_qnb_document_identity(
                            client_id=client_id,
                            identity_key=identity_key,
                            metadata={"ettn": invoice.ettn, "invoice_no": invoice.invoice_no},
                        )
                    )
                if not claimed:
                    result["skipped_duplicate_count"] += 1
                    continue
                try:
                    downloaded = self.adapter.download_incoming_invoice_ubl(credentials, invoice)
                    saved = self._store_downloaded_document(
                        client_id=client_id,
                        invoice=invoice,
                        downloaded=downloaded,
                        sync_run_id=sync_run_id,
                    )
                    self._queue_processing_job(client_id=client_id, document=saved)
                    result["downloaded_count"] += 1
                    result["queued_processing_count"] += 1
                except Exception as exc:  # pragma: no cover - covered through public failed_count behavior later
                    page_failed = True
                    result["failed_count"] += 1
                    result["errors"].append(
                        {
                            "ettn": invoice.ettn,
                            "code": qnb_safe_error_code(exc),
                            "message": _redacted_error_message(exc),
                        }
                    )
                    if identity_key and hasattr(self.store, "release_qnb_document_identity"):
                        self.store.release_qnb_document_identity(client_id=client_id, identity_key=identity_key)
            if result.get("limit_reached"):
                break
            if page_failed:
                result["status"] = "partial_failed"
                break
            if mode == "cursor" and page.last_sequence_no:
                current_cursor = page.last_sequence_no
                result["cursor_after"] = current_cursor
                if hasattr(self.store, "save_qnb_sync_cursor"):
                    self.store.save_qnb_sync_cursor(client_id=client_id, cursor=current_cursor)
            if not page.has_more:
                result["status"] = "completed"
                break
            if mode == "backfill":
                result["status"] = "partial_failed"
                result["backfill_truncated"] = True
                break
        else:
            result["status"] = "partial_failed"
            result["errors"].append({"message": "QNB sync reached max page limit"})
        if result["status"] == "running":
            result["status"] = "completed"
        if hasattr(self.adapter, "close_session"):
            try:
                self.adapter.close_session(credentials)
            except Exception as exc:
                result["status"] = "partial_failed"
                result["errors"].append(
                    {"code": "logout_failed", "message": _redacted_error_message(exc)}
                )
        self._record_operation(client_id, "qnb_sync_completed", sync_run_id, {k: v for k, v in result.items() if k != "errors"})
        return result

    def _list_page(
        self,
        *,
        credentials: QnbConnectionCredentials,
        start_date: str,
        end_date: str,
        cursor: str,
    ) -> QnbIncomingInvoicePage:
        if hasattr(self.adapter, "list_incoming_page"):
            return self.adapter.list_incoming_page(
                credentials,
                start_date=start_date,
                end_date=end_date,
                cursor=cursor,
            )
        invoices = self.adapter.list_incoming_invoices(
            credentials,
            start_date=start_date,
            end_date=end_date,
            cursor=cursor,
        )
        return QnbIncomingInvoicePage(
            items=tuple(invoices),
            last_sequence_no=invoices[-1].sequence_no if invoices else "",
            has_more=False,
        )

    def _is_duplicate(self, *, client_id: str, invoice: QnbInvoiceSummary) -> bool:
        workspace = self.store.get_workspace(client_id)
        identity_key = _fallback_identity_key(invoice)
        for document in workspace.get("uploaded_documents", []) or []:
            if str(document.get("source_provider") or "") != SOURCE_PROVIDER:
                continue
            if invoice.ettn and str(document.get("source_external_uuid") or "") == invoice.ettn:
                return True
            if identity_key and str(document.get("source_identity_key") or "") == identity_key:
                return True
        return False

    def _store_downloaded_document(
        self,
        *,
        client_id: str,
        invoice: QnbInvoiceSummary,
        downloaded: QnbDownloadedDocument,
        sync_run_id: str,
    ) -> dict[str, object]:
        content_sha256 = hashlib.sha256(downloaded.content).hexdigest()
        stored = store_document_content(
            base_dir=self.document_storage_path,
            client_id=client_id,
            file_name=downloaded.file_name,
            document_type="einvoice_xml",
            intake_category="purchase_invoice",
            uploaded_by="qnb_esolutions",
            content=downloaded.content,
        )
        payload = asdict(stored)
        payload.update(
            {
                "source_provider": SOURCE_PROVIDER,
                "source_direction": SOURCE_DIRECTION,
                "source_external_uuid": invoice.ettn,
                "source_invoice_no": invoice.invoice_no,
                "source_qnb_sequence_no": invoice.sequence_no,
                "source_issue_date": invoice.issue_date,
                "source_supplier_tax_id": invoice.supplier_tax_id,
                "source_supplier_title": invoice.supplier_title,
                "source_payable_total": invoice.payable_total,
                "source_qnb_status": invoice.qnb_status,
                "source_sync_run_id": sync_run_id,
                "source_content_sha256": content_sha256,
                "source_identity_key": _fallback_identity_key(invoice),
                "source_pulled_at": datetime.now(UTC).isoformat(timespec="seconds"),
            }
        )
        saved = self.store.save_uploaded_document(client_id=client_id, document=payload)
        self.store.record_document_pipeline_event(
            client_id=client_id,
            document_ref=str(saved["document_ref"]),
            step="qnb_ubl_stored",
            status="ok",
            message_tr="QNB gelen e-Fatura UBL olarak kaydedildi.",
            debug_code="qnb_ubl_stored",
            details={
                "source_provider": SOURCE_PROVIDER,
                "source_external_uuid": invoice.ettn,
                "source_sync_run_id": sync_run_id,
                "source_content_sha256": content_sha256,
            },
        )
        return saved

    def _queue_processing_job(self, *, client_id: str, document: dict[str, object]) -> dict[str, object]:
        job = self.store.create_processing_job(
            client_id=client_id,
            document_ref=str(document["document_ref"]),
            document_type="einvoice_xml",
            parser_kind=parser_kind_for_document_type("einvoice_xml"),
            intake_category="purchase_invoice",
        )
        self.store.record_document_pipeline_event(
            client_id=client_id,
            document_ref=str(document["document_ref"]),
            step="qnb_processing_queued",
            status="ok",
            message_tr="QNB belgesi isleme kuyruguna alindi.",
            debug_code="qnb_processing_queued",
            details={"processing_job_id": str(job.get("id") or "")},
        )
        return job

    def _record_operation(self, client_id: str, event_type: str, sync_run_id: str, metadata: dict[str, object]) -> None:
        if not hasattr(self.store, "record_operation_event"):
            return
        self.store.record_operation_event(
            client_id=client_id,
            event={
                "event_type": event_type,
                "status": "ok",
                "message": event_type,
                "metadata": {"source_provider": SOURCE_PROVIDER, "source_sync_run_id": sync_run_id, **metadata},
            },
        )


def _fallback_identity_key(invoice: QnbInvoiceSummary) -> str:
    parts = [invoice.invoice_no, invoice.issue_date, invoice.supplier_tax_id, invoice.payable_total]
    if not all(str(part or "").strip() for part in parts):
        return ""
    return "|".join(str(part).strip() for part in parts)


def _qnb_identity_key(invoice: QnbInvoiceSummary) -> str:
    if str(invoice.ettn or "").strip():
        return f"ettn:{str(invoice.ettn).strip()}"
    fallback = _fallback_identity_key(invoice)
    return f"fallback:{fallback}" if fallback else ""


def qnb_safe_error_code(exc: Exception) -> str:
    if isinstance(exc, httpx.TimeoutException):
        return "timeout"
    if isinstance(exc, httpx.TransportError):
        return "transport_error"
    text = str(exc or "").lower()
    if "auth" in text or "kullanıcı" in text or "kullanici" in text or "şifre" in text or "sifre" in text:
        return "auth_failed"
    if "base64" in text or "zip" in text or "xml" in text or "belgesirano" in text:
        return "invalid_provider_payload"
    if "429" in text or "rate" in text or "limit" in text:
        return "rate_limited"
    return "provider_error"


class QnbConnectionService:
    def __init__(
        self,
        *,
        store,
        document_storage_path: Path,
        adapter: QnbEfaturaAdapter | None = None,
        credential_cipher: QnbCredentialCipher | None = None,
    ) -> None:
        self.store = store
        self.document_storage_path = Path(document_storage_path)
        self.adapter = adapter or FakeQnbEfaturaAdapter()
        self.credential_cipher = credential_cipher or QnbCredentialCipher.from_env()

    def save_connection(
        self,
        *,
        client_id: str,
        base_url: str,
        username: str,
        password: str,
        vkn: str,
        erp_code: str = "",
        environment: str = "test",
        actor_user_id: str = "",
    ) -> dict[str, object]:
        base_url, environment = validate_qnb_endpoint(base_url, environment)
        platform_erp_code = qnb_platform_erp_code()
        existing = self.store.get_qnb_connection(client_id=client_id) or {}
        effective_password = str(password or "")
        credential_ciphertext = ""
        if not effective_password:
            credential_ciphertext = str(existing.get("credential_ciphertext") or "")
            if not credential_ciphertext:
                raise ValueError("QNB password is required for a new connection")
            effective_password = self.credential_cipher.decrypt(credential_ciphertext)
        else:
            credential_ciphertext = self.credential_cipher.encrypt(effective_password)
        credentials = QnbConnectionCredentials(
            base_url=base_url,
            username=username,
            password=effective_password,
            vkn=vkn,
            erp_code=platform_erp_code,
        )
        test = self.adapter.test_connection(credentials)
        record = self.store.save_qnb_connection(
            client_id=client_id,
            connection={
                "base_url": base_url,
                "username": username,
                "credential_ciphertext": credential_ciphertext,
                "vkn": vkn,
                "environment": environment,
                "erp_code": platform_erp_code,
                "status": test.status,
                "last_error": "" if test.ok else test.status,
                "last_tested_at": datetime.now(UTC).isoformat(timespec="seconds"),
                "last_success_at": datetime.now(UTC).isoformat(timespec="seconds") if test.ok else str(existing.get("last_success_at") or ""),
            },
        )
        self._record_connection_audit(client_id, actor_user_id, "qnb_connection_saved")
        return public_qnb_connection_payload(record)

    def disable_connection(self, *, client_id: str, actor_user_id: str = "") -> dict[str, object]:
        existing = self.store.get_qnb_connection(client_id=client_id)
        if not existing:
            raise ValueError("QNB connection was not found")
        record = self.store.save_qnb_connection(
            client_id=client_id,
            connection={**existing, "status": "disabled", "last_error": ""},
        )
        self._record_connection_audit(client_id, actor_user_id, "qnb_connection_disabled")
        return public_qnb_connection_payload(record)

    def public_connection(self, *, client_id: str) -> dict[str, object]:
        return public_qnb_connection_payload(self.store.get_qnb_connection(client_id=client_id))

    def sync_incoming_invoices(self, *, client_id: str, start_date: str = "", end_date: str = "", max_documents: int = 100) -> dict[str, object]:
        credentials = self._active_credentials(client_id)
        cursor = ""
        if not start_date and not end_date and hasattr(self.store, "get_qnb_sync_cursor"):
            cursor = str(self.store.get_qnb_sync_cursor(client_id=client_id) or "")
        result = QnbSyncService(
            store=self.store,
            document_storage_path=self.document_storage_path,
            adapter=self.adapter,
            max_documents=max_documents,
        ).sync_incoming_invoices(
            client_id=client_id,
            credentials=credentials,
            start_date=start_date,
            end_date=end_date,
            cursor=cursor,
        )
        if hasattr(self.store, "save_qnb_sync_run"):
            self.store.save_qnb_sync_run(client_id=client_id, sync_run=result)
        return result

    def reconcile_outgoing_invoice(self, *, client_id: str, document_oid: str, invoice_no: str = "") -> dict[str, object]:
        oid = str(document_oid or "").strip()
        if not oid:
            raise ValueError("QNB outgoing document OID is required")
        credentials = self._active_credentials(client_id)
        previous = self.store.get_qnb_outgoing_invoice(client_id=client_id, document_oid=oid) or {}
        try:
            status = self.adapter.get_outgoing_invoice_status(credentials, document_oid=oid)
            snapshot = {
                "snapshot_id": str(uuid4()),
                "document_oid": oid,
                "invoice_no": str(invoice_no or previous.get("invoice_no") or ""),
                "ettn": status.ettn,
                "status_code": status.status_code,
                "processing_state": status.processing_state,
                "status_text": status.status_text,
                "description": status.description,
                "checked_at": datetime.now(UTC).isoformat(timespec="seconds"),
                "source": "qnb_status_query",
                "severity": qnb_outgoing_review_severity(status.processing_state),
                "changed": bool(previous) and previous.get("processing_state") != status.processing_state,
                "previous_processing_state": str(previous.get("processing_state") or ""),
            }
            self.store.append_qnb_outgoing_status_snapshot(client_id=client_id, snapshot=snapshot)
            current = self.store.save_qnb_outgoing_invoice(client_id=client_id, invoice=snapshot)
            return {**current, "snapshot_id": snapshot["snapshot_id"]}
        finally:
            if hasattr(self.adapter, "close_session"):
                self.adapter.close_session(credentials)

    def download_incoming_pdf(self, *, client_id: str, ettn: str) -> dict[str, object]:
        normalized_ettn = str(ettn or "").strip()
        workspace = self.store.get_workspace(client_id)
        source = next((item for item in workspace.get("uploaded_documents", []) if str(item.get("source_external_uuid") or item.get("source_qnb_ettn") or "") == normalized_ettn and str(item.get("source_provider") or "") == SOURCE_PROVIDER), None)
        if not source:
            raise ValueError("QNB incoming document was not found in the client workspace")
        existing = next((item for item in workspace.get("uploaded_documents", []) if str(item.get("source_parent_document_ref") or "") == str(source.get("document_ref") or "") and str(item.get("source_evidence_kind") or "") == "qnb_pdf"), None)
        if existing:
            return existing
        credentials = self._active_credentials(client_id)
        invoice = QnbInvoiceSummary(normalized_ettn, str(source.get("source_invoice_no") or ""), str(source.get("source_qnb_sequence_no") or ""), str(source.get("source_issue_date") or ""), str(source.get("source_supplier_tax_id") or ""), str(source.get("source_supplier_title") or ""), str(source.get("source_payable_total") or ""))
        try:
            downloaded = self.adapter.download_incoming_invoice_pdf(credentials, invoice)
            stored = store_document_content(base_dir=self.document_storage_path, client_id=client_id, file_name=downloaded.file_name, document_type="invoice", intake_category="purchase_invoice", uploaded_by="qnb_esolutions", content=downloaded.content)
            payload = {**asdict(stored), "source_provider": SOURCE_PROVIDER, "source_external_uuid": normalized_ettn, "source_parent_document_ref": str(source.get("document_ref") or ""), "source_evidence_kind": "qnb_pdf", "source_content_sha256": hashlib.sha256(downloaded.content).hexdigest(), "source_pulled_at": datetime.now(UTC).isoformat(timespec="seconds"), "processing_status": "evidence_only"}
            return self.store.save_uploaded_document(client_id=client_id, document=payload)
        finally:
            if hasattr(self.adapter, "close_session"):
                self.adapter.close_session(credentials)

    def reconcile_outgoing_invoices(self, *, client_id: str, document_oids: list[str] | None = None) -> dict[str, object]:
        requested = [str(item).strip() for item in (document_oids or []) if str(item).strip()]
        if not requested:
            requested = [str(item.get("document_oid") or "") for item in self.store.list_qnb_outgoing_invoices(client_id=client_id)]
        results: list[dict[str, object]] = []
        errors: list[dict[str, str]] = []
        for oid in dict.fromkeys(filter(None, requested)):
            try:
                results.append(self.reconcile_outgoing_invoice(client_id=client_id, document_oid=oid))
            except Exception as exc:
                errors.append({"document_oid": oid, "code": qnb_safe_error_code(exc)})
        return {
            "status": "completed" if not errors else "partial_failed",
            "requested_count": len(requested),
            "updated_count": len(results),
            "error_count": len(errors),
            "items": results,
            "errors": errors,
        }

    def reconcile_incoming_invoice(self, *, client_id: str, ettn: str) -> dict[str, object]:
        normalized_ettn = str(ettn or "").strip()
        if not normalized_ettn:
            raise ValueError("QNB incoming document ETTN is required")
        credentials = self._active_credentials(client_id)
        documents = self.store.get_workspace(client_id).get("uploaded_documents", [])
        document = next(
            (
                item for item in documents
                if str(item.get("source_provider") or "") == SOURCE_PROVIDER
                and str(item.get("source_qnb_ettn") or "") == normalized_ettn
            ),
            None,
        )
        if not document:
            raise ValueError("QNB incoming document was not found in the client workspace")
        previous_status = str(document.get("source_qnb_normalized_status") or "")
        try:
            status = self.adapter.get_incoming_invoice_status(credentials, ettn=normalized_ettn)
            checked_at = datetime.now(UTC).isoformat(timespec="seconds")
            changed = bool(previous_status) and previous_status != status.normalized_status
            needs_review = status.normalized_status in {"rejected", "cancelled", "unknown"}
            snapshot = {
                "snapshot_id": str(uuid4()),
                "document_ref": str(document.get("document_ref") or document.get("document_id") or ""),
                "ettn": normalized_ettn,
                "response_code": status.response_code,
                "normalized_status": status.normalized_status,
                "response_detail": status.response_detail,
                "cancelled_at": status.cancelled_at,
                "checked_at": checked_at,
                "source": "qnb_incoming_status_query",
                "changed": changed,
                "previous_status": previous_status,
                "review_required": needs_review,
            }
            self.store.append_qnb_incoming_status_snapshot(client_id=client_id, snapshot=snapshot)
            updated = self.store.save_uploaded_document(
                client_id=client_id,
                document={
                    **document,
                    "source_qnb_status": status.response_code,
                    "source_qnb_normalized_status": status.normalized_status,
                    "source_qnb_status_detail": status.response_detail,
                    "source_qnb_status_checked_at": checked_at,
                    "source_qnb_status_changed": changed,
                    "qnb_review_required": needs_review,
                    "automation_hold": needs_review,
                    "automation_hold_reason": "qnb_status_review_required" if needs_review else "",
                },
            )
            self.store.record_document_pipeline_event(
                client_id=client_id,
                document_ref=str(updated.get("document_ref") or snapshot["document_ref"]),
                step="qnb_status_reconciled",
                status="warning" if needs_review else "ok",
                message_tr={
                    "accepted": "QNB durumu: kabul edildi.",
                    "rejected": "QNB durumu: reddedildi; müşavir kontrolü gerekli.",
                    "cancelled": "QNB durumu: iptal edildi; müşavir kontrolü gerekli.",
                    "received": "QNB durumu: belge alındı, cevap bekleniyor.",
                    "unknown": "QNB durumu doğrulanamadı; müşavir kontrolü gerekli.",
                }.get(status.normalized_status, "QNB durumu güncellendi."),
                debug_code=f"qnb_status_{status.normalized_status}",
                details={
                    "normalized_status": status.normalized_status,
                    "response_code": status.response_code,
                    "changed": changed,
                    "checked_at": checked_at,
                },
            )
            return {**snapshot, "document_ref": str(updated.get("document_ref") or snapshot["document_ref"])}
        finally:
            if hasattr(self.adapter, "close_session"):
                self.adapter.close_session(credentials)

    def reconcile_incoming_invoices(self, *, client_id: str, ettns: list[str] | None = None) -> dict[str, object]:
        requested = [str(item).strip() for item in (ettns or []) if str(item).strip()]
        if not requested:
            requested = [
                str(item.get("source_qnb_ettn") or "")
                for item in self.store.get_workspace(client_id).get("uploaded_documents", [])
                if str(item.get("source_provider") or "") == SOURCE_PROVIDER
            ]
        items: list[dict[str, object]] = []
        errors: list[dict[str, str]] = []
        for ettn in dict.fromkeys(filter(None, requested)):
            try:
                items.append(self.reconcile_incoming_invoice(client_id=client_id, ettn=ettn))
            except Exception as exc:
                errors.append({"ettn": ettn, "code": qnb_safe_error_code(exc)})
        return {
            "status": "completed" if not errors else "partial_failed",
            "requested_count": len(requested),
            "updated_count": len(items),
            "error_count": len(errors),
            "items": items,
            "errors": errors,
        }

    def _active_credentials(self, client_id: str) -> QnbConnectionCredentials:
        connection = self.store.get_qnb_connection(client_id=client_id)
        if not connection or str(connection.get("status") or "") != "active":
            raise ValueError("active QNB connection is required before status reconciliation")
        return QnbConnectionCredentials(
            base_url=str(connection.get("base_url") or ""),
            username=str(connection.get("username") or ""),
            password=self.credential_cipher.decrypt(str(connection.get("credential_ciphertext") or "")),
            vkn=str(connection.get("vkn") or ""),
            erp_code=str(connection.get("erp_code") or ""),
        )

    def _record_connection_audit(self, client_id: str, actor_user_id: str, event_type: str) -> None:
        if not hasattr(self.store, "record_operation_event"):
            return
        self.store.record_operation_event(
            client_id=client_id,
            event={
                "event_type": event_type,
                "status": "ok",
                "message": event_type,
                "actor_user_id": str(actor_user_id or ""),
                "target_client_id": client_id,
                "metadata": {"source_provider": SOURCE_PROVIDER},
            },
        )
