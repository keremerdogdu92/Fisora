from __future__ import annotations

import base64
from dataclasses import dataclass
import json
from typing import Mapping
from urllib.parse import urlparse
from xml.etree import ElementTree
from xml.sax.saxutils import escape

import httpx


QNB_EARSIV_NAMESPACE = "http://service.earsiv.uut.cs.com.tr/"
QNB_USER_NAMESPACE = "http://service.csap.cs.com.tr/"
QNB_EARSIV_SUCCESS_CODE = "AE00000"
QNB_EARSIV_MAX_OUTPUT_BYTES = 20 * 1024 * 1024


@dataclass(frozen=True)
class QnbEarsivCredentials:
    user_service_url: str
    service_url: str
    username: str
    password: str
    vkn: str
    erp_code: str


@dataclass(frozen=True)
class QnbEarsivConnectionTestResult:
    ok: bool
    status: str
    message: str = ""


@dataclass(frozen=True)
class QnbEarsivCreatedInvoice:
    transaction_id: str
    result_code: str
    result_text: str
    invoice_uuid: str = ""
    invoice_no: str = ""
    invoice_url: str = ""
    output_format: str = ""
    output_content: bytes = b""

    @property
    def ok(self) -> bool:
        return self.result_code == QNB_EARSIV_SUCCESS_CODE


class QnbSoapEarsivAdapter:
    def __init__(self, *, http_client=None, timeout: int = 30) -> None:
        self.http_client = http_client or httpx.Client(timeout=timeout)
        self.timeout = timeout
        self._logged_in_key = ""

    def test_connection(self, credentials: QnbEarsivCredentials) -> QnbEarsivConnectionTestResult:
        try:
            self._login(credentials, force=True)
        except Exception as exc:
            message = _safe_error_message(exc)
            lowered = message.lower()
            if "ef0556" in lowered or "mali mühür" in lowered or "e-imza" in lowered:
                return QnbEarsivConnectionTestResult(False, "portal_verification_required", message)
            if "username.pwd.mismatch" in lowered or "authentication" in lowered:
                return QnbEarsivConnectionTestResult(False, "auth_failed", message)
            return QnbEarsivConnectionTestResult(False, "connection_failed", message)
        return QnbEarsivConnectionTestResult(True, "active")

    def create_invoice_ubl(
        self,
        credentials: QnbEarsivCredentials,
        *,
        transaction_id: str,
        content: bytes,
        branch: str = "DFLT",
        cash_register: str = "DFLT",
        returned_document_format: int = 3,
        assign_invoice_number: bool | None = None,
        invoice_series: str = "",
        send_to_draft: bool | None = None,
    ) -> QnbEarsivCreatedInvoice:
        normalized_transaction_id = str(transaction_id or "").strip()
        if not normalized_transaction_id:
            raise ValueError("QNB e-Arsiv transaction id is required")
        payload = bytes(content or b"")
        if not payload.lstrip().startswith(b"<"):
            raise ValueError("QNB e-Arsiv invoice must be UBL XML")
        if returned_document_format not in {0, 2, 3, 9}:
            raise ValueError("QNB e-Arsiv returned document format must be 0, 2, 3 or 9")

        self._login(credentials)
        input_payload: dict[str, object] = {
            "islemId": normalized_transaction_id,
            "vkn": credentials.vkn,
            "sube": str(branch or "DFLT"),
            "kasa": str(cash_register or "DFLT"),
            "erpKodu": credentials.erp_code,
            "donenBelgeFormati": str(returned_document_format),
        }
        if assign_invoice_number is not None:
            input_payload["numaraVerilsinMi"] = 1 if assign_invoice_number else 0
        if invoice_series:
            input_payload["faturaSeri"] = str(invoice_series)
        if send_to_draft is not None:
            input_payload["taslagaYonlendir"] = 1 if send_to_draft else 0

        inner_xml = "".join(
            [
                f"<input>{escape(json.dumps(input_payload, ensure_ascii=False, separators=(',', ':')))}</input>",
                "<fatura>",
                "<belgeFormati>UBL</belgeFormati>",
                f"<belgeIcerigi>{base64.b64encode(payload).decode('ascii')}</belgeIcerigi>",
                "</fatura>",
            ]
        )
        response_xml = self._post_soap(
            _earsiv_service_url(credentials.service_url),
            _soap_operation("faturaOlusturExt", inner_xml, namespace=QNB_EARSIV_NAMESPACE),
        )
        return _parse_created_invoice(response_xml, transaction_id=normalized_transaction_id)

    def close_session(self, credentials: QnbEarsivCredentials) -> None:
        if not self._logged_in_key:
            return
        try:
            self._post_soap(
                credentials.user_service_url,
                _soap_operation("logout", "", namespace=QNB_USER_NAMESPACE),
            )
        finally:
            self._logged_in_key = ""

    def _login(self, credentials: QnbEarsivCredentials, *, force: bool = False) -> None:
        login_key = "|".join(
            [credentials.user_service_url, credentials.service_url, credentials.username, credentials.vkn, credentials.erp_code]
        )
        if not force and self._logged_in_key == login_key:
            return
        inner_xml = "".join(
            [
                f"<userId>{escape(credentials.username)}</userId>",
                f"<password>{escape(credentials.password)}</password>",
                "<lang>tr</lang>",
            ]
        )
        self._post_soap(
            credentials.user_service_url,
            _soap_operation("wsLogin", inner_xml, namespace=QNB_USER_NAMESPACE),
        )
        self._logged_in_key = login_key

    def _post_soap(self, url: str, operation_xml: str) -> str:
        envelope = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<soapenv:Envelope xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/">'
            f"<soapenv:Body>{operation_xml}</soapenv:Body>"
            "</soapenv:Envelope>"
        )
        response = self.http_client.post(
            str(url or "").strip(),
            content=envelope,
            headers={"Content-Type": "text/xml; charset=utf-8", "SOAPAction": ""},
            timeout=self.timeout,
        )
        text = str(getattr(response, "text", "") or "")
        _raise_for_soap_fault(text)
        if hasattr(response, "raise_for_status"):
            response.raise_for_status()
        return text


def qnb_earsiv_credentials_from_env(env: Mapping[str, str]) -> QnbEarsivCredentials:
    return QnbEarsivCredentials(
        user_service_url=str(env.get("QNB_EARSIV_USER_SERVICE_URL") or "").strip(),
        service_url=str(env.get("QNB_EARSIV_TEST_BASE_URL") or "").strip(),
        username=str(env.get("QNB_EARSIV_TEST_USERNAME") or "").strip(),
        password=str(env.get("QNB_EARSIV_TEST_PASSWORD") or ""),
        vkn=str(env.get("QNB_EARSIV_TEST_VKN") or "").strip(),
        erp_code=str(env.get("QNB_ERP_CODE") or "").strip(),
    )


def is_qnb_earsiv_test_endpoint(value: str) -> bool:
    parsed = urlparse(str(value or "").strip())
    return parsed.scheme.lower() == "https" and (parsed.hostname or "").lower() in {
        "connectortest.qnbesolutions.com.tr",
        "earsivtest.qnbesolutions.com.tr",
    }


def _earsiv_service_url(value: str) -> str:
    base = str(value or "").strip().rstrip("/")
    if base.endswith("/EarsivWebService"):
        return base
    return f"{base}/EarsivWebService"


def _soap_operation(name: str, inner_xml: str, *, namespace: str) -> str:
    return f'<qnb:{name} xmlns:qnb="{namespace}">{inner_xml}</qnb:{name}>'


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1] if "}" in tag else tag


def _parse_xml(text: str):
    try:
        return ElementTree.fromstring(str(text or "").encode("utf-8"))
    except ElementTree.ParseError as exc:
        raise ValueError("QNB e-Arsiv SOAP response could not be parsed") from exc


def _raise_for_soap_fault(text: str) -> None:
    root = _parse_xml(text)
    for element in root.iter():
        if _local_name(str(element.tag)).lower() in {"faultstring", "message"} and (element.text or "").strip():
            raise ValueError((element.text or "").strip())


def _parse_result_entries(return_element) -> dict[str, str]:
    entries: dict[str, str] = {}
    for element in return_element.iter():
        if _local_name(str(element.tag)) != "entry":
            continue
        key = ""
        value = ""
        for child in list(element):
            name = _local_name(str(child.tag))
            if name == "key":
                key = (child.text or "").strip()
            elif name == "value":
                value = (child.text or "").strip()
        if key:
            entries[key] = value
    return entries


def _parse_created_invoice(text: str, *, transaction_id: str) -> QnbEarsivCreatedInvoice:
    root = _parse_xml(text)
    result_code = ""
    result_text = ""
    output_format = ""
    output_encoded = ""
    entries: dict[str, str] = {}
    for element in root.iter():
        name = _local_name(str(element.tag))
        if name == "return":
            entries = _parse_result_entries(element)
        elif name == "resultCode":
            result_code = (element.text or "").strip()
        elif name == "resultText":
            result_text = (element.text or "").strip()
        elif name == "output":
            for child in list(element):
                child_name = _local_name(str(child.tag))
                if child_name == "belgeFormati":
                    output_format = (child.text or "").strip()
                elif child_name == "belgeIcerigi":
                    output_encoded = (child.text or "").strip()

    if not result_code:
        raise ValueError("QNB e-Arsiv response did not include resultCode")
    output_content = b""
    if output_encoded:
        try:
            output_content = base64.b64decode(output_encoded, validate=True)
        except ValueError as exc:
            raise ValueError("QNB e-Arsiv output document is not valid base64") from exc
        if len(output_content) > QNB_EARSIV_MAX_OUTPUT_BYTES:
            raise ValueError("QNB e-Arsiv output document exceeds size limit")
        if output_format.upper() == "PDF" and not output_content.startswith(b"%PDF-"):
            raise ValueError("QNB e-Arsiv PDF output has an invalid header")

    return QnbEarsivCreatedInvoice(
        transaction_id=transaction_id,
        result_code=result_code,
        result_text=result_text,
        invoice_uuid=entries.get("uuid", ""),
        invoice_no=entries.get("faturaNo", ""),
        invoice_url=entries.get("faturaURL", ""),
        output_format=output_format,
        output_content=output_content,
    )


def _safe_error_message(exc: Exception) -> str:
    text = str(exc or "")
    return text if len(text) <= 240 else f"{text[:237]}..."
