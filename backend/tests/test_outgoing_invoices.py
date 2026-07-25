from __future__ import annotations

import base64
import os
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
from xml.etree import ElementTree


ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

try:
    from fastapi.testclient import TestClient

    from app.api import phase0
    from app.main import app
except ModuleNotFoundError:
    TestClient = None
    phase0 = None
    app = None

from app.domain.outgoing_invoices import (
    OutgoingInvoiceService,
    OutgoingProviderOutcomeUnknown,
    OutgoingProviderReceipt,
)
from app.persistence.workflow_store import JsonWorkflowStore
from app.services.document_service import DocumentService


def invoice_payload(*, document_type: str = "earsiv", profile: str = "EARSIVFATURA") -> dict[str, object]:
    return {
        "document_type": document_type,
        "profile": profile,
        "invoice_no": "GIB2026000000001",
        "issue_date": "2026-07-13",
        "currency": "TRY",
        "supplier": {"tax_id": "5910611340", "title": "Fisora Test", "tax_office": "Kadikoy"},
        "customer": {"tax_id": "11111111111", "title": "Test Musteri"},
        "lines": [
            {"name": "Danismanlik", "quantity": "2", "unit_price": "100.00", "vat_rate": "20"},
            {"name": "Kurulum", "quantity": "1", "unit_price": "50.00", "vat_rate": "10"},
        ],
    }


class OutgoingInvoiceServiceTests(unittest.TestCase):
    def test_draft_approval_builds_frozen_ubl_with_exact_totals(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            service = OutgoingInvoiceService(store=JsonWorkflowStore(Path(temp_dir) / "store.json"))
            draft = service.create_draft(client_id="client-a", payload=invoice_payload(), actor_user_id="accountant")
            approved = service.approve(
                client_id="client-a", invoice_id=draft["invoice_id"], actor_user_id="accountant"
            )

        self.assertEqual(draft["totals"], {"net_amount": "250.00", "tax_amount": "45.00", "payable_amount": "295.00"})
        self.assertEqual(approved["status"], "approved")
        self.assertEqual(len(approved["ubl_sha256"]), 64)
        root = ElementTree.fromstring(base64.b64decode(approved["ubl_base64"]))
        self.assertTrue(root.tag.endswith("}Invoice"))

    def test_send_requires_approval_and_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            service = OutgoingInvoiceService(store=JsonWorkflowStore(Path(temp_dir) / "store.json"))
            draft = service.create_draft(client_id="client-a", payload=invoice_payload(), actor_user_id="accountant")
            with self.assertRaisesRegex(ValueError, "approved"):
                service.send(
                    client_id="client-a",
                    invoice_id=draft["invoice_id"],
                    idempotency_key="send-1",
                    actor_user_id="accountant",
                )
            approved = service.approve(client_id="client-a", invoice_id=draft["invoice_id"], actor_user_id="accountant")
            sent = service.send(
                client_id="client-a", invoice_id=approved["invoice_id"], idempotency_key="send-2", actor_user_id="accountant"
            )
            repeated = service.send(
                client_id="client-a", invoice_id=approved["invoice_id"], idempotency_key="send-2", actor_user_id="accountant"
            )

        self.assertEqual(sent["status"], "sent")
        self.assertEqual(sent["provider"], "fake")
        self.assertEqual(repeated["provider_document_id"], sent["provider_document_id"])
        self.assertEqual(len(repeated["history"]), 3)

    def test_invoice_is_tenant_scoped(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            service = OutgoingInvoiceService(store=JsonWorkflowStore(Path(temp_dir) / "store.json"))
            draft = service.create_draft(client_id="client-a", payload=invoice_payload(), actor_user_id="accountant")
            with self.assertRaisesRegex(ValueError, "not found"):
                service.get(client_id="client-b", invoice_id=draft["invoice_id"])

    def test_post_submit_unknown_outcome_blocks_same_and_new_keys(self) -> None:
        class UnknownProvider:
            def __init__(self) -> None:
                self.calls = 0

            def send(self, *, invoice: dict[str, object], ubl_content: bytes) -> dict[str, object]:
                self.calls += 1
                raise OutgoingProviderOutcomeUnknown("provider response was not received")

        with tempfile.TemporaryDirectory() as temp_dir:
            store = JsonWorkflowStore(Path(temp_dir) / "store.json")
            provider = UnknownProvider()
            service = OutgoingInvoiceService(store=store, provider=provider)
            draft = service.create_draft(client_id="client-a", payload=invoice_payload(), actor_user_id="accountant")
            approved = service.approve(client_id="client-a", invoice_id=draft["invoice_id"], actor_user_id="accountant")

            first = service.send(
                client_id="client-a", invoice_id=approved["invoice_id"], idempotency_key="unknown-1", actor_user_id="accountant"
            )
            repeated = service.send(
                client_id="client-a", invoice_id=approved["invoice_id"], idempotency_key="unknown-1", actor_user_id="accountant"
            )
            with self.assertRaisesRegex(ValueError, "approved"):
                service.send(
                    client_id="client-a",
                    invoice_id=approved["invoice_id"],
                    idempotency_key="unknown-2",
                    actor_user_id="accountant",
                )

        self.assertEqual(first["status"], "reconciliation_required")
        self.assertEqual(repeated["status"], "reconciliation_required")
        self.assertEqual(provider.calls, 1)

    def test_send_rejects_tampered_frozen_ubl_before_provider_call(self) -> None:
        class RecordingProvider:
            def __init__(self) -> None:
                self.calls = 0

            def send(self, *, invoice: dict[str, object], ubl_content: bytes) -> dict[str, object]:
                self.calls += 1
                return {}

        with tempfile.TemporaryDirectory() as temp_dir:
            store = JsonWorkflowStore(Path(temp_dir) / "store.json")
            provider = RecordingProvider()
            service = OutgoingInvoiceService(store=store, provider=provider)
            draft = service.create_draft(client_id="client-a", payload=invoice_payload(), actor_user_id="accountant")
            approved = service.approve(client_id="client-a", invoice_id=draft["invoice_id"], actor_user_id="accountant")
            approved["ubl_sha256"] = "0" * 64
            store.save_outgoing_invoice(client_id="client-a", invoice=approved)

            with self.assertRaisesRegex(ValueError, "hash"):
                service.send(
                    client_id="client-a", invoice_id=approved["invoice_id"], idempotency_key="tampered-1", actor_user_id="accountant"
                )

        self.assertEqual(provider.calls, 0)

    def test_send_records_append_only_attempt_lifecycle(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = JsonWorkflowStore(Path(temp_dir) / "store.json")
            service = OutgoingInvoiceService(store=store)
            draft = service.create_draft(client_id="client-a", payload=invoice_payload(), actor_user_id="accountant")
            approved = service.approve(client_id="client-a", invoice_id=draft["invoice_id"], actor_user_id="accountant")

            sent = service.send(
                client_id="client-a",
                invoice_id=approved["invoice_id"],
                idempotency_key="attempt-events-1",
                actor_user_id="accountant",
            )
            attempts = store.list_outgoing_invoice_attempts(
                client_id="client-a", invoice_id=approved["invoice_id"]
            )

        self.assertEqual(sent["status"], "sent")
        self.assertEqual(len(attempts), 1)
        self.assertEqual(attempts[0]["state"], "sent")
        self.assertEqual(attempts[0]["provider"], "fake")
        self.assertEqual(
            [event["event"] for event in attempts[0]["events"]],
            ["claimed", "preflight_passed", "request_started", "response_received"],
        )

    def test_concurrent_same_key_callers_share_terminal_result(self) -> None:
        class BlockingProvider:
            provider_name = "fake"
            provider_operation = "blocking_fake"

            def __init__(self) -> None:
                self.calls = 0
                self.started = threading.Event()
                self.release = threading.Event()

            def send(self, *, invoice: dict[str, object], ubl_content: bytes) -> OutgoingProviderReceipt:
                self.calls += 1
                self.started.set()
                self.release.wait(timeout=5)
                return OutgoingProviderReceipt(
                    provider="fake",
                    provider_operation="blocking_fake",
                    provider_document_id="fake-terminal",
                    provider_status="accepted",
                )

        with tempfile.TemporaryDirectory() as temp_dir:
            store = JsonWorkflowStore(Path(temp_dir) / "store.json")
            provider = BlockingProvider()
            service = OutgoingInvoiceService(store=store, provider=provider, claim_wait_seconds=5)
            draft = service.create_draft(client_id="client-a", payload=invoice_payload(), actor_user_id="accountant")
            approved = service.approve(client_id="client-a", invoice_id=draft["invoice_id"], actor_user_id="accountant")
            results: list[dict[str, object]] = []

            def send_once() -> None:
                results.append(
                    service.send(
                        client_id="client-a",
                        invoice_id=approved["invoice_id"],
                        idempotency_key="concurrent-1",
                        actor_user_id="accountant",
                    )
                )

            first = threading.Thread(target=send_once)
            second = threading.Thread(target=send_once)
            first.start()
            self.assertTrue(provider.started.wait(timeout=2))
            second.start()
            time.sleep(0.1)
            provider.release.set()
            first.join(timeout=5)
            second.join(timeout=5)

        self.assertEqual(provider.calls, 1)
        self.assertEqual(len(results), 2)
        self.assertEqual({result["status"] for result in results}, {"sent"})
        self.assertEqual({result["provider_document_id"] for result in results}, {"fake-terminal"})

    def test_reconcile_closes_unknown_outcome_only_with_positive_provider_evidence(self) -> None:
        class ReconcilingProvider:
            provider_name = "qnb_sandbox"
            provider_operation = "belgeGonderExt"

            def send(self, *, invoice: dict[str, object], ubl_content: bytes) -> object:
                raise OutgoingProviderOutcomeUnknown("response lost")

            def reconcile(self, *, invoice: dict[str, object], attempt: dict[str, object]) -> dict[str, object]:
                return {
                    "status": "sent",
                    "provider_document_id": "oid-reconciled",
                    "provider_status": "processed",
                    "evidence": {"lookup": "local_invoice_no"},
                }

        with tempfile.TemporaryDirectory() as temp_dir:
            store = JsonWorkflowStore(Path(temp_dir) / "store.json")
            service = OutgoingInvoiceService(store=store, provider=ReconcilingProvider())
            draft = service.create_draft(client_id="client-a", payload=invoice_payload(), actor_user_id="accountant")
            approved = service.approve(client_id="client-a", invoice_id=draft["invoice_id"], actor_user_id="accountant")
            unknown = service.send(
                client_id="client-a",
                invoice_id=approved["invoice_id"],
                idempotency_key="reconcile-1",
                actor_user_id="accountant",
            )

            reconciled = service.reconcile(
                client_id="client-a", invoice_id=approved["invoice_id"], actor_user_id="accountant"
            )
            attempt = store.get_outgoing_invoice_attempt(
                client_id="client-a", attempt_id=str(reconciled["current_attempt_id"])
            )

        self.assertEqual(unknown["status"], "reconciliation_required")
        self.assertEqual(reconciled["status"], "sent")
        self.assertEqual(reconciled["provider_document_id"], "oid-reconciled")
        self.assertEqual(
            [event["event"] for event in attempt["events"]][-2:],
            ["reconciliation_started", "reconciliation_confirmed_sent"],
        )

    def test_reconcile_preserves_unknown_when_provider_has_no_terminal_evidence(self) -> None:
        class UnknownProvider:
            provider_name = "qnb_sandbox"
            provider_operation = "belgeGonderExt"

            def send(self, *, invoice: dict[str, object], ubl_content: bytes) -> object:
                raise OutgoingProviderOutcomeUnknown("response lost")

            def reconcile(self, *, invoice: dict[str, object], attempt: dict[str, object]) -> dict[str, object]:
                return {"status": "reconciliation_required", "evidence": {"lookup": "not_conclusive"}}

        with tempfile.TemporaryDirectory() as temp_dir:
            store = JsonWorkflowStore(Path(temp_dir) / "store.json")
            service = OutgoingInvoiceService(store=store, provider=UnknownProvider())
            draft = service.create_draft(client_id="client-a", payload=invoice_payload(), actor_user_id="accountant")
            approved = service.approve(client_id="client-a", invoice_id=draft["invoice_id"], actor_user_id="accountant")
            service.send(
                client_id="client-a",
                invoice_id=approved["invoice_id"],
                idempotency_key="reconcile-unknown-1",
                actor_user_id="accountant",
            )

            reconciled = service.reconcile(
                client_id="client-a", invoice_id=approved["invoice_id"], actor_user_id="accountant"
            )

        self.assertEqual(reconciled["status"], "reconciliation_required")

    def test_concurrent_reconciliation_has_single_owner(self) -> None:
        class BlockingReconciliationProvider:
            provider_name = "qnb_sandbox"
            provider_operation = "belgeGonderExt"

            def __init__(self) -> None:
                self.reconcile_calls = 0
                self.started = threading.Event()
                self.release = threading.Event()

            def send(self, *, invoice: dict[str, object], ubl_content: bytes) -> object:
                raise OutgoingProviderOutcomeUnknown("response lost")

            def reconcile(self, *, invoice: dict[str, object], attempt: dict[str, object]) -> dict[str, object]:
                self.reconcile_calls += 1
                self.started.set()
                self.release.wait(timeout=5)
                return {
                    "status": "sent",
                    "provider_document_id": "oid-single-owner",
                    "provider_status": "processed",
                }

        with tempfile.TemporaryDirectory() as temp_dir:
            store = JsonWorkflowStore(Path(temp_dir) / "store.json")
            provider = BlockingReconciliationProvider()
            service = OutgoingInvoiceService(store=store, provider=provider)
            draft = service.create_draft(client_id="client-a", payload=invoice_payload(), actor_user_id="accountant")
            approved = service.approve(client_id="client-a", invoice_id=draft["invoice_id"], actor_user_id="accountant")
            service.send(
                client_id="client-a",
                invoice_id=approved["invoice_id"],
                idempotency_key="reconcile-single-owner-1",
                actor_user_id="accountant",
            )
            results: list[dict[str, object]] = []

            def reconcile_once() -> None:
                results.append(
                    service.reconcile(
                        client_id="client-a", invoice_id=approved["invoice_id"], actor_user_id="accountant"
                    )
                )

            first = threading.Thread(target=reconcile_once)
            first.start()
            self.assertTrue(provider.started.wait(timeout=5))
            with self.assertRaisesRegex(ValueError, "already active"):
                service.reconcile(
                    client_id="client-a", invoice_id=approved["invoice_id"], actor_user_id="accountant"
                )
            provider.release.set()
            first.join(timeout=5)

        self.assertEqual(provider.reconcile_calls, 1)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["status"], "sent")

    def test_expired_reconciliation_owner_cannot_finalize_after_lease_is_stolen(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = JsonWorkflowStore(Path(temp_dir) / "store.json")
            service = OutgoingInvoiceService(store=store)
            draft = service.create_draft(client_id="client-a", payload=invoice_payload(), actor_user_id="accountant")
            approved = service.approve(client_id="client-a", invoice_id=draft["invoice_id"], actor_user_id="accountant")
            claimed, _, attempt = store.claim_outgoing_invoice_attempt(
                client_id="client-a",
                invoice_id=approved["invoice_id"],
                idempotency_key="lease-owner-1",
                ubl_sha256=approved["ubl_sha256"],
                provider="qnb_sandbox",
                provider_operation="belgeGonderExt",
            )
            store.append_outgoing_invoice_attempt_event(
                client_id="client-a",
                attempt_id=attempt["attempt_id"],
                event="request_started",
                state="request_started",
            )
            store.append_outgoing_invoice_attempt_event(
                client_id="client-a",
                attempt_id=attempt["attempt_id"],
                event="outcome_unknown",
                state="reconciliation_required",
            )
            first_claimed, _ = store.claim_outgoing_invoice_reconciliation(
                client_id="client-a",
                attempt_id=attempt["attempt_id"],
                owner_id="owner-1",
                stale_before="2999-01-01T00:00:00+00:00",
                lease_expires_at="2000-01-01T00:00:00+00:00",
            )
            second_claimed, _ = store.claim_outgoing_invoice_reconciliation(
                client_id="client-a",
                attempt_id=attempt["attempt_id"],
                owner_id="owner-2",
                stale_before="2999-01-01T00:00:00+00:00",
                lease_expires_at="2999-01-01T00:00:00+00:00",
            )
            stale_finalized, _ = store.finalize_outgoing_invoice_attempt(
                client_id="client-a",
                attempt_id=attempt["attempt_id"],
                expected_state="reconciling",
                event="reconciliation_confirmed_sent",
                state="sent",
                reconciliation_owner="owner-1",
            )
            winner_finalized, final_attempt = store.finalize_outgoing_invoice_attempt(
                client_id="client-a",
                attempt_id=attempt["attempt_id"],
                expected_state="reconciling",
                event="reconciliation_confirmed_sent",
                state="sent",
                reconciliation_owner="owner-2",
            )

        self.assertTrue(claimed)
        self.assertTrue(first_claimed)
        self.assertTrue(second_claimed)
        self.assertFalse(stale_finalized)
        self.assertTrue(winner_finalized)
        self.assertEqual(
            [event["event"] for event in final_attempt["events"]].count("reconciliation_confirmed_sent"), 1
        )

    def test_reconcile_recovers_request_started_sending_after_process_crash(self) -> None:
        class RecoveryProvider:
            provider_name = "qnb_sandbox"
            provider_operation = "belgeGonderExt"

            def reconcile(self, *, invoice: dict[str, object], attempt: dict[str, object]) -> dict[str, object]:
                return {
                    "status": "sent",
                    "provider_document_id": "oid-recovered",
                    "provider_status": "processed",
                    "evidence": {"lookup": "local_invoice_no"},
                }

        with tempfile.TemporaryDirectory() as temp_dir:
            store = JsonWorkflowStore(Path(temp_dir) / "store.json")
            service = OutgoingInvoiceService(
                store=store, provider=RecoveryProvider(), reconciliation_stale_seconds=0
            )
            draft = service.create_draft(client_id="client-a", payload=invoice_payload(), actor_user_id="accountant")
            approved = service.approve(client_id="client-a", invoice_id=draft["invoice_id"], actor_user_id="accountant")
            claimed, sending, attempt = store.claim_outgoing_invoice_attempt(
                client_id="client-a",
                invoice_id=approved["invoice_id"],
                idempotency_key="crash-window-1",
                ubl_sha256=approved["ubl_sha256"],
                provider="qnb_sandbox",
                provider_operation="belgeGonderExt",
            )
            store.append_outgoing_invoice_attempt_event(
                client_id="client-a",
                attempt_id=attempt["attempt_id"],
                event="request_started",
                state="request_started",
            )

            recovered = service.reconcile(
                client_id="client-a", invoice_id=approved["invoice_id"], actor_user_id="accountant"
            )

        self.assertTrue(claimed)
        self.assertEqual(sending["status"], "sending")
        self.assertEqual(recovered["status"], "sent")
        self.assertEqual(recovered["provider_document_id"], "oid-recovered")

    def test_confirmed_qnb_send_queues_exact_ubl_as_canonical_sales_source(self) -> None:
        class QnbProvider:
            provider_name = "qnb_sandbox"
            provider_operation = "belgeGonderExt"

            def send(self, *, invoice: dict[str, object], ubl_content: bytes) -> OutgoingProviderReceipt:
                return OutgoingProviderReceipt(
                    provider="qnb_sandbox",
                    provider_operation="belgeGonderExt",
                    provider_document_id="oid-123",
                    provider_status="accepted",
                    evidence={"ubl_sha256": __import__("hashlib").sha256(ubl_content).hexdigest()},
                )

        class RecordingDocumentService:
            def __init__(self) -> None:
                self.calls: list[dict[str, object]] = []

            def store_document_upload(self, **kwargs: object) -> dict[str, object]:
                self.calls.append(kwargs)
                return {"document_ref": "document-1", "processing_job": {"id": "job-1", "status": "queued"}}

        with tempfile.TemporaryDirectory() as temp_dir:
            store = JsonWorkflowStore(Path(temp_dir) / "store.json")
            documents = RecordingDocumentService()
            service = OutgoingInvoiceService(store=store, provider=QnbProvider(), document_service=documents)
            draft = service.create_draft(client_id="client-a", payload=invoice_payload(), actor_user_id="accountant")
            approved = service.approve(client_id="client-a", invoice_id=draft["invoice_id"], actor_user_id="accountant")
            sent = service.send(
                client_id="client-a",
                invoice_id=approved["invoice_id"],
                idempotency_key="canonical-sales-1",
                actor_user_id="accountant",
            )

        call = documents.calls[0]
        self.assertEqual(call["content"], base64.b64decode(approved["ubl_base64"]))
        self.assertEqual(call["sha256"], approved["ubl_sha256"])
        self.assertEqual(call["document_type"], "einvoice_xml")
        self.assertEqual(call["intake_category"], "sales_invoice")
        self.assertEqual(call["uploaded_by_user_id"], "accountant")
        self.assertEqual(sent["canonical_document_ref"], "document-1")
        self.assertEqual(sent["accounting_link_status"], "queued")

    def test_confirmed_qnb_source_is_stored_with_sales_direction_and_attempt_link(self) -> None:
        class QnbProvider:
            provider_name = "qnb_sandbox"
            provider_operation = "belgeGonderExt"

            def send(self, *, invoice: dict[str, object], ubl_content: bytes) -> OutgoingProviderReceipt:
                return OutgoingProviderReceipt(
                    provider="qnb_sandbox",
                    provider_operation="belgeGonderExt",
                    provider_document_id="oid-123",
                    provider_status="accepted",
                    evidence={"ubl_sha256": __import__("hashlib").sha256(ubl_content).hexdigest()},
                )

        with tempfile.TemporaryDirectory() as temp_dir:
            store = JsonWorkflowStore(Path(temp_dir) / "store.json")
            store.upsert_client(
                client_id="client-a",
                profile={"client_id": "client-a", "title": "Fisora Test", "tax_id": "5910611340"},
                onboarding={"is_ready": False},
            )
            store.upsert_portal_user(
                user_id="accountant",
                display_name="Accountant",
                role="accountant",
                allowed_client_ids=["client-a"],
            )
            document_service = DocumentService(
                store=store,
                document_storage_path=Path(temp_dir) / "documents",
                record_operation_event=lambda **kwargs: dict(kwargs),
                require_client_access=lambda **kwargs: {"allowed": True},
            )
            service = OutgoingInvoiceService(
                store=store, provider=QnbProvider(), document_service=document_service
            )
            draft = service.create_draft(client_id="client-a", payload=invoice_payload(), actor_user_id="accountant")
            approved = service.approve(client_id="client-a", invoice_id=draft["invoice_id"], actor_user_id="accountant")
            sent = service.send(
                client_id="client-a",
                invoice_id=approved["invoice_id"],
                idempotency_key="canonical-storage-1",
                actor_user_id="accountant",
            )
            workspace = store.get_workspace("client-a")

        document = workspace["uploaded_documents"][0]
        self.assertEqual(document["source_direction"], "sales_invoice")
        self.assertEqual(document["source_outgoing_invoice_id"], sent["invoice_id"])
        self.assertEqual(document["source_outgoing_attempt_id"], sent["current_attempt_id"])
        self.assertEqual(document["source_ubl_sha256"], sent["ubl_sha256"])
        self.assertEqual(workspace["processing_jobs"][0]["status"], "queued")


class OutgoingInvoiceApiTests(unittest.TestCase):
    def test_accountant_can_create_approve_and_fake_send(self) -> None:
        if TestClient is None or phase0 is None or app is None:
            self.skipTest("fastapi is not installed in this Python environment")
        with tempfile.TemporaryDirectory() as temp_dir, patch.dict(
            os.environ, {"FISORA_OUTGOING_PROVIDER_MODE": "fake"}
        ):
            phase0.DEFAULT_STORE_PATH = Path(temp_dir) / "store.json"
            phase0.DEFAULT_DOCUMENT_STORAGE_PATH = Path(temp_dir) / "documents"
            client = TestClient(app)
            client.post("/phase0/store/client", json={"client_id": "client-a", "title": "A", "has_chart_accounts": True})
            client.post(
                "/phase0/store/portal-user",
                json={"user_id": "accountant", "display_name": "Accountant", "role": "accountant", "allowed_client_ids": ["client-a"]},
            )
            headers = {"X-Fisora-User-Id": "accountant"}
            created = client.post("/phase0/outgoing-invoices/client-a/drafts", headers=headers, json=invoice_payload())
            invoice_id = created.json().get("invoice_id", "")
            approved = client.post(f"/phase0/outgoing-invoices/client-a/drafts/{invoice_id}/approve", headers=headers)
            sent = client.post(
                f"/phase0/outgoing-invoices/client-a/drafts/{invoice_id}/send",
                headers=headers,
                json={"idempotency_key": "api-send-1"},
            )

        self.assertEqual(created.status_code, 200, created.text)
        self.assertEqual(approved.status_code, 200, approved.text)
        self.assertEqual(sent.status_code, 200, sent.text)
        self.assertEqual(sent.json()["status"], "sent")
        self.assertEqual(sent.json()["receipt"]["mode"], "local_fake")

    def test_client_user_cannot_manage_outgoing_invoices(self) -> None:
        if TestClient is None or phase0 is None or app is None:
            self.skipTest("fastapi is not installed in this Python environment")
        with tempfile.TemporaryDirectory() as temp_dir:
            phase0.DEFAULT_STORE_PATH = Path(temp_dir) / "store.json"
            client = TestClient(app)
            client.post("/phase0/store/client", json={"client_id": "client-a", "title": "A", "has_chart_accounts": True})
            client.post(
                "/phase0/store/portal-user",
                json={"user_id": "client-user", "display_name": "Client", "role": "client_user", "allowed_client_ids": ["client-a"]},
            )
            response = client.post(
                "/phase0/outgoing-invoices/client-a/drafts",
                headers={"X-Fisora-User-Id": "client-user"},
                json=invoice_payload(),
            )
            reconcile_response = client.post(
                "/phase0/outgoing-invoices/client-a/drafts/invoice-1/reconcile",
                headers={"X-Fisora-User-Id": "client-user"},
            )

        self.assertEqual(response.status_code, 403)
        self.assertEqual(reconcile_response.status_code, 403)


if __name__ == "__main__":
    unittest.main()
