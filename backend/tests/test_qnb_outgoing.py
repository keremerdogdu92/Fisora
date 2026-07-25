from __future__ import annotations

import base64
from pathlib import Path
import sys
import tempfile
import unittest

from cryptography.fernet import Fernet


ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.domain.outgoing_invoices import (
    FakeOutgoingInvoiceProvider,
    OutgoingInvoiceService,
    OutgoingProviderOutcomeUnknown,
)
from app.domain.qnb_credentials import QnbCredentialCipher
from app.domain.qnb_efatura import QnbOutgoingInvoiceSendResult, QnbOutgoingInvoiceStatus
from app.domain.qnb_outgoing import (
    DisabledOutgoingInvoiceProvider,
    QnbSandboxOutgoingInvoiceProvider,
    build_outgoing_invoice_provider,
)
from app.persistence.workflow_store import JsonWorkflowStore


def supplier_ubl(tax_id: str) -> bytes:
    return (
        '<Invoice xmlns="urn:oasis:names:specification:ubl:schema:xsd:Invoice-2" '
        'xmlns:cac="urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2" '
        'xmlns:cbc="urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2">'
        f'<cac:AccountingSupplierParty><cac:Party><cac:PartyIdentification><cbc:ID schemeID="VKN">{tax_id}</cbc:ID>'
        '</cac:PartyIdentification></cac:Party></cac:AccountingSupplierParty></Invoice>'
    ).encode("utf-8")


class QnbOutgoingProviderTests(unittest.TestCase):
    def test_factory_is_disabled_by_default_and_modes_are_explicit(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = JsonWorkflowStore(Path(temp_dir) / "store.json")
            self.assertIsInstance(build_outgoing_invoice_provider({}, store), DisabledOutgoingInvoiceProvider)
            self.assertIsInstance(
                build_outgoing_invoice_provider({"FISORA_OUTGOING_PROVIDER_MODE": "fake"}, store),
                FakeOutgoingInvoiceProvider,
            )
            self.assertIsInstance(
                build_outgoing_invoice_provider({"FISORA_OUTGOING_PROVIDER_MODE": "qnb_sandbox"}, store),
                QnbSandboxOutgoingInvoiceProvider,
            )
            with self.assertRaisesRegex(ValueError, "MODE"):
                build_outgoing_invoice_provider({"FISORA_OUTGOING_PROVIDER_MODE": "qnb_production"}, store)

    def test_disabled_provider_rejects_before_attempt_claim(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = JsonWorkflowStore(Path(temp_dir) / "store.json")
            service = OutgoingInvoiceService(store=store, provider=DisabledOutgoingInvoiceProvider())
            payload = {
                "document_type": "earsiv",
                "profile": "EARSIVFATURA",
                "invoice_no": "EAR2026000000001",
                "issue_date": "2026-07-21",
                "currency": "TRY",
                "supplier": {"tax_id": "5910611340", "title": "Fisora Test"},
                "customer": {"tax_id": "11111111111", "title": "Test Musteri"},
                "lines": [{"name": "Test", "quantity": "1", "unit_price": "100", "vat_rate": "20"}],
            }
            draft = service.create_draft(client_id="client-a", payload=payload, actor_user_id="accountant")
            approved = service.approve(client_id="client-a", invoice_id=draft["invoice_id"], actor_user_id="accountant")

            with self.assertRaisesRegex(ValueError, "disabled"):
                service.send(
                    client_id="client-a",
                    invoice_id=approved["invoice_id"],
                    idempotency_key="disabled-1",
                    actor_user_id="accountant",
                )

            stored = store.get_outgoing_invoice(client_id="client-a", invoice_id=approved["invoice_id"])
            attempts = store.list_outgoing_invoice_attempts(client_id="client-a", invoice_id=approved["invoice_id"])

        self.assertEqual(stored["status"], "approved")
        self.assertEqual(attempts, [])

    def test_qnb_provider_rejects_inactive_connection_before_adapter_call(self) -> None:
        class RecordingAdapter:
            def __init__(self) -> None:
                self.calls = 0

            def send_outgoing_invoice_ubl(self, *args: object, **kwargs: object) -> object:
                self.calls += 1
                raise AssertionError("adapter must not be called")

        with tempfile.TemporaryDirectory() as temp_dir:
            store = JsonWorkflowStore(Path(temp_dir) / "store.json")
            adapter = RecordingAdapter()
            provider = QnbSandboxOutgoingInvoiceProvider(
                store=store,
                env={},
                efatura_adapter=adapter,
                credential_cipher=QnbCredentialCipher(Fernet.generate_key()),
            )

            with self.assertRaisesRegex(ValueError, "active"):
                provider.send(
                    invoice={
                        "client_id": "client-a",
                        "document_type": "efatura",
                        "invoice_no": "FSR2026000000001",
                        "supplier": {"tax_id": "5910611341"},
                    },
                    ubl_content=supplier_ubl("5910611341"),
                )

        self.assertEqual(adapter.calls, 0)

    def test_qnb_provider_uses_client_credential_and_normalizes_efatura_receipt(self) -> None:
        class RecordingAdapter:
            def __init__(self) -> None:
                self.calls: list[tuple[object, dict[str, object]]] = []

            def send_outgoing_invoice_ubl(self, credentials: object, **kwargs: object) -> object:
                self.calls.append((credentials, kwargs))
                return QnbOutgoingInvoiceSendResult("oid-123", str(kwargs["invoice_no"]))

        with tempfile.TemporaryDirectory() as temp_dir:
            store = JsonWorkflowStore(Path(temp_dir) / "store.json")
            cipher = QnbCredentialCipher(Fernet.generate_key())
            store.save_qnb_connection(
                client_id="client-a",
                connection={
                    "status": "active",
                    "environment": "test",
                    "base_url": "https://erpefaturatest2.qnbesolutions.com.tr/efatura/ws",
                    "username": "sandbox-user",
                    "credential_ciphertext": cipher.encrypt("sandbox-password"),
                    "vkn": "5910611341",
                    "erp_code": "FSR31422",
                },
            )
            adapter = RecordingAdapter()
            provider = QnbSandboxOutgoingInvoiceProvider(
                store=store,
                env={
                    "FISORA_QNB_SANDBOX_SENDER_LABEL": "urn:mail:sendergb@example.test",
                    "FISORA_QNB_SANDBOX_RECIPIENT_LABEL": "urn:mail:receiverpk@example.test",
                },
                efatura_adapter=adapter,
                credential_cipher=cipher,
            )

            receipt = provider.send(
                invoice={
                    "client_id": "client-a",
                    "document_type": "efatura",
                    "invoice_no": "FSR2026000000001",
                    "supplier": {"tax_id": "5910611341"},
                    "ubl_base64": base64.b64encode(supplier_ubl("5910611341")).decode("ascii"),
                },
                ubl_content=supplier_ubl("5910611341"),
            )

        self.assertEqual(receipt.provider_document_id, "oid-123")
        self.assertEqual(receipt.provider_operation, "belgeGonderExt")
        self.assertEqual(adapter.calls[0][0].password, "sandbox-password")

    def test_qnb_provider_rejects_supplier_mismatch_before_adapter_call(self) -> None:
        class RecordingAdapter:
            calls = 0

            def send_outgoing_invoice_ubl(self, *args: object, **kwargs: object) -> object:
                self.calls += 1
                raise AssertionError("adapter must not be called")

        with tempfile.TemporaryDirectory() as temp_dir:
            store = JsonWorkflowStore(Path(temp_dir) / "store.json")
            cipher = QnbCredentialCipher(Fernet.generate_key())
            store.save_qnb_connection(
                client_id="client-a",
                connection={
                    "status": "active",
                    "environment": "test",
                    "base_url": "https://erpefaturatest2.qnbesolutions.com.tr/efatura/ws",
                    "username": "sandbox-user",
                    "credential_ciphertext": cipher.encrypt("sandbox-password"),
                    "vkn": "5910611341",
                    "erp_code": "FSR31422",
                },
            )
            adapter = RecordingAdapter()
            provider = QnbSandboxOutgoingInvoiceProvider(
                store=store, env={}, efatura_adapter=adapter, credential_cipher=cipher
            )

            with self.assertRaisesRegex(ValueError, "does not match"):
                provider.send(
                    invoice={
                        "client_id": "client-a",
                        "document_type": "efatura",
                        "invoice_no": "FSR2026000000001",
                        "supplier": {"tax_id": "5910611341"},
                    },
                    ubl_content=supplier_ubl("1111111111"),
                )

        self.assertEqual(adapter.calls, 0)

    def test_qnb_provider_reconciles_efatura_by_local_invoice_number(self) -> None:
        class StatusAdapter:
            def get_outgoing_invoice_status_by_local_invoice_no(
                self, credentials: object, *, invoice_no: str
            ) -> QnbOutgoingInvoiceStatus:
                return QnbOutgoingInvoiceStatus(
                    document_oid="oid-reconciled",
                    status_code="3",
                    processing_state="processed",
                    status_text="ISLENDI",
                    ettn="11111111-2222-3333-4444-555555555555",
                )

        with tempfile.TemporaryDirectory() as temp_dir:
            store = JsonWorkflowStore(Path(temp_dir) / "store.json")
            cipher = QnbCredentialCipher(Fernet.generate_key())
            store.save_qnb_connection(
                client_id="client-a",
                connection={
                    "status": "active",
                    "environment": "test",
                    "base_url": "https://erpefaturatest2.qnbesolutions.com.tr/efatura/ws",
                    "username": "sandbox-user",
                    "credential_ciphertext": cipher.encrypt("sandbox-password"),
                    "vkn": "5910611341",
                    "erp_code": "FSR31422",
                },
            )
            provider = QnbSandboxOutgoingInvoiceProvider(
                store=store, env={}, efatura_adapter=StatusAdapter(), credential_cipher=cipher
            )

            result = provider.reconcile(
                invoice={
                    "client_id": "client-a",
                    "document_type": "efatura",
                    "invoice_no": "FSR2026000000001",
                    "supplier": {"tax_id": "5910611341"},
                    "ubl_base64": base64.b64encode(supplier_ubl("5910611341")).decode("ascii"),
                },
                attempt={"attempt_id": "attempt-1"},
            )

        self.assertEqual(result["status"], "sent")
        self.assertEqual(result["provider_document_id"], "oid-reconciled")
        self.assertEqual(result["evidence"]["lookup"], "local_invoice_no")

    def test_post_submit_unparseable_response_is_unknown_not_failed(self) -> None:
        class AmbiguousAdapter:
            def send_outgoing_invoice_ubl(self, *args: object, **kwargs: object) -> object:
                raise ValueError("QNB SOAP response could not be parsed")

        with tempfile.TemporaryDirectory() as temp_dir:
            store = JsonWorkflowStore(Path(temp_dir) / "store.json")
            cipher = QnbCredentialCipher(Fernet.generate_key())
            store.save_qnb_connection(
                client_id="client-a",
                connection={
                    "status": "active",
                    "environment": "test",
                    "base_url": "https://erpefaturatest2.qnbesolutions.com.tr/efatura/ws",
                    "username": "sandbox-user",
                    "credential_ciphertext": cipher.encrypt("sandbox-password"),
                    "vkn": "5910611341",
                    "erp_code": "FSR31422",
                },
            )
            provider = QnbSandboxOutgoingInvoiceProvider(
                store=store,
                env={
                    "FISORA_QNB_SANDBOX_SENDER_LABEL": "urn:mail:sendergb@example.test",
                    "FISORA_QNB_SANDBOX_RECIPIENT_LABEL": "urn:mail:receiverpk@example.test",
                },
                efatura_adapter=AmbiguousAdapter(),
                credential_cipher=cipher,
            )

            with self.assertRaises(OutgoingProviderOutcomeUnknown):
                provider.send(
                    invoice={
                        "client_id": "client-a",
                        "document_type": "efatura",
                        "invoice_no": "FSR2026000000001",
                        "supplier": {"tax_id": "5910611341"},
                    },
                    ubl_content=supplier_ubl("5910611341"),
                )


if __name__ == "__main__":
    unittest.main()
