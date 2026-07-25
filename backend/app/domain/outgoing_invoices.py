from __future__ import annotations

import base64
import hashlib
import time
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any, Protocol
from uuid import uuid4
from xml.etree import ElementTree
from xml.sax.saxutils import escape


MONEY = Decimal("0.01")
ALLOWED_DOCUMENT_TYPES = {"efatura", "earsiv"}
ALLOWED_PROFILES = {
    "efatura": {"TEMELFATURA", "TICARIFATURA"},
    "earsiv": {"EARSIVFATURA"},
}


@dataclass(frozen=True)
class OutgoingProviderReceipt:
    provider: str
    provider_operation: str
    provider_document_id: str = ""
    provider_transaction_id: str = ""
    provider_invoice_no: str = ""
    provider_status: str = ""
    response_received: bool = True
    evidence: dict[str, object] = field(default_factory=dict)


class OutgoingProviderOutcomeUnknown(RuntimeError):
    """The provider may have accepted the request, but no terminal response is available."""


def utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def money(value: Any) -> Decimal:
    try:
        result = Decimal(str(value)).quantize(MONEY, rounding=ROUND_HALF_UP)
    except (InvalidOperation, ValueError) as exc:
        raise ValueError("Invoice amount must be numeric") from exc
    return result


def amount(value: Decimal) -> str:
    return f"{value.quantize(MONEY, rounding=ROUND_HALF_UP):.2f}"


def normalize_party(value: dict[str, Any], *, label: str) -> dict[str, str]:
    tax_id = "".join(ch for ch in str(value.get("tax_id") or "") if ch.isdigit())
    title = " ".join(str(value.get("title") or "").split())
    if len(tax_id) not in (10, 11):
        raise ValueError(f"{label} tax ID must contain 10 or 11 digits")
    if not title:
        raise ValueError(f"{label} title is required")
    return {
        "tax_id": tax_id,
        "title": title,
        "tax_office": str(value.get("tax_office") or "").strip(),
        "city": str(value.get("city") or "ISTANBUL").strip(),
        "district": str(value.get("district") or "").strip(),
        "email": str(value.get("email") or "").strip(),
    }


def normalize_lines(values: list[dict[str, Any]]) -> tuple[list[dict[str, str]], dict[str, str]]:
    if not values:
        raise ValueError("At least one invoice line is required")
    lines: list[dict[str, str]] = []
    net_total = Decimal("0")
    tax_total = Decimal("0")
    for index, value in enumerate(values, start=1):
        name = " ".join(str(value.get("name") or "").split())
        quantity = money(value.get("quantity", "0"))
        unit_price = money(value.get("unit_price", "0"))
        vat_rate = money(value.get("vat_rate", "0"))
        if not name or quantity <= 0 or unit_price < 0 or vat_rate < 0:
            raise ValueError(f"Invoice line {index} is invalid")
        net = (quantity * unit_price).quantize(MONEY, rounding=ROUND_HALF_UP)
        tax = (net * vat_rate / Decimal("100")).quantize(MONEY, rounding=ROUND_HALF_UP)
        lines.append(
            {
                "line_no": str(index),
                "name": name,
                "quantity": amount(quantity),
                "unit_code": str(value.get("unit_code") or "C62").strip(),
                "unit_price": amount(unit_price),
                "vat_rate": amount(vat_rate),
                "net_amount": amount(net),
                "tax_amount": amount(tax),
            }
        )
        net_total += net
        tax_total += tax
    totals = {
        "net_amount": amount(net_total),
        "tax_amount": amount(tax_total),
        "payable_amount": amount(net_total + tax_total),
    }
    return lines, totals


def _party_xml(party: dict[str, str]) -> str:
    scheme = "VKN" if len(party["tax_id"]) == 10 else "TCKN"
    return "".join(
        [
            "<cac:Party>",
            f'<cbc:EndpointID schemeID="{scheme}">{escape(party["tax_id"])}</cbc:EndpointID>',
            f'<cac:PartyIdentification><cbc:ID schemeID="{scheme}">{escape(party["tax_id"])}</cbc:ID></cac:PartyIdentification>',
            f"<cac:PartyName><cbc:Name>{escape(party['title'])}</cbc:Name></cac:PartyName>",
            "<cac:PostalAddress>",
            f"<cbc:CitySubdivisionName>{escape(party['district'])}</cbc:CitySubdivisionName>",
            f"<cbc:CityName>{escape(party['city'])}</cbc:CityName>",
            "<cac:Country><cbc:IdentificationCode>TR</cbc:IdentificationCode><cbc:Name>TURKIYE</cbc:Name></cac:Country>",
            "</cac:PostalAddress>",
            f"<cac:PartyTaxScheme><cac:TaxScheme><cbc:Name>{escape(party['tax_office'])}</cbc:Name></cac:TaxScheme></cac:PartyTaxScheme>",
            f"<cac:PartyLegalEntity><cbc:RegistrationName>{escape(party['title'])}</cbc:RegistrationName></cac:PartyLegalEntity>",
            "</cac:Party>",
        ]
    )


def build_invoice_ubl(invoice: dict[str, Any]) -> bytes:
    currency = invoice["currency"]
    lines_xml: list[str] = []
    for line in invoice["lines"]:
        lines_xml.append(
            "".join(
                [
                    "<cac:InvoiceLine>",
                    f"<cbc:ID>{line['line_no']}</cbc:ID>",
                    f'<cbc:InvoicedQuantity unitCode="{escape(line["unit_code"])}">{line["quantity"]}</cbc:InvoicedQuantity>',
                    f'<cbc:LineExtensionAmount currencyID="{currency}">{line["net_amount"]}</cbc:LineExtensionAmount>',
                    "<cac:TaxTotal>",
                    f'<cbc:TaxAmount currencyID="{currency}">{line["tax_amount"]}</cbc:TaxAmount>',
                    "<cac:TaxSubtotal>",
                    f'<cbc:TaxableAmount currencyID="{currency}">{line["net_amount"]}</cbc:TaxableAmount>',
                    f'<cbc:TaxAmount currencyID="{currency}">{line["tax_amount"]}</cbc:TaxAmount>',
                    f"<cbc:Percent>{line['vat_rate']}</cbc:Percent>",
                    "<cac:TaxCategory><cac:TaxScheme><cbc:Name>KDV</cbc:Name><cbc:TaxTypeCode>0015</cbc:TaxTypeCode></cac:TaxScheme></cac:TaxCategory>",
                    "</cac:TaxSubtotal></cac:TaxTotal>",
                    f"<cac:Item><cbc:Name>{escape(line['name'])}</cbc:Name></cac:Item>",
                    f'<cac:Price><cbc:PriceAmount currencyID="{currency}">{line["unit_price"]}</cbc:PriceAmount></cac:Price>',
                    "</cac:InvoiceLine>",
                ]
            )
        )
    totals = invoice["totals"]
    content = "".join(
        [
            '<?xml version="1.0" encoding="UTF-8"?>',
            '<Invoice xmlns="urn:oasis:names:specification:ubl:schema:xsd:Invoice-2" ',
            'xmlns:cac="urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2" ',
            'xmlns:cbc="urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2">',
            "<cbc:UBLVersionID>2.1</cbc:UBLVersionID><cbc:CustomizationID>TR1.2</cbc:CustomizationID>",
            f"<cbc:ProfileID>{invoice['profile']}</cbc:ProfileID>",
            f"<cbc:ID>{escape(invoice['invoice_no'])}</cbc:ID><cbc:CopyIndicator>false</cbc:CopyIndicator>",
            f"<cbc:UUID>{invoice['invoice_id']}</cbc:UUID><cbc:IssueDate>{invoice['issue_date']}</cbc:IssueDate>",
            "<cbc:InvoiceTypeCode>SATIS</cbc:InvoiceTypeCode>",
            f"<cbc:DocumentCurrencyCode>{currency}</cbc:DocumentCurrencyCode><cbc:LineCountNumeric>{len(invoice['lines'])}</cbc:LineCountNumeric>",
            f"<cac:AccountingSupplierParty>{_party_xml(invoice['supplier'])}</cac:AccountingSupplierParty>",
            f"<cac:AccountingCustomerParty>{_party_xml(invoice['customer'])}</cac:AccountingCustomerParty>",
            "<cac:TaxTotal>",
            f'<cbc:TaxAmount currencyID="{currency}">{totals["tax_amount"]}</cbc:TaxAmount></cac:TaxTotal>',
            "<cac:LegalMonetaryTotal>",
            f'<cbc:LineExtensionAmount currencyID="{currency}">{totals["net_amount"]}</cbc:LineExtensionAmount>',
            f'<cbc:TaxExclusiveAmount currencyID="{currency}">{totals["net_amount"]}</cbc:TaxExclusiveAmount>',
            f'<cbc:TaxInclusiveAmount currencyID="{currency}">{totals["payable_amount"]}</cbc:TaxInclusiveAmount>',
            f'<cbc:PayableAmount currencyID="{currency}">{totals["payable_amount"]}</cbc:PayableAmount>',
            "</cac:LegalMonetaryTotal>",
            *lines_xml,
            "</Invoice>",
        ]
    ).encode("utf-8")
    root = ElementTree.fromstring(content)
    if not root.tag.endswith("}Invoice"):
        raise ValueError("Generated document is not a UBL invoice")
    return content


class OutgoingInvoiceProvider(Protocol):
    provider_name: str
    provider_operation: str

    def send(self, *, invoice: dict[str, Any], ubl_content: bytes) -> OutgoingProviderReceipt: ...

    def reconcile(self, *, invoice: dict[str, Any], attempt: dict[str, Any]) -> dict[str, Any]: ...


class FakeOutgoingInvoiceProvider:
    provider_name = "fake"
    provider_operation = "local_fake"

    def send(self, *, invoice: dict[str, Any], ubl_content: bytes) -> OutgoingProviderReceipt:
        digest = hashlib.sha256(ubl_content).hexdigest()
        return OutgoingProviderReceipt(
            provider="fake",
            provider_operation="local_fake",
            provider_document_id=f"FAKE-{digest[:16].upper()}",
            provider_status="accepted",
            evidence={"ubl_sha256": digest, "mode": "local_fake"},
        )

    def reconcile(self, *, invoice: dict[str, Any], attempt: dict[str, Any]) -> dict[str, Any]:
        return {"status": str(invoice.get("status") or "")}


class OutgoingInvoiceService:
    def __init__(
        self,
        *,
        store: Any,
        provider: OutgoingInvoiceProvider | None = None,
        document_service: Any | None = None,
        claim_wait_seconds: float = 35.0,
        reconciliation_stale_seconds: float = 120.0,
        reconciliation_lease_seconds: float = 60.0,
    ) -> None:
        self.store = store
        self.provider = provider or FakeOutgoingInvoiceProvider()
        self.document_service = document_service
        self.claim_wait_seconds = max(float(claim_wait_seconds), 0.0)
        self.reconciliation_stale_seconds = max(float(reconciliation_stale_seconds), 0.0)
        self.reconciliation_lease_seconds = max(float(reconciliation_lease_seconds), 1.0)

    def create_draft(self, *, client_id: str, payload: dict[str, Any], actor_user_id: str) -> dict[str, Any]:
        document_type = str(payload.get("document_type") or "").lower()
        profile = str(payload.get("profile") or "").upper()
        if document_type not in ALLOWED_DOCUMENT_TYPES:
            raise ValueError("Document type must be efatura or earsiv")
        if profile not in ALLOWED_PROFILES[document_type]:
            raise ValueError("Invoice profile is not valid for the document type")
        invoice_no = str(payload.get("invoice_no") or "").strip()
        issue_date = str(payload.get("issue_date") or "").strip()
        if not invoice_no or len(issue_date) != 10:
            raise ValueError("Invoice number and ISO issue date are required")
        lines, totals = normalize_lines(payload.get("lines") or [])
        now = utc_now()
        invoice = {
            "invoice_id": str(uuid4()),
            "client_id": client_id,
            "status": "draft",
            "document_type": document_type,
            "profile": profile,
            "invoice_no": invoice_no,
            "issue_date": issue_date,
            "currency": str(payload.get("currency") or "TRY").upper(),
            "supplier": normalize_party(payload.get("supplier") or {}, label="Supplier"),
            "customer": normalize_party(payload.get("customer") or {}, label="Customer"),
            "lines": lines,
            "totals": totals,
            "history": [{"status": "draft", "actor_user_id": actor_user_id, "at": now}],
            "created_at": now,
            "updated_at": now,
        }
        return self.store.save_outgoing_invoice(client_id=client_id, invoice=invoice)

    def approve(self, *, client_id: str, invoice_id: str, actor_user_id: str) -> dict[str, Any]:
        invoice = self._get(client_id, invoice_id)
        if invoice.get("status") != "draft":
            raise ValueError("Only a draft invoice can be approved")
        ubl_content = build_invoice_ubl(invoice)
        now = utc_now()
        invoice.update(
            {
                "status": "approved",
                "ubl_base64": base64.b64encode(ubl_content).decode("ascii"),
                "ubl_sha256": hashlib.sha256(ubl_content).hexdigest(),
                "approved_at": now,
                "approved_by": actor_user_id,
                "updated_at": now,
            }
        )
        invoice.setdefault("history", []).append({"status": "approved", "actor_user_id": actor_user_id, "at": now})
        return self.store.save_outgoing_invoice(client_id=client_id, invoice=invoice)

    def send(
        self, *, client_id: str, invoice_id: str, idempotency_key: str, actor_user_id: str
    ) -> dict[str, Any]:
        idempotency_key = idempotency_key.strip()
        if not idempotency_key:
            raise ValueError("Idempotency key is required")
        candidate = self._get(client_id, invoice_id)
        if candidate.get("status") == "draft":
            raise ValueError("Only an approved invoice can be sent")
        try:
            ubl_content = base64.b64decode(candidate.get("ubl_base64") or "", validate=True)
        except Exception as exc:
            raise ValueError("Frozen UBL payload is invalid") from exc
        frozen_hash = str(candidate.get("ubl_sha256") or "")
        if hashlib.sha256(ubl_content).hexdigest() != frozen_hash:
            raise ValueError("Frozen UBL hash mismatch")
        provider_name = str(getattr(self.provider, "provider_name", self.provider.__class__.__name__))
        if getattr(self.provider, "dispatch_enabled", True) is False:
            raise ValueError("Outgoing invoice provider is disabled")
        provider_preflight = getattr(self.provider, "preflight", None)
        if candidate.get("status") == "approved" and callable(provider_preflight):
            provider_preflight(candidate, ubl_content=ubl_content)
        operation_for = getattr(self.provider, "operation_for", None)
        provider_operation = str(
            operation_for(candidate) if callable(operation_for) else getattr(self.provider, "provider_operation", "send")
        )
        claimed, invoice, attempt = self.store.claim_outgoing_invoice_attempt(
            client_id=client_id,
            invoice_id=invoice_id,
            idempotency_key=idempotency_key,
            ubl_sha256=str(candidate.get("ubl_sha256") or ""),
            provider=provider_name,
            provider_operation=provider_operation,
        )
        if not claimed:
            return self._wait_for_attempt_result(client_id=client_id, invoice=invoice)
        attempt_id = str(attempt["attempt_id"])
        try:
            self.store.append_outgoing_invoice_attempt_event(
                client_id=client_id,
                attempt_id=attempt_id,
                event="preflight_passed",
                state="preflight_passed",
                details={"ubl_sha256": frozen_hash},
            )
            self.store.append_outgoing_invoice_attempt_event(
                client_id=client_id,
                attempt_id=attempt_id,
                event="request_started",
                state="request_started",
                details={"provider_operation": provider_operation},
            )
            receipt = self.provider.send(invoice=invoice, ubl_content=ubl_content)
            result = asdict(receipt)
            result["receipt"] = result.pop("evidence")
            now = utc_now()
            invoice.update({**result, "status": "sent", "sent_at": now, "sent_by": actor_user_id, "updated_at": now})
            invoice.setdefault("history", []).append({"status": "sent", "actor_user_id": actor_user_id, "at": now})
            finalized, saved_invoice, _ = self.store.finalize_outgoing_invoice_attempt_and_invoice(
                client_id=client_id,
                attempt_id=attempt_id,
                expected_state="request_started",
                event="response_received",
                state="sent",
                invoice=invoice,
                details={
                    "provider_document_id": result.get("provider_document_id") or "",
                    "provider_transaction_id": result.get("provider_transaction_id") or "",
                    "provider_status": result.get("provider_status") or "",
                },
            )
            if not finalized:
                return self._get(client_id, invoice_id)
        except OutgoingProviderOutcomeUnknown as exc:
            now = utc_now()
            invoice.update(
                {"status": "reconciliation_required", "last_error": str(exc), "updated_at": now}
            )
            invoice.setdefault("history", []).append(
                {"status": "reconciliation_required", "actor_user_id": actor_user_id, "at": now}
            )
            finalized, saved_invoice, _ = self.store.finalize_outgoing_invoice_attempt_and_invoice(
                client_id=client_id,
                attempt_id=attempt_id,
                expected_state="request_started",
                event="outcome_unknown",
                state="reconciliation_required",
                invoice=invoice,
                details={"error_type": exc.__class__.__name__},
            )
            if not finalized:
                return self._get(client_id, invoice_id)
            return saved_invoice
        except Exception as exc:
            now = utc_now()
            invoice.update({"status": "failed", "last_error": str(exc), "updated_at": now})
            invoice.setdefault("history", []).append({"status": "failed", "actor_user_id": actor_user_id, "at": now})
            finalized, _, _ = self.store.finalize_outgoing_invoice_attempt_and_invoice(
                client_id=client_id,
                attempt_id=attempt_id,
                expected_state="request_started",
                event="send_failed",
                state="failed",
                invoice=invoice,
                details={"error_type": exc.__class__.__name__},
            )
            if not finalized:
                return self._get(client_id, invoice_id)
            raise
        return self._link_confirmed_sales_source(
            client_id=client_id,
            invoice=saved_invoice,
            attempt_id=attempt_id,
            actor_user_id=actor_user_id,
            ubl_content=ubl_content,
        )

    def get(self, *, client_id: str, invoice_id: str) -> dict[str, Any]:
        return self._get(client_id, invoice_id)

    def reconcile(self, *, client_id: str, invoice_id: str, actor_user_id: str) -> dict[str, Any]:
        invoice = self._get(client_id, invoice_id)
        if invoice.get("status") not in {"reconciliation_required", "sending"}:
            raise ValueError("Only a submitted invoice requiring reconciliation can be reconciled")
        attempt_id = str(invoice.get("current_attempt_id") or "")
        attempt = self.store.get_outgoing_invoice_attempt(client_id=client_id, attempt_id=attempt_id)
        if not attempt:
            raise ValueError("Outgoing invoice reconciliation attempt was not found")
        events = [str(item.get("event") or "") for item in attempt.get("events") or []]
        if "request_started" not in events:
            raise ValueError("Outgoing invoice mutating request was not started")
        now_dt = datetime.now(UTC)
        owner_id = f"{actor_user_id}:{uuid4()}"
        claimed, attempt = self.store.claim_outgoing_invoice_reconciliation(
            client_id=client_id,
            attempt_id=attempt_id,
            owner_id=owner_id,
            stale_before=(now_dt - timedelta(seconds=self.reconciliation_stale_seconds)).isoformat(
                timespec="seconds"
            ),
            lease_expires_at=(now_dt + timedelta(seconds=self.reconciliation_lease_seconds)).isoformat(
                timespec="seconds"
            ),
        )
        if not claimed:
            raise ValueError("Outgoing invoice reconciliation is already active or the send attempt is not stale")
        if invoice.get("status") == "sending":
            invoice.update({"status": "reconciliation_required", "updated_at": utc_now()})
            invoice = self.store.save_outgoing_invoice(client_id=client_id, invoice=invoice)
        try:
            result = self.provider.reconcile(invoice=invoice, attempt=attempt)
        except Exception as exc:
            self.store.finalize_outgoing_invoice_attempt(
                client_id=client_id,
                attempt_id=attempt_id,
                expected_state="reconciling",
                event="reconciliation_error",
                state="reconciliation_required",
                details={"error_type": exc.__class__.__name__},
                reconciliation_owner=owner_id,
            )
            raise
        outcome = str(result.get("status") or "reconciliation_required")
        if (
            outcome == "sent"
            and str(attempt.get("provider") or "") == "qnb_sandbox"
            and not str(result.get("provider_document_id") or "").strip()
        ):
            outcome = "reconciliation_required"
        evidence = result.get("evidence") if isinstance(result.get("evidence"), dict) else {}
        now = utc_now()
        if outcome == "sent":
            invoice.update(
                {
                    "status": "sent",
                    "provider_document_id": str(result.get("provider_document_id") or ""),
                    "provider_transaction_id": str(result.get("provider_transaction_id") or ""),
                    "provider_invoice_no": str(result.get("provider_invoice_no") or ""),
                    "provider_status": str(result.get("provider_status") or ""),
                    "reconciliation_receipt": evidence,
                    "reconciled_at": now,
                    "reconciled_by": actor_user_id,
                    "updated_at": now,
                }
            )
            invoice.setdefault("history", []).append(
                {"status": "sent", "source": "reconciliation", "actor_user_id": actor_user_id, "at": now}
            )
            event = "reconciliation_confirmed_sent"
        elif outcome == "failed":
            invoice.update(
                {
                    "status": "failed",
                    "provider_status": str(result.get("provider_status") or ""),
                    "reconciliation_receipt": evidence,
                    "reconciled_at": now,
                    "reconciled_by": actor_user_id,
                    "updated_at": now,
                }
            )
            invoice.setdefault("history", []).append(
                {"status": "failed", "source": "reconciliation", "actor_user_id": actor_user_id, "at": now}
            )
            event = "reconciliation_confirmed_failed"
        else:
            invoice.update(
                {"status": "reconciliation_required", "reconciliation_receipt": evidence, "updated_at": now}
            )
            event = "reconciliation_inconclusive"
            outcome = "reconciliation_required"
        finalized, saved_invoice, _ = self.store.finalize_outgoing_invoice_attempt_and_invoice(
            client_id=client_id,
            attempt_id=attempt_id,
            expected_state="reconciling",
            event=event,
            state=outcome,
            invoice=invoice,
            details={
                "provider_document_id": str(result.get("provider_document_id") or ""),
                "provider_status": str(result.get("provider_status") or ""),
            },
            reconciliation_owner=owner_id,
        )
        if not finalized:
            return self._get(client_id, invoice_id)
        if outcome != "sent":
            return saved_invoice
        try:
            ubl_content = base64.b64decode(saved_invoice.get("ubl_base64") or "", validate=True)
        except Exception:
            return saved_invoice
        return self._link_confirmed_sales_source(
            client_id=client_id,
            invoice=saved_invoice,
            attempt_id=attempt_id,
            actor_user_id=actor_user_id,
            ubl_content=ubl_content,
        )

    def list(self, *, client_id: str) -> list[dict[str, Any]]:
        return self.store.list_outgoing_invoices(client_id=client_id)

    def _link_confirmed_sales_source(
        self,
        *,
        client_id: str,
        invoice: dict[str, Any],
        attempt_id: str,
        actor_user_id: str,
        ubl_content: bytes,
    ) -> dict[str, Any]:
        if self.document_service is None or str(invoice.get("provider") or "") != "qnb_sandbox":
            return invoice
        if invoice.get("canonical_document_ref"):
            return invoice
        try:
            uploaded = self.document_service.store_document_upload(
                client_id=client_id,
                document_type="einvoice_xml",
                intake_category="sales_invoice",
                period=str(invoice.get("issue_date") or "")[:7],
                file_name=f"outgoing-{invoice['invoice_id']}.xml",
                uploaded_by="qnb_outgoing_confirmed",
                uploaded_by_user_id=actor_user_id,
                request_user_id=actor_user_id,
                content=ubl_content,
                size_bytes=len(ubl_content),
                sha256=str(invoice.get("ubl_sha256") or ""),
            )
            document = {key: value for key, value in uploaded.items() if key != "processing_job"}
            document.update(
                {
                    "source_provider": "qnb_esolutions",
                    "source_direction": "sales_invoice",
                    "source_outgoing_invoice_id": str(invoice.get("invoice_id") or ""),
                    "source_outgoing_attempt_id": attempt_id,
                    "source_provider_document_id": str(invoice.get("provider_document_id") or ""),
                    "source_ubl_sha256": str(invoice.get("ubl_sha256") or ""),
                }
            )
            self.store.save_uploaded_document(client_id=client_id, document=document)
            job = uploaded.get("processing_job") if isinstance(uploaded.get("processing_job"), dict) else {}
            invoice.update(
                {
                    "canonical_document_ref": str(uploaded.get("document_ref") or ""),
                    "canonical_processing_job_id": str(job.get("id") or ""),
                    "accounting_link_status": str(job.get("status") or "queued"),
                    "updated_at": utc_now(),
                }
            )
        except Exception as exc:
            invoice.update(
                {
                    "accounting_link_status": "failed",
                    "accounting_link_error_type": exc.__class__.__name__,
                    "updated_at": utc_now(),
                }
            )
        return self.store.save_outgoing_invoice(client_id=client_id, invoice=invoice)

    def _wait_for_attempt_result(self, *, client_id: str, invoice: dict[str, Any]) -> dict[str, Any]:
        if str(invoice.get("status") or "") != "sending" or self.claim_wait_seconds <= 0:
            return invoice
        deadline = time.monotonic() + self.claim_wait_seconds
        current = invoice
        while time.monotonic() < deadline:
            time.sleep(0.05)
            refreshed = self.store.get_outgoing_invoice(
                client_id=client_id, invoice_id=str(invoice.get("invoice_id") or "")
            )
            if refreshed:
                current = refreshed
            if str(current.get("status") or "") != "sending":
                return current
        return current

    def _get(self, client_id: str, invoice_id: str) -> dict[str, Any]:
        invoice = self.store.get_outgoing_invoice(client_id=client_id, invoice_id=invoice_id)
        if not invoice:
            raise ValueError("Outgoing invoice not found")
        return invoice
