from __future__ import annotations

from contextlib import ExitStack, contextmanager
import importlib
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch


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


def _pilot_error(reason: str, status_code: int = 409):
    try:
        module = importlib.import_module("app.services.pilot_reinitialization_service")
    except ModuleNotFoundError:
        error = RuntimeError(reason)
        error.reason = reason  # type: ignore[attr-defined]
        error.status_code = status_code  # type: ignore[attr-defined]
        return error
    return module.PilotReinitializationError(reason, status_code=status_code)


class _FakePortalStore:
    def __init__(self, *, role: str = "accountant") -> None:
        self.role = role

    def get_portal_user(self, user_id: str) -> dict[str, object] | None:
        if not user_id:
            return None
        return {"user_id": user_id, "role": self.role}


class _FakePilotReinitializationService:
    def __init__(
        self,
        *,
        preview_response: dict[str, object] | None = None,
        execute_response: dict[str, object] | None = None,
        preview_error: Exception | None = None,
        execute_error: Exception | None = None,
    ) -> None:
        self.preview_response = preview_response or {
            "preview_fingerprint": "a" * 64,
            "operational_document_count": 3,
            "protected_corpus_count": 1,
            "protected_rule_count": 1,
            "preserved_accountant_admin_count": 2,
        }
        self.execute_response = execute_response or {
            "preview_fingerprint": "a" * 64,
            "remaining_operational_document_count": 0,
            "remaining_protected_corpus_count": 0,
            "remaining_protected_rule_count": 0,
            "deleted_file_count": 3,
            "file_delete_warning_count": 0,
            "file_delete_warning_categories": [],
        }
        self.preview_error = preview_error
        self.execute_error = execute_error
        self.execute_calls: list[dict[str, object]] = []

    def preview(self) -> dict[str, object]:
        if self.preview_error is not None:
            raise self.preview_error
        return dict(self.preview_response)

    def execute(
        self,
        *,
        actor_user_id: str = "",
        confirmation: str,
        preview_fingerprint: str,
        delete_files: bool = True,
    ) -> dict[str, object]:
        self.execute_calls.append(
            {
                "confirmation": confirmation,
                "actor_user_id": actor_user_id,
                "preview_fingerprint": preview_fingerprint,
                "delete_files": delete_files,
            }
        )
        if self.execute_error is not None:
            raise self.execute_error
        return dict(self.execute_response)


@contextmanager
def _pilot_route_patches(store: _FakePortalStore, service: _FakePilotReinitializationService):
    with ExitStack() as stack:
        try:
            module = importlib.import_module("app.api.phase0_routes_maintenance")
        except ModuleNotFoundError:
            yield
            return
        stack.enter_context(patch.object(module, "get_workflow_store", return_value=store))
        stack.enter_context(
            patch.object(module, "get_pilot_reinitialization_service", return_value=service)
        )
        yield


@unittest.skipIf(TestClient is None or phase0 is None or app is None, "fastapi is not installed")
class PilotReinitializationApiTests(unittest.TestCase):
    def test_preview_and_execute_routes_use_safe_contract(self) -> None:
        previous_auth_mode = os.environ.get("FISORA_AUTH_MODE")
        try:
            os.environ["FISORA_AUTH_MODE"] = "mock_header_required"
            with tempfile.TemporaryDirectory() as temp_dir:
                phase0.DEFAULT_STORE_PATH = Path(temp_dir) / "store.json"
                client = TestClient(app)
                service = _FakePilotReinitializationService()
                with _pilot_route_patches(_FakePortalStore(role="accountant"), service):
                    preview = client.get(
                        "/phase0/store/admin/pilot-reinitialization/preview",
                        headers={"X-Fisora-User-Id": "mali-musavir"},
                    )
                    execute = client.post(
                        "/phase0/store/admin/pilot-reinitialization",
                        headers={"X-Fisora-User-Id": "mali-musavir"},
                        json={
                            "confirmation": "YALNIZ_50_FATURA_ILE_BASLAT",
                            "preview_fingerprint": "a" * 64,
                            "delete_files": True,
                        },
                    )
        finally:
            if previous_auth_mode is None:
                os.environ.pop("FISORA_AUTH_MODE", None)
            else:
                os.environ["FISORA_AUTH_MODE"] = previous_auth_mode

        self.assertEqual(preview.status_code, 200)
        self.assertEqual(len(preview.json()["preview_fingerprint"]), 64)
        self.assertIn("operational_document_count", preview.json())
        self.assertIn("protected_corpus_count", preview.json())
        self.assertIn("protected_rule_count", preview.json())
        self.assertIn("preserved_accountant_admin_count", preview.json())
        self.assertEqual(execute.status_code, 200)
        self.assertEqual(execute.json()["remaining_operational_document_count"], 0)
        self.assertEqual(execute.json()["remaining_protected_corpus_count"], 0)

    def test_execute_payload_defaults_delete_files_to_true(self) -> None:
        previous_auth_mode = os.environ.get("FISORA_AUTH_MODE")
        try:
            os.environ["FISORA_AUTH_MODE"] = "mock_header_required"
            with tempfile.TemporaryDirectory() as temp_dir:
                phase0.DEFAULT_STORE_PATH = Path(temp_dir) / "store.json"
                client = TestClient(app)
                service = _FakePilotReinitializationService()
                with _pilot_route_patches(_FakePortalStore(role="accountant"), service):
                    response = client.post(
                        "/phase0/store/admin/pilot-reinitialization",
                        headers={"X-Fisora-User-Id": "mali-musavir"},
                        json={
                            "confirmation": "YALNIZ_50_FATURA_ILE_BASLAT",
                            "preview_fingerprint": "b" * 64,
                        },
                    )
        finally:
            if previous_auth_mode is None:
                os.environ.pop("FISORA_AUTH_MODE", None)
            else:
                os.environ["FISORA_AUTH_MODE"] = previous_auth_mode

        self.assertEqual(response.status_code, 200)
        self.assertEqual(service.execute_calls[-1]["delete_files"], True)

    def test_routes_enforce_auth_and_exact_error_contracts(self) -> None:
        previous_auth_mode = os.environ.get("FISORA_AUTH_MODE")
        try:
            os.environ["FISORA_AUTH_MODE"] = "mock_header_required"
            with tempfile.TemporaryDirectory() as temp_dir:
                phase0.DEFAULT_STORE_PATH = Path(temp_dir) / "store.json"
                client = TestClient(app)
                missing_user = client.get("/phase0/store/admin/pilot-reinitialization/preview")

                with _pilot_route_patches(
                    _FakePortalStore(role="client_user"),
                    _FakePilotReinitializationService(),
                ):
                    forbidden = client.get(
                        "/phase0/store/admin/pilot-reinitialization/preview",
                        headers={"X-Fisora-User-Id": "client-user"},
                    )
                with _pilot_route_patches(
                    _FakePortalStore(role="accountant"),
                    _FakePilotReinitializationService(),
                ):
                    bad_confirmation = client.post(
                        "/phase0/store/admin/pilot-reinitialization",
                        headers={"X-Fisora-User-Id": "mali-musavir"},
                        json={
                            "confirmation": "TEMIZLE",
                            "preview_fingerprint": "a" * 64,
                            "delete_files": True,
                        },
                    )
                with _pilot_route_patches(
                    _FakePortalStore(role="accountant"),
                    _FakePilotReinitializationService(
                        execute_error=_pilot_error("pilot_reinitialization_preview_stale")
                    ),
                ):
                    stale = client.post(
                        "/phase0/store/admin/pilot-reinitialization",
                        headers={"X-Fisora-User-Id": "mali-musavir"},
                        json={
                            "confirmation": "YALNIZ_50_FATURA_ILE_BASLAT",
                            "preview_fingerprint": "a" * 64,
                            "delete_files": True,
                        },
                    )
                with _pilot_route_patches(
                    _FakePortalStore(role="accountant"),
                    _FakePilotReinitializationService(
                        preview_error=_pilot_error("normalized_accounting_required")
                    ),
                ):
                    compatibility = client.get(
                        "/phase0/store/admin/pilot-reinitialization/preview",
                        headers={"X-Fisora-User-Id": "mali-musavir"},
                    )
                with _pilot_route_patches(
                    _FakePortalStore(role="accountant"),
                    _FakePilotReinitializationService(
                        preview_error=_pilot_error("unsafe_storage_root_overlap")
                    ),
                ):
                    overlap = client.get(
                        "/phase0/store/admin/pilot-reinitialization/preview",
                        headers={"X-Fisora-User-Id": "mali-musavir"},
                    )
        finally:
            if previous_auth_mode is None:
                os.environ.pop("FISORA_AUTH_MODE", None)
            else:
                os.environ["FISORA_AUTH_MODE"] = previous_auth_mode

        self.assertEqual(missing_user.status_code, 401)
        self.assertEqual(missing_user.json()["detail"]["reason"], "user_required")
        self.assertEqual(forbidden.status_code, 403)
        self.assertEqual(forbidden.json()["detail"]["reason"], "accountant_required")
        self.assertEqual(bad_confirmation.status_code, 400)
        self.assertEqual(bad_confirmation.json()["detail"]["reason"], "confirmation_required")
        self.assertEqual(stale.status_code, 409)
        self.assertEqual(stale.json()["detail"]["reason"], "pilot_reinitialization_preview_stale")
        self.assertEqual(compatibility.status_code, 409)
        self.assertEqual(compatibility.json()["detail"]["reason"], "normalized_accounting_required")
        self.assertEqual(overlap.status_code, 409)
        self.assertEqual(overlap.json()["detail"]["reason"], "unsafe_storage_root_overlap")


if __name__ == "__main__":
    unittest.main()
