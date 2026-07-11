from __future__ import annotations

import argparse
import json
import sys
import time as time_module
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.domain.qnb_efatura import QnbConnectionCredentials, QnbSoapEfaturaAdapter  # noqa: E402
from app.domain.qnb_sandbox_outgoing import (  # noqa: E402
    QnbSandboxParty,
    build_qnb_sandbox_invoice_ubl,
)


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


def credentials_for(env: dict[str, str], environment: str) -> QnbConnectionCredentials:
    prefix = f"QNB_EFATURA_{environment.upper()}_"
    return QnbConnectionCredentials(
        base_url=env[f"{prefix}BASE_URL"],
        username=env[f"{prefix}USERNAME"],
        password=env[f"{prefix}PASSWORD"],
        vkn=env[f"{prefix}VKN"],
        erp_code=env["QNB_ERP_CODE"],
    )


def select_label(labels, kind: str) -> str:
    return next((item.label for item in labels if item.kind.upper() == kind.upper()), "")


def is_qnb_sandbox_base_url(value: str) -> bool:
    host = str(value or "").lower()
    return "erpefaturatest1.qnbesolutions.com.tr" in host or "erpefaturatest2.qnbesolutions.com.tr" in host


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Send one controlled TEST2 -> TEST1 QNB sandbox e-Fatura.")
    parser.add_argument("--env-file", type=Path, default=ROOT / ".env.qnb.local")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "exports" / "qnb-sandbox-outgoing")
    parser.add_argument("--confirm-send", action="store_true", help="Required for the external QNB send side effect.")
    parser.add_argument("--poll-attempts", type=int, default=5)
    parser.add_argument("--poll-seconds", type=float, default=2.0)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    env = load_env_file(args.env_file)
    sender_environment = env["QNB_EFATURA_SENDER_ENV"].upper()
    receiver_environment = env["QNB_EFATURA_RECEIVER_ENV"].upper()
    sender = credentials_for(env, sender_environment)
    receiver = credentials_for(env, receiver_environment)
    if not is_qnb_sandbox_base_url(sender.base_url) or not is_qnb_sandbox_base_url(receiver.base_url):
        print(json.dumps({"ok": False, "error": "sandbox sender refuses non-test QNB endpoints"}))
        return 1

    sender_adapter = QnbSoapEfaturaAdapter(timeout=30)
    receiver_adapter = QnbSoapEfaturaAdapter(timeout=30)
    sender_label = select_label(sender_adapter.list_active_mailbox_labels(sender), "GB")
    receiver_label = select_label(receiver_adapter.list_active_mailbox_labels(receiver), "PK")
    if not sender_label or not receiver_label:
        print(json.dumps({"ok": False, "error": "required QNB GB/PK mailbox label not found"}))
        return 1

    now = datetime.now(UTC)
    invoice_uuid = str(uuid4()).upper()
    invoice_no = f"FSR{now.year}{uuid4().int % 1_000_000_000:09d}"
    content = build_qnb_sandbox_invoice_ubl(
        invoice_no=invoice_no,
        invoice_uuid=invoice_uuid,
        issue_date=now.date(),
        issue_time=now.time(),
        supplier=QnbSandboxParty(sender.vkn, "FISORA QNB TEST2", sender_label),
        customer=QnbSandboxParty(receiver.vkn, "FISORA QNB TEST1", receiver_label),
    )
    args.output_dir.mkdir(parents=True, exist_ok=True)
    output_path = args.output_dir / f"{invoice_no}.xml"
    output_path.write_bytes(content)
    receipt_path = args.output_dir / f"{invoice_no}.receipt.json"

    plan = {
        "sender_environment": sender_environment,
        "receiver_environment": receiver_environment,
        "invoice_no": invoice_no,
        "invoice_uuid": invoice_uuid,
        "currency": "TRY",
        "line_total": "100.00",
        "vat_rate": "20",
        "vat_total": "20.00",
        "payable_total": "120.00",
        "ubl_path": str(output_path),
        "receipt_path": str(receipt_path),
    }
    if not args.confirm_send:
        print(json.dumps({"ok": True, "sent": False, "plan": plan}, ensure_ascii=True, sort_keys=True))
        return 0

    result = sender_adapter.send_outgoing_invoice_ubl(
        sender,
        invoice_no=invoice_no,
        content=content,
        recipient_label=receiver_label,
        sender_label=sender_label,
    )
    output: dict[str, object] = {
        "ok": True,
        "sent": True,
        "plan": plan,
        "document_oid": result.document_oid,
    }
    receipt_path.write_text(json.dumps(output, ensure_ascii=True, sort_keys=True, indent=2), encoding="utf-8")
    for _ in range(max(args.poll_attempts, 0)):
        status = sender_adapter.get_outgoing_invoice_status(sender, document_oid=result.document_oid)
        output["status"] = {
            "code": status.status_code,
            "processing_state": status.processing_state,
            "text": status.status_text,
            "description": status.description,
            "ettn": status.ettn,
        }
        if status.status_code in {"2", "3"}:
            break
        time_module.sleep(max(args.poll_seconds, 0))
    receipt_path.write_text(json.dumps(output, ensure_ascii=True, sort_keys=True, indent=2), encoding="utf-8")
    print(json.dumps(output, ensure_ascii=True, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
