from __future__ import annotations

import base64
from dataclasses import asdict, dataclass
import hashlib
import io
from pathlib import Path
from typing import Mapping, Protocol
from xml.etree import ElementTree
from xml.sax.saxutils import escape
from uuid import uuid4
import zipfile

import httpx

from app.domain.document_uploads import store_document_content
from app.workflows.document_processing import parser_kind_for_document_type


SOURCE_PROVIDER = "qnb_esolutions"
SOURCE_DIRECTION = "incoming_efatura"
QNB_USER_NAMESPACE = "http://service.csap.cs.com.tr/"
QNB_CONNECTOR_NAMESPACE = "http://service.connector.uut.cs.com.tr/"


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


class QnbEfaturaAdapter(Protocol):
    def test_connection(self, credentials: QnbConnectionCredentials) -> QnbConnectionTestResult:
        ...


def build_qnb_adapter_from_env(env: Mapping[str, str]) -> QnbEfaturaAdapter:
    selected = str(env.get("FISORA_QNB_ADAPTER") or env.get("FISORA_QNB_EFATURA_ADAPTER") or "fake").strip().lower()
    if selected in {"soap", "qnb_soap", "real"}:
        return QnbSoapEfaturaAdapter()
    return FakeQnbEfaturaAdapter()

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


class FakeQnbEfaturaAdapter:
    def __init__(self, *, invoices: list[QnbInvoiceSummary] | None = None, downloads: dict[str, bytes] | None = None) -> None:
        self.invoices = invoices or []
        self.downloads = downloads or {}

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
        return list(self.invoices)

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


class QnbSoapEfaturaAdapter:
    def __init__(self, *, http_client=None, timeout: int = 30) -> None:
        self.http_client = http_client or httpx.Client(timeout=timeout)
        self.timeout = timeout
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
        return _parse_qnb_invoice_summaries(response_xml)

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
        response = self.http_client.post(
            url,
            content=envelope,
            headers={"Content-Type": "text/xml; charset=utf-8", "SOAPAction": ""},
            timeout=self.timeout,
        )
        if hasattr(response, "raise_for_status"):
            response.raise_for_status()
        text = str(getattr(response, "text", "") or "")
        _raise_for_soap_fault(text)
        return text


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


def _parse_qnb_invoice_summaries(text: str) -> list[QnbInvoiceSummary]:
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
        invoices.append(
            QnbInvoiceSummary(
                ettn=ettn,
                invoice_no=invoice_no,
                sequence_no=values.get("belgeSiraNo", ""),
                issue_date=values.get("belgeTarihi", ""),
                supplier_tax_id=values.get("gonderenVknTckn", ""),
                supplier_title=values.get("saticiUnvan") or values.get("gonderenIsim", ""),
                payable_total=values.get("payableAmount", ""),
                qnb_status=values.get("yanitDurumu") or values.get("yanitDetayi", ""),
            )
        )
    return invoices


def _decode_qnb_download_payload(encoded: str) -> bytes:
    try:
        decoded = base64.b64decode(str(encoded or "").strip())
    except Exception as exc:
        raise ValueError("QNB download payload is not valid base64") from exc
    if decoded.lstrip().startswith(b"<"):
        return decoded
    try:
        with zipfile.ZipFile(io.BytesIO(decoded)) as archive:
            names = [name for name in archive.namelist() if not name.endswith("/")]
            xml_name = next((name for name in names if name.lower().endswith(".xml")), names[0] if names else "")
            if not xml_name:
                raise ValueError("QNB download zip did not include a document")
            return archive.read(xml_name)
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
        "sync_enabled": str(source.get("status") or "") == "active",
    }


class QnbSyncService:
    def __init__(
        self,
        *,
        store,
        document_storage_path: Path,
        adapter: QnbEfaturaAdapter,
    ) -> None:
        self.store = store
        self.document_storage_path = Path(document_storage_path)
        self.adapter = adapter

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
        invoices = self.adapter.list_incoming_invoices(
            credentials,
            start_date=start_date,
            end_date=end_date,
            cursor=cursor,
        )
        result = {
            "sync_run_id": sync_run_id,
            "client_id": client_id,
            "listed_count": len(invoices),
            "downloaded_count": 0,
            "skipped_duplicate_count": 0,
            "queued_processing_count": 0,
            "failed_count": 0,
            "errors": [],
        }
        for invoice in invoices:
            if self._is_duplicate(client_id=client_id, invoice=invoice):
                result["skipped_duplicate_count"] += 1
                self._record_operation(client_id, "qnb_duplicate_skipped", sync_run_id, {"ettn": invoice.ettn})
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
                result["failed_count"] += 1
                result["errors"].append({"ettn": invoice.ettn, "message": str(exc)})
        self._record_operation(client_id, "qnb_sync_completed", sync_run_id, {k: v for k, v in result.items() if k != "errors"})
        return result

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


class QnbConnectionService:
    def __init__(
        self,
        *,
        store,
        document_storage_path: Path,
        adapter: QnbEfaturaAdapter | None = None,
    ) -> None:
        self.store = store
        self.document_storage_path = Path(document_storage_path)
        self.adapter = adapter or FakeQnbEfaturaAdapter()

    def save_connection(
        self,
        *,
        client_id: str,
        base_url: str,
        username: str,
        password: str,
        vkn: str,
        erp_code: str,
    ) -> dict[str, object]:
        credentials = QnbConnectionCredentials(
            base_url=base_url,
            username=username,
            password=password,
            vkn=vkn,
            erp_code=erp_code,
        )
        test = self.adapter.test_connection(credentials)
        record = self.store.save_qnb_connection(
            client_id=client_id,
            connection={
                "base_url": base_url,
                "username": username,
                "password": password,
                "vkn": vkn,
                "erp_code": erp_code,
                "status": test.status,
                "last_error": "" if test.ok else test.message,
            },
        )
        return public_qnb_connection_payload(record)

    def public_connection(self, *, client_id: str) -> dict[str, object]:
        return public_qnb_connection_payload(self.store.get_qnb_connection(client_id=client_id))

    def sync_incoming_invoices(self, *, client_id: str, start_date: str = "", end_date: str = "") -> dict[str, object]:
        connection = self.store.get_qnb_connection(client_id=client_id)
        if not connection or str(connection.get("status") or "") != "active":
            raise ValueError("active QNB connection is required before sync")
        credentials = QnbConnectionCredentials(
            base_url=str(connection.get("base_url") or ""),
            username=str(connection.get("username") or ""),
            password=str(connection.get("password") or ""),
            vkn=str(connection.get("vkn") or ""),
            erp_code=str(connection.get("erp_code") or ""),
        )
        result = QnbSyncService(
            store=self.store,
            document_storage_path=self.document_storage_path,
            adapter=self.adapter,
        ).sync_incoming_invoices(
            client_id=client_id,
            credentials=credentials,
            start_date=start_date,
            end_date=end_date,
        )
        if hasattr(self.store, "save_qnb_sync_run"):
            self.store.save_qnb_sync_run(client_id=client_id, sync_run=result)
        return result
