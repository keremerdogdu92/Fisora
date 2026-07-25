from __future__ import annotations

import base64
import hashlib
from typing import Any, Mapping
from xml.etree import ElementTree

import httpx

from app.domain.outgoing_invoices import (
    FakeOutgoingInvoiceProvider,
    OutgoingProviderOutcomeUnknown,
    OutgoingProviderReceipt,
)
from app.domain.qnb_credentials import QnbCredentialCipher, validate_qnb_endpoint
from app.domain.qnb_earsiv import (
    QnbEarsivCredentials,
    QnbSoapEarsivAdapter,
    is_qnb_earsiv_test_endpoint,
)
from app.domain.qnb_efatura import QnbConnectionCredentials, QnbSoapEfaturaAdapter


class DisabledOutgoingInvoiceProvider:
    provider_name = "disabled"
    provider_operation = "disabled"
    dispatch_enabled = False

    def send(self, *, invoice: dict[str, Any], ubl_content: bytes) -> OutgoingProviderReceipt:
        raise ValueError("Outgoing invoice provider is disabled")

    def reconcile(self, *, invoice: dict[str, Any], attempt: dict[str, Any]) -> dict[str, Any]:
        raise ValueError("Outgoing invoice provider is disabled")


class QnbSandboxOutgoingInvoiceProvider:
    provider_name = "qnb_sandbox"
    provider_operation = "qnb_sandbox.send"

    def __init__(
        self,
        *,
        store: Any,
        env: Mapping[str, str],
        efatura_adapter: Any | None = None,
        earsiv_adapter: Any | None = None,
        credential_cipher: QnbCredentialCipher | None = None,
    ) -> None:
        self.store = store
        self.env = env
        self.efatura_adapter = efatura_adapter or QnbSoapEfaturaAdapter()
        self.earsiv_adapter = earsiv_adapter or QnbSoapEarsivAdapter()
        self._credential_cipher = credential_cipher

    def operation_for(self, invoice: dict[str, Any]) -> str:
        document_type = str(invoice.get("document_type") or "")
        return {"efatura": "belgeGonderExt", "earsiv": "faturaOlusturExt"}.get(
            document_type, "unsupported"
        )

    def preflight(self, invoice: dict[str, Any], *, ubl_content: bytes) -> None:
        connection = self._active_connection(invoice)
        self._validate_frozen_supplier(connection, ubl_content=ubl_content)
        document_type = str(invoice.get("document_type") or "")
        if document_type == "efatura":
            self._efatura_labels()
            credentials = self._efatura_credentials(connection)
            prepare = getattr(self.efatura_adapter, "prepare_outgoing_send", None)
            if callable(prepare):
                prepare(credentials)
            return
        if document_type == "earsiv":
            credentials = self._earsiv_credentials(connection)
            prepare = getattr(self.earsiv_adapter, "prepare_outgoing_send", None)
            if callable(prepare):
                prepare(credentials)
            return
        raise ValueError("QNB sandbox only supports efatura or earsiv")

    def send(self, *, invoice: dict[str, Any], ubl_content: bytes) -> OutgoingProviderReceipt:
        connection = self._active_connection(invoice)
        self._validate_frozen_supplier(connection, ubl_content=ubl_content)
        document_type = str(invoice.get("document_type") or "")
        try:
            if document_type == "efatura":
                return self._send_efatura(connection, invoice=invoice, ubl_content=ubl_content)
            if document_type == "earsiv":
                return self._send_earsiv(connection, invoice=invoice, ubl_content=ubl_content)
            raise ValueError("QNB sandbox only supports efatura or earsiv")
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            raise OutgoingProviderOutcomeUnknown("QNB response was not received") from exc
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 429 or exc.response.status_code >= 500:
                raise OutgoingProviderOutcomeUnknown("QNB returned an ambiguous HTTP status") from exc
            raise
        except RuntimeError as exc:
            lowered = str(exc).lower()
            if "http 429" in lowered or any(f"http {status}" in lowered for status in range(500, 600)):
                raise OutgoingProviderOutcomeUnknown("QNB returned an ambiguous HTTP status") from exc
            raise
        except ValueError as exc:
            lowered = str(exc).lower()
            ambiguous_markers = (
                "response could not be parsed",
                "response did not include",
                "output document is not valid base64",
                "output document has an invalid header",
            )
            if any(marker in lowered for marker in ambiguous_markers):
                raise OutgoingProviderOutcomeUnknown("QNB response could not be confirmed") from exc
            raise

    def reconcile(self, *, invoice: dict[str, Any], attempt: dict[str, Any]) -> dict[str, Any]:
        connection = self._active_connection(invoice)
        try:
            frozen_ubl = base64.b64decode(invoice.get("ubl_base64") or "", validate=True)
        except Exception as exc:
            raise ValueError("Frozen UBL payload is invalid") from exc
        self._validate_frozen_supplier(connection, ubl_content=frozen_ubl)
        document_type = str(invoice.get("document_type") or "")
        if document_type == "efatura":
            status = self.efatura_adapter.get_outgoing_invoice_status_by_local_invoice_no(
                self._efatura_credentials(connection),
                invoice_no=str(invoice.get("invoice_no") or ""),
            )
            outcome = {
                "received": "sent",
                "processed": "sent",
                "processing_error": "failed",
            }.get(str(status.processing_state or ""), "reconciliation_required")
            if outcome == "sent" and not str(status.document_oid or "").strip():
                outcome = "reconciliation_required"
            return {
                "status": outcome,
                "provider_document_id": str(status.document_oid or ""),
                "provider_status": str(status.processing_state or ""),
                "evidence": {
                    "lookup": "local_invoice_no",
                    "status_code": str(status.status_code or ""),
                    "status_text": str(status.status_text or ""),
                    "ettn": str(status.ettn or ""),
                },
            }
        if document_type == "earsiv":
            result = self.earsiv_adapter.query_invoice(
                self._earsiv_credentials(connection),
                invoice_no=str(invoice.get("provider_invoice_no") or invoice.get("invoice_no") or ""),
                invoice_uuid=str(invoice.get("provider_document_id") or ""),
            )
            confirmed = bool(result.ok and str(result.invoice_uuid or "").strip())
            return {
                "status": "sent" if confirmed else "reconciliation_required",
                "provider_document_id": str(result.invoice_uuid or ""),
                "provider_transaction_id": str(result.transaction_id or ""),
                "provider_invoice_no": str(result.invoice_no or ""),
                "provider_status": str(result.result_code or ""),
                "evidence": {
                    "lookup": "provider_invoice_identity",
                    "result_code": str(result.result_code or ""),
                },
            }
        raise ValueError("QNB sandbox only supports efatura or earsiv")

    def _active_connection(self, invoice: dict[str, Any]) -> dict[str, Any]:
        client_id = str(invoice.get("client_id") or "")
        connection = self.store.get_qnb_connection(client_id=client_id)
        if not connection or str(connection.get("status") or "") != "active":
            raise ValueError("An active client-scoped QNB connection is required")
        base_url, environment = validate_qnb_endpoint(
            str(connection.get("base_url") or ""), str(connection.get("environment") or "")
        )
        if environment != "test":
            raise ValueError("QNB sandbox requires a test connection")
        return {**connection, "base_url": base_url}

    def _validate_frozen_supplier(self, connection: dict[str, Any], *, ubl_content: bytes) -> None:
        supplier_tax_id = _supplier_tax_id_from_ubl(ubl_content)
        connection_tax_id = _digits(str(connection.get("vkn") or ""))
        if not supplier_tax_id or supplier_tax_id != connection_tax_id:
            raise ValueError("Frozen UBL supplier tax ID does not match the QNB connection")

    def _cipher(self) -> QnbCredentialCipher:
        if self._credential_cipher is None:
            self._credential_cipher = QnbCredentialCipher.from_env(self.env)
        return self._credential_cipher

    def _efatura_credentials(self, connection: dict[str, Any]) -> QnbConnectionCredentials:
        return QnbConnectionCredentials(
            base_url=str(connection["base_url"]),
            username=str(connection.get("username") or ""),
            password=self._cipher().decrypt(str(connection.get("credential_ciphertext") or "")),
            vkn=str(connection.get("vkn") or ""),
            erp_code=str(connection.get("erp_code") or ""),
        )

    def _earsiv_credentials(self, connection: dict[str, Any]) -> QnbEarsivCredentials:
        user_service_url = str(self.env.get("QNB_EARSIV_USER_SERVICE_URL") or "").strip()
        service_url = str(self.env.get("QNB_EARSIV_TEST_BASE_URL") or "").strip()
        if not is_qnb_earsiv_test_endpoint(user_service_url) or not is_qnb_earsiv_test_endpoint(service_url):
            raise ValueError("QNB e-Arsiv sandbox requires configured test endpoints")
        return QnbEarsivCredentials(
            user_service_url=user_service_url,
            service_url=service_url,
            username=str(connection.get("earsiv_username") or connection.get("username") or ""),
            password=self._cipher().decrypt(
                str(connection.get("earsiv_credential_ciphertext") or connection.get("credential_ciphertext") or "")
            ),
            vkn=str(connection.get("vkn") or ""),
            erp_code=str(connection.get("erp_code") or ""),
        )

    def _send_efatura(
        self, connection: dict[str, Any], *, invoice: dict[str, Any], ubl_content: bytes
    ) -> OutgoingProviderReceipt:
        sender_label, recipient_label = self._efatura_labels()
        result = self.efatura_adapter.send_outgoing_invoice_ubl(
            self._efatura_credentials(connection),
            invoice_no=str(invoice.get("invoice_no") or ""),
            content=ubl_content,
            recipient_label=recipient_label,
            sender_label=sender_label,
        )
        document_oid = str(result.document_oid or "").strip()
        if not document_oid:
            raise OutgoingProviderOutcomeUnknown("QNB e-Fatura response omitted the document OID")
        return OutgoingProviderReceipt(
            provider=self.provider_name,
            provider_operation="belgeGonderExt",
            provider_document_id=document_oid,
            provider_invoice_no=str(result.local_invoice_no or ""),
            provider_status="accepted",
            evidence={"ubl_sha256": hashlib.sha256(ubl_content).hexdigest(), "endpoint_class": "sandbox"},
        )

    def _efatura_labels(self) -> tuple[str, str]:
        sender_label = str(self.env.get("FISORA_QNB_SANDBOX_SENDER_LABEL") or "").strip()
        recipient_label = str(self.env.get("FISORA_QNB_SANDBOX_RECIPIENT_LABEL") or "").strip()
        if not sender_label or not recipient_label:
            raise ValueError("QNB e-Fatura sandbox sender and recipient labels are required")
        return sender_label, recipient_label

    def _send_earsiv(
        self, connection: dict[str, Any], *, invoice: dict[str, Any], ubl_content: bytes
    ) -> OutgoingProviderReceipt:
        result = self.earsiv_adapter.create_invoice_ubl(
            self._earsiv_credentials(connection),
            transaction_id=str(invoice.get("invoice_id") or ""),
            content=ubl_content,
            assign_invoice_number=False,
            send_to_draft=False,
        )
        if not result.ok or not str(result.invoice_uuid or "").strip():
            raise OutgoingProviderOutcomeUnknown("QNB e-Arsiv response omitted a confirmed invoice UUID")
        evidence: dict[str, object] = {
            "result_code": result.result_code,
            "ubl_sha256": hashlib.sha256(ubl_content).hexdigest(),
            "endpoint_class": "sandbox",
        }
        if result.output_content:
            evidence["returned_document_sha256"] = hashlib.sha256(result.output_content).hexdigest()
            evidence["returned_document_format"] = result.output_format
        return OutgoingProviderReceipt(
            provider=self.provider_name,
            provider_operation="faturaOlusturExt",
            provider_document_id=str(result.invoice_uuid),
            provider_transaction_id=str(result.transaction_id),
            provider_invoice_no=str(result.invoice_no),
            provider_status=str(result.result_code),
            evidence=evidence,
        )


def build_outgoing_invoice_provider(env: Mapping[str, str], store: Any) -> Any:
    mode = str(env.get("FISORA_OUTGOING_PROVIDER_MODE") or "disabled").strip().lower()
    if mode == "disabled":
        return DisabledOutgoingInvoiceProvider()
    if mode == "fake":
        return FakeOutgoingInvoiceProvider()
    if mode == "qnb_sandbox":
        return QnbSandboxOutgoingInvoiceProvider(store=store, env=env)
    raise ValueError("FISORA_OUTGOING_PROVIDER_MODE must be disabled, fake or qnb_sandbox")


def _digits(value: str) -> str:
    return "".join(character for character in value if character.isdigit())


def _supplier_tax_id_from_ubl(content: bytes) -> str:
    try:
        root = ElementTree.fromstring(bytes(content or b""))
    except ElementTree.ParseError as exc:
        raise ValueError("Frozen UBL could not be parsed") from exc
    for party in root.iter():
        if str(party.tag).rsplit("}", 1)[-1] != "AccountingSupplierParty":
            continue
        for element in party.iter():
            if str(element.tag).rsplit("}", 1)[-1] not in {"EndpointID", "ID"}:
                continue
            scheme = str(element.attrib.get("schemeID") or "").upper()
            value = _digits(str(element.text or ""))
            if scheme in {"VKN", "TCKN"} and len(value) in {10, 11}:
                return value
    raise ValueError("Frozen UBL supplier tax ID is missing")
