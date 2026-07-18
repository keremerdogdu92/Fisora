from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys
from xml.etree import ElementTree


ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.domain.qnb_earsiv import (  # noqa: E402
    QnbSoapEarsivAdapter,
    is_qnb_earsiv_test_endpoint,
    qnb_earsiv_credentials_from_env,
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


def ubl_identity(content: bytes) -> dict[str, str]:
    root = ElementTree.fromstring(content)
    values: dict[str, str] = {}
    for element in root.iter():
        name = str(element.tag).rsplit("}", 1)[-1]
        if name in {"ID", "UUID", "ProfileID"} and name not in values:
            values[name] = (element.text or "").strip()
    if values.get("ProfileID") != "EARSIVFATURA":
        raise ValueError("QNB e-Arsiv sandbox UBL ProfileID must be EARSIVFATURA")
    if not values.get("UUID"):
        raise ValueError("QNB e-Arsiv sandbox UBL must include UUID")
    return values


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run a secret-safe QNB e-Arsiv sandbox connection/send smoke.")
    parser.add_argument("--env-file", type=Path, default=ROOT / ".env.qnb.local")
    parser.add_argument("--ubl-file", type=Path)
    parser.add_argument("--confirm-send", action="store_true", help="Required for the external QNB invoice creation side effect.")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "exports" / "qnb-earsiv-sandbox")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    env = load_env_file(args.env_file)
    credentials = qnb_earsiv_credentials_from_env(env)
    if not is_qnb_earsiv_test_endpoint(credentials.user_service_url) or not is_qnb_earsiv_test_endpoint(
        credentials.service_url
    ):
        print(json.dumps({"ok": False, "error": "sandbox smoke refuses non-test QNB endpoints"}, sort_keys=True))
        return 1

    adapter = QnbSoapEarsivAdapter(timeout=30)
    connection = adapter.test_connection(credentials)
    summary: dict[str, object] = {
        "ok": connection.ok,
        "connection_status": connection.status,
        "message": connection.message,
        "sent": False,
    }
    if not connection.ok:
        print(json.dumps(summary, ensure_ascii=True, sort_keys=True))
        return 2

    try:
        if args.ubl_file is None:
            print(json.dumps(summary, ensure_ascii=True, sort_keys=True))
            return 0
        content = args.ubl_file.read_bytes()
        identity = ubl_identity(content)
        summary["ubl"] = {
            "invoice_no": identity.get("ID", ""),
            "uuid": identity["UUID"],
            "profile": identity["ProfileID"],
            "sha256": hashlib.sha256(content).hexdigest(),
            "size_bytes": len(content),
        }
        if not args.confirm_send:
            print(json.dumps(summary, ensure_ascii=True, sort_keys=True))
            return 0

        result = adapter.create_invoice_ubl(
            credentials,
            transaction_id=identity["UUID"],
            content=content,
            returned_document_format=3,
        )
        summary.update(
            {
                "ok": result.ok,
                "sent": True,
                "result_code": result.result_code,
                "result_text": result.result_text,
                "invoice_uuid": result.invoice_uuid,
                "invoice_no": result.invoice_no,
                "invoice_url_present": bool(result.invoice_url),
                "output_format": result.output_format,
                "output_size_bytes": len(result.output_content),
            }
        )
        args.output_dir.mkdir(parents=True, exist_ok=True)
        receipt_path = args.output_dir / f"{identity['UUID']}.receipt.json"
        if result.output_content:
            suffix = ".pdf" if result.output_format.upper() == "PDF" else ".bin"
            (args.output_dir / f"{identity['UUID']}{suffix}").write_bytes(result.output_content)
        receipt_path.write_text(json.dumps(summary, ensure_ascii=True, sort_keys=True, indent=2), encoding="utf-8")
        print(json.dumps(summary, ensure_ascii=True, sort_keys=True))
        return 0 if result.ok else 3
    finally:
        adapter.close_session(credentials)


if __name__ == "__main__":
    raise SystemExit(main())
