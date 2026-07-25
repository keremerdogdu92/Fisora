from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
import sys
from typing import Any, Callable
from uuid import uuid4


ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.domain.outgoing_invoices import OutgoingInvoiceService  # noqa: E402
from app.domain.qnb_credentials import QnbCredentialCipher, validate_qnb_endpoint  # noqa: E402
from app.domain.qnb_earsiv import is_qnb_earsiv_test_endpoint  # noqa: E402
from app.domain.qnb_efatura import QnbConnectionCredentials, QnbSoapEfaturaAdapter  # noqa: E402
from app.domain.qnb_outgoing import build_outgoing_invoice_provider  # noqa: E402
from app.persistence.workflow_store import JsonWorkflowStore  # noqa: E402
from app.services.document_service import DocumentService  # noqa: E402


def load_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, raw_value = line.split("=", 1)
        value = raw_value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
            value = value[1:-1]
        values[name.strip()] = value
    return values


def validate_plan_endpoints(plan: dict[str, Any]) -> None:
    document_type = str(plan.get("document_type") or "")
    if document_type == "efatura":
        validate_qnb_endpoint(str(plan.get("efatura_base_url") or ""), "test")
        return
    if document_type == "earsiv":
        if not is_qnb_earsiv_test_endpoint(str(plan.get("earsiv_user_service_url") or "")) or not is_qnb_earsiv_test_endpoint(
            str(plan.get("earsiv_service_url") or "")
        ):
            raise ValueError("QNB e-Arsiv acceptance requires test endpoints")
        return
    raise ValueError("Acceptance document type must be efatura or earsiv")


def build_plan(env: dict[str, str], *, document_type: str, output_dir: Path) -> dict[str, Any]:
    now = datetime.now(UTC)
    normalized_type = str(document_type or "").strip().lower()
    invoice_no = (
        f"FSR{now.year}{uuid4().int % 1_000_000_000:09d}"
        if normalized_type == "efatura"
        else f"EAR{now.year}{uuid4().int % 1_000_000_000:09d}"
    )
    sender_environment = str(env.get("QNB_EFATURA_SENDER_ENV") or "TEST2").upper()
    efatura_prefix = f"QNB_EFATURA_{sender_environment}_"
    if normalized_type == "efatura":
        supplier_tax_id = str(env.get(f"{efatura_prefix}VKN") or "")
        customer_tax_id = str(env.get("QNB_EFATURA_TEST1_VKN") or "")
        profile = "TEMELFATURA"
    else:
        supplier_tax_id = str(env.get("QNB_EARSIV_TEST_VKN") or "")
        customer_tax_id = str(env.get("QNB_EARSIV_TEST_CUSTOMER_TCKN") or "11111111111")
        profile = "EARSIVFATURA"
    plan = {
        "client_id": "qnb-outgoing-sandbox-acceptance",
        "document_type": normalized_type,
        "invoice_no": invoice_no,
        "supplier_tax_id": supplier_tax_id,
        "customer_tax_id": customer_tax_id,
        "efatura_base_url": str(env.get(f"{efatura_prefix}BASE_URL") or ""),
        "earsiv_user_service_url": str(env.get("QNB_EARSIV_USER_SERVICE_URL") or ""),
        "earsiv_service_url": str(env.get("QNB_EARSIV_TEST_BASE_URL") or ""),
        "sender_label_configured": bool(env.get("FISORA_QNB_SANDBOX_SENDER_LABEL")),
        "recipient_label_configured": bool(env.get("FISORA_QNB_SANDBOX_RECIPIENT_LABEL")),
        "output_dir": str(output_dir),
        "draft_payload": {
            "document_type": normalized_type,
            "profile": profile,
            "invoice_no": invoice_no,
            "issue_date": now.date().isoformat(),
            "currency": "TRY",
            "supplier": {"tax_id": supplier_tax_id, "title": "FISORA QNB SANDBOX"},
            "customer": {"tax_id": customer_tax_id, "title": "FISORA TEST MUSTERI"},
            "lines": [{"name": "Sandbox entegrasyon testi", "quantity": "1", "unit_price": "100.00", "vat_rate": "20"}],
        },
        "totals": {"net_amount": "100.00", "tax_amount": "20.00", "payable_amount": "120.00"},
    }
    validate_plan_endpoints(plan)
    return plan


def execute_plan(
    plan: dict[str, Any],
    *,
    confirm_send: bool,
    service_factory: Callable[[], Any],
) -> dict[str, Any]:
    if not confirm_send:
        return {"ok": True, "sent": False, "plan": _public_plan(plan)}
    service = service_factory()
    client_id = str(plan["client_id"])
    actor = "qnb-sandbox-operator"
    draft = service.create_draft(client_id=client_id, payload=plan["draft_payload"], actor_user_id=actor)
    approved = service.approve(client_id=client_id, invoice_id=str(draft["invoice_id"]), actor_user_id=actor)
    sent = service.send(
        client_id=client_id,
        invoice_id=str(approved["invoice_id"]),
        idempotency_key=f"qnb-sandbox-acceptance:{plan['invoice_no']}",
        actor_user_id=actor,
    )
    confirmed = (
        str(sent.get("status") or "") == "sent"
        and bool(str(sent.get("provider_document_id") or "").strip())
        and bool(str(sent.get("canonical_document_ref") or "").strip())
        and str(sent.get("accounting_link_status") or "") not in {"", "failed"}
    )
    return {
        "ok": confirmed,
        "sent": str(sent.get("status") or "") == "sent",
        "status": str(sent.get("status") or ""),
        "invoice_id": str(sent.get("invoice_id") or ""),
        "attempt_id": str(sent.get("current_attempt_id") or ""),
        "provider": str(sent.get("provider") or ""),
        "provider_document_id": str(sent.get("provider_document_id") or ""),
        "provider_transaction_id": str(sent.get("provider_transaction_id") or ""),
        "provider_invoice_no": str(sent.get("provider_invoice_no") or ""),
        "provider_status": str(sent.get("provider_status") or ""),
        "ubl_sha256": str(sent.get("ubl_sha256") or ""),
        "canonical_document_ref": str(sent.get("canonical_document_ref") or ""),
        "accounting_link_status": str(sent.get("accounting_link_status") or ""),
    }


def _public_plan(plan: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in plan.items() if key != "draft_payload"}


def _service_factory(env: dict[str, str], plan: dict[str, Any], output_dir: Path) -> OutgoingInvoiceService:
    output_dir.mkdir(parents=True, exist_ok=True)
    runtime_env = dict(env)
    runtime_env["FISORA_OUTGOING_PROVIDER_MODE"] = "qnb_sandbox"
    runtime_env["FISORA_QNB_CREDENTIAL_KEY_FILE"] = str(output_dir / ".credential.key")
    store = JsonWorkflowStore(output_dir / "workflow-store.json")
    cipher = QnbCredentialCipher.from_env(runtime_env)
    document_type = str(plan["document_type"])
    sender_environment = str(env.get("QNB_EFATURA_SENDER_ENV") or "TEST2").upper()
    efatura_prefix = f"QNB_EFATURA_{sender_environment}_"
    if document_type == "efatura":
        username = str(env.get(f"{efatura_prefix}USERNAME") or "")
        password = str(env.get(f"{efatura_prefix}PASSWORD") or "")
        vkn = str(env.get(f"{efatura_prefix}VKN") or "")
        _ensure_efatura_labels(runtime_env)
    else:
        username = str(env.get("QNB_EARSIV_TEST_USERNAME") or "")
        password = str(env.get("QNB_EARSIV_TEST_PASSWORD") or "")
        vkn = str(env.get("QNB_EARSIV_TEST_VKN") or "")
    connection: dict[str, Any] = {
        "status": "active",
        "environment": "test",
        "base_url": str(plan.get("efatura_base_url") or "https://erpefaturatest2.qnbesolutions.com.tr/efatura/ws"),
        "username": username,
        "credential_ciphertext": cipher.encrypt(password),
        "vkn": vkn,
        "erp_code": str(env.get("QNB_ERP_CODE") or env.get("FISORA_QNB_ERP_CODE") or "FSR31422"),
    }
    if document_type == "earsiv":
        connection.update(
            {
                "earsiv_username": username,
                "earsiv_credential_ciphertext": cipher.encrypt(password),
            }
        )
    client_id = str(plan["client_id"])
    store.save_qnb_connection(client_id=client_id, connection=connection)
    store.upsert_client(
        client_id=client_id,
        profile={"client_id": client_id, "title": "QNB Sandbox Acceptance", "tax_id": vkn},
        onboarding={"is_ready": False},
    )
    store.upsert_portal_user(
        user_id="qnb-sandbox-operator",
        display_name="QNB Sandbox Operator",
        role="accountant",
        allowed_client_ids=[client_id],
    )
    documents = DocumentService(
        store=store,
        document_storage_path=output_dir / "documents",
        record_operation_event=lambda **kwargs: dict(kwargs),
        require_client_access=lambda **kwargs: {"allowed": True},
    )
    return OutgoingInvoiceService(
        store=store,
        provider=build_outgoing_invoice_provider(runtime_env, store),
        document_service=documents,
    )


def _ensure_efatura_labels(env: dict[str, str]) -> None:
    if env.get("FISORA_QNB_SANDBOX_SENDER_LABEL") and env.get("FISORA_QNB_SANDBOX_RECIPIENT_LABEL"):
        return
    sender_environment = str(env.get("QNB_EFATURA_SENDER_ENV") or "TEST2").upper()
    receiver_environment = str(env.get("QNB_EFATURA_RECEIVER_ENV") or "TEST1").upper()

    def credentials(environment: str) -> QnbConnectionCredentials:
        prefix = f"QNB_EFATURA_{environment}_"
        return QnbConnectionCredentials(
            base_url=str(env.get(f"{prefix}BASE_URL") or ""),
            username=str(env.get(f"{prefix}USERNAME") or ""),
            password=str(env.get(f"{prefix}PASSWORD") or ""),
            vkn=str(env.get(f"{prefix}VKN") or ""),
            erp_code=str(env.get("QNB_ERP_CODE") or env.get("FISORA_QNB_ERP_CODE") or "FSR31422"),
        )

    sender = credentials(sender_environment)
    receiver = credentials(receiver_environment)
    sender_adapter = QnbSoapEfaturaAdapter(timeout=30)
    receiver_adapter = QnbSoapEfaturaAdapter(timeout=30)
    try:
        sender_labels = sender_adapter.list_active_mailbox_labels(sender)
        receiver_labels = receiver_adapter.list_active_mailbox_labels(receiver)
    finally:
        sender_adapter.close_session(sender)
        receiver_adapter.close_session(receiver)
    sender_label = next((item.label for item in sender_labels if item.kind.upper() == "GB"), "")
    recipient_label = next((item.label for item in receiver_labels if item.kind.upper() == "PK"), "")
    if not sender_label or not recipient_label:
        raise ValueError("QNB sandbox GB/PK mailbox labels could not be discovered")
    env["FISORA_QNB_SANDBOX_SENDER_LABEL"] = sender_label
    env["FISORA_QNB_SANDBOX_RECIPIENT_LABEL"] = recipient_label


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run QNB outgoing sandbox acceptance through the common service.")
    parser.add_argument("--env-file", type=Path, default=ROOT / ".env.qnb.local")
    parser.add_argument("--document-type", choices=("efatura", "earsiv"), required=True)
    parser.add_argument("--output-dir", type=Path, default=ROOT / "exports" / "qnb-outgoing-service-acceptance")
    parser.add_argument("--confirm-send", action="store_true", help="Required for the external sandbox side effect.")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        env = load_env_file(args.env_file)
        plan = build_plan(env, document_type=args.document_type, output_dir=args.output_dir)
        result = execute_plan(
            plan,
            confirm_send=args.confirm_send,
            service_factory=lambda: _service_factory(env, plan, args.output_dir),
        )
    except Exception as exc:
        print(json.dumps({"ok": False, "error_type": exc.__class__.__name__, "error": str(exc)[:240]}, sort_keys=True))
        return 1
    if args.confirm_send:
        args.output_dir.mkdir(parents=True, exist_ok=True)
        (args.output_dir / f"{plan['invoice_no']}.summary.json").write_text(
            json.dumps(result, ensure_ascii=True, sort_keys=True, indent=2), encoding="utf-8"
        )
    print(json.dumps(result, ensure_ascii=True, sort_keys=True))
    return 0 if result.get("ok") else 2


if __name__ == "__main__":
    raise SystemExit(main())
