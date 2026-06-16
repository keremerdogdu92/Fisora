from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict
from pathlib import Path
from typing import Any

from fastapi import HTTPException

from app.api.phase0_mappers import chart_account_from_payload, chart_account_payloads, client_profile_from_payload
from app.api.phase0_schemas import ChartAccountsStorePayload, ClientOnboardingPackagePayload, ClientProfilePayload
from app.domain.business_relevance import check_client_onboarding
from app.domain.chart_accounts import parse_chart_accounts


OperationRecorder = Callable[..., dict[str, object]]
AccessChecker = Callable[..., dict[str, object]]
UserIdResolver = Callable[[str | None, str | None, str | None], str]


class WorkspaceService:
    def __init__(
        self,
        *,
        store: Any,
        record_operation_event: OperationRecorder,
        require_client_access: AccessChecker,
        request_user_id: UserIdResolver,
        chart_account_parser: Callable[[Path], object] = parse_chart_accounts,
    ) -> None:
        self.store = store
        self.record_operation_event = record_operation_event
        self.require_client_access = require_client_access
        self.request_user_id = request_user_id
        self.chart_account_parser = chart_account_parser

    def onboarding_check(self, payload: ClientProfilePayload) -> dict[str, object]:
        check = check_client_onboarding(client_profile_from_payload(payload))
        return {"is_ready": check.is_ready, "missing_fields": list(check.missing_fields)}

    def store_client(self, payload: ClientProfilePayload) -> dict[str, object]:
        if not payload.client_id.strip():
            raise HTTPException(status_code=400, detail="client_id is required for persistence")
        return self.store.upsert_client(
            client_id=payload.client_id,
            profile=payload.model_dump(),
            onboarding=self.onboarding_check(payload),
        )

    def store_clients(
        self,
        *,
        x_fisora_user_id: str | None,
        x_fisora_session: str | None,
        fisora_session: str | None,
    ) -> dict[str, object]:
        clients = self.store.list_clients()
        user_id = self.request_user_id(x_fisora_user_id, x_fisora_session, fisora_session)
        if user_id:
            clients = [
                client
                for client in clients
                if self.store.verify_portal_access(client_id=client_id_from_record(client), user_id=user_id).get("allowed")
            ]
        return {
            "clients": clients,
            "auth": {
                "mode": "session_or_header" if user_id else "disabled",
                "user_id": user_id,
            },
        }

    def store_chart_accounts(self, payload: ChartAccountsStorePayload) -> dict[str, object]:
        if not payload.client_id.strip():
            raise HTTPException(status_code=400, detail="client_id is required for persistence")
        return self.store.replace_chart_accounts(
            client_id=payload.client_id,
            accounts=chart_account_payloads(payload.accounts),
        )

    def store_chart_accounts_upload(
        self,
        *,
        client_id: str,
        original_name: str,
        file_path: Path,
        x_fisora_user_id: str | None,
        x_fisora_session: str | None,
        fisora_session: str | None,
    ) -> dict[str, object]:
        normalized_client_id = client_id.strip()
        if not normalized_client_id:
            raise HTTPException(status_code=400, detail="client_id is required for chart account upload")
        self.require_client_access(
            client_id=normalized_client_id,
            user_id=self.request_user_id(x_fisora_user_id, x_fisora_session, fisora_session),
            allowed_roles=("accountant", "admin"),
        )
        suffix = Path(original_name).suffix.lower()
        if suffix not in {".csv", ".xlsx", ".xlsm"}:
            raise HTTPException(status_code=400, detail=f"Unsupported chart account format: {suffix or 'unknown'}")
        try:
            parsed_accounts = self.chart_account_parser(file_path)
        except (RuntimeError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        accounts = [asdict(account) for account in parsed_accounts]
        stored = self.store.replace_chart_accounts(client_id=normalized_client_id, accounts=accounts)
        self.record_operation_event(
            store=self.store,
            client_id=normalized_client_id,
            event_type="chart_accounts_uploaded",
            status="ok" if accounts else "warning",
            message="Hesap plani import edildi.",
            metadata={"file_name": original_name, "account_count": len(accounts)},
        )
        return {**stored, "file_name": original_name}

    def store_client_onboarding_package(
        self,
        payload: ClientOnboardingPackagePayload,
        *,
        x_fisora_user_id: str | None = None,
        x_fisora_session: str | None = None,
        fisora_session: str | None = None,
    ) -> dict[str, object]:
        if not payload.client.client_id.strip():
            raise HTTPException(status_code=400, detail="client_id is required for onboarding package")
        client = self.store.upsert_client(
            client_id=payload.client.client_id,
            profile=payload.client.model_dump(),
            onboarding=self.onboarding_check(payload.client),
        )
        chart_accounts = None
        if payload.chart_accounts:
            chart_accounts = self.store.replace_chart_accounts(
                client_id=payload.client.client_id,
                accounts=[asdict(chart_account_from_payload(account)) for account in payload.chart_accounts],
            )
        portal_users = []
        for user in payload.portal_users:
            portal_users.append(
                self.store.upsert_portal_user(
                    user_id=user.user_id,
                    display_name=user.display_name,
                    role=user.role,
                    allowed_client_ids=user.allowed_client_ids or [payload.client.client_id],
                )
            )
        actor_user = self.request_user_id(x_fisora_user_id, x_fisora_session, fisora_session)
        actor_grant = self._grant_actor_access_to_new_client(
            actor_user_id=actor_user,
            client_id=payload.client.client_id,
        )
        if actor_grant:
            portal_users.append(actor_grant)
        return {
            "client": client,
            "chart_accounts": chart_accounts,
            "portal_users": portal_users,
            "workspace": self.store.get_workspace(payload.client.client_id),
        }

    def _grant_actor_access_to_new_client(self, *, actor_user_id: str, client_id: str) -> dict[str, object] | None:
        actor_user_id = actor_user_id.strip()
        if not actor_user_id:
            return None
        access = self.store.verify_portal_access(client_id=client_id, user_id=actor_user_id)
        if access.get("allowed"):
            return None
        if access.get("role") not in {"accountant", "admin"}:
            return None
        existing = self.store.get_portal_user(actor_user_id) if hasattr(self.store, "get_portal_user") else None
        if not existing:
            return None
        allowed_client_ids = list(dict.fromkeys([*(existing.get("allowed_client_ids") or []), client_id]))
        return self.store.upsert_portal_user(
            user_id=actor_user_id,
            display_name=str(existing.get("display_name") or actor_user_id),
            role=str(existing.get("role") or access.get("role") or "accountant"),
            allowed_client_ids=allowed_client_ids,
        )

    def store_workspace(
        self,
        *,
        client_id: str,
        x_fisora_user_id: str | None,
        x_fisora_session: str | None,
        fisora_session: str | None,
    ) -> dict[str, object]:
        if not client_id.strip():
            raise HTTPException(status_code=400, detail="client_id is required")
        self.require_client_access(
            client_id=client_id,
            user_id=self.request_user_id(x_fisora_user_id, x_fisora_session, fisora_session),
        )
        return self.store.get_workspace(client_id)


def client_id_from_record(record: dict[str, object]) -> str:
    profile = record.get("profile") if isinstance(record, dict) else {}
    if isinstance(profile, dict) and profile.get("client_id"):
        return str(profile["client_id"])
    return str(record.get("client_id") or record.get("id") or "")

