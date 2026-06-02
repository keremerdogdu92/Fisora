from __future__ import annotations

import json
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4


def utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def empty_store() -> dict[str, Any]:
    return {
        "clients": {},
        "chart_accounts": {},
        "uploaded_documents": {},
        "documents": {},
        "review_decisions": [],
        "learning_events": [],
        "export_packages": [],
    }


class JsonWorkflowStore:
    """Local persistence adapter for Phase 0 and demos.

    Production should swap this with a PostgreSQL-backed implementation using
    the same behavior surface. The default path lives under exports/, which is
    intentionally gitignored.
    """

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)

    def upsert_client(self, *, client_id: str, profile: dict[str, Any], onboarding: dict[str, Any]) -> dict[str, Any]:
        data = self._read()
        clients = data["clients"]
        existing = clients.get(client_id, {})
        record = {
            **existing,
            "client_id": client_id,
            "profile": profile,
            "onboarding": onboarding,
            "updated_at": utc_now(),
        }
        record.setdefault("created_at", record["updated_at"])
        clients[client_id] = record
        self._write(data)
        return deepcopy(record)

    def replace_chart_accounts(self, *, client_id: str, accounts: list[dict[str, Any]]) -> dict[str, Any]:
        data = self._read()
        record = {
            "client_id": client_id,
            "account_count": len(accounts),
            "accounts": accounts,
            "updated_at": utc_now(),
        }
        data["chart_accounts"][client_id] = record
        self._write(data)
        return deepcopy(record)

    def save_uploaded_document(self, *, client_id: str, document: dict[str, Any]) -> dict[str, Any]:
        data = self._read()
        document_ref = str(document.get("document_id") or document.get("original_file_name") or uuid4())
        document_key = self._document_key(client_id, document_ref)
        record = {
            **document,
            "client_id": client_id,
            "document_ref": document_ref,
            "updated_at": utc_now(),
        }
        record.setdefault("created_at", record["updated_at"])
        data["uploaded_documents"][document_key] = record
        self._write(data)
        return deepcopy(record)

    def save_simulation_result(
        self,
        *,
        client_id: str,
        document_ref: str,
        result: dict[str, Any],
    ) -> dict[str, Any]:
        data = self._read()
        document_key = self._document_key(client_id, document_ref)
        existing = data["documents"].get(document_key, {})
        record = {
            **existing,
            "client_id": client_id,
            "document_ref": document_ref,
            "status": result.get("simulated_status", "review_required"),
            "export_status": result.get("export_status", "review_required"),
            "review_reason_codes": result.get("review_reason_codes", []),
            "result": result,
            "updated_at": utc_now(),
        }
        record.setdefault("id", str(uuid4()))
        record.setdefault("created_at", record["updated_at"])
        data["documents"][document_key] = record
        self._write(data)
        return deepcopy(record)

    def save_review_decision(
        self,
        *,
        client_id: str,
        decision: dict[str, Any],
        learning_event: dict[str, Any],
    ) -> dict[str, Any]:
        data = self._read()
        record = {
            "id": str(uuid4()),
            "client_id": client_id,
            "decision": decision,
            "learning_event": learning_event,
            "created_at": utc_now(),
        }
        data["review_decisions"].append(record)
        data["learning_events"].append(
            {
                "id": str(uuid4()),
                "client_id": client_id,
                **learning_event,
                "created_at": record["created_at"],
            }
        )
        self._write(data)
        return deepcopy(record)

    def save_export_package(self, *, client_id: str, package: dict[str, Any]) -> dict[str, Any]:
        data = self._read()
        record = {
            "id": str(uuid4()),
            "client_id": client_id,
            "package": package,
            "created_at": utc_now(),
        }
        data["export_packages"].append(record)
        self._write(data)
        return deepcopy(record)

    def get_workspace(self, client_id: str) -> dict[str, Any]:
        data = self._read()
        document_prefix = f"{client_id}:"
        return {
            "client": deepcopy(data["clients"].get(client_id)),
            "chart_accounts": deepcopy(data["chart_accounts"].get(client_id)),
            "uploaded_documents": [
                deepcopy(document)
                for key, document in data["uploaded_documents"].items()
                if key.startswith(document_prefix)
            ],
            "documents": [
                deepcopy(document)
                for key, document in data["documents"].items()
                if key.startswith(document_prefix)
            ],
            "review_decisions": [
                deepcopy(decision)
                for decision in data["review_decisions"]
                if decision.get("client_id") == client_id
            ],
            "learning_events": [
                deepcopy(event)
                for event in data["learning_events"]
                if event.get("client_id") == client_id
            ],
            "export_packages": [
                deepcopy(package)
                for package in data["export_packages"]
                if package.get("client_id") == client_id
            ],
        }

    def _read(self) -> dict[str, Any]:
        if not self.path.exists():
            return empty_store()
        with self.path.open("r", encoding="utf-8") as handle:
            loaded = json.load(handle)
        data = empty_store()
        for key, value in loaded.items():
            if key in data:
                data[key] = value
        return data

    def _write(self, data: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = self.path.with_suffix(f"{self.path.suffix}.tmp")
        tmp_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp_path.replace(self.path)

    @staticmethod
    def _document_key(client_id: str, document_ref: str) -> str:
        return f"{client_id}:{document_ref}"
