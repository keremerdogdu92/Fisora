from pathlib import Path
import os
import sys
import tempfile
from unittest.mock import patch

import pytest

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from fastapi.testclient import TestClient
from app.api import phase0
from app.domain.session_auth import AuthActionToken, create_password_hash, hash_session_token
from app.main import app
@pytest.fixture
def isolated_store():
    previous_store_path = phase0.DEFAULT_STORE_PATH
    previous_base_url = os.environ.get("FISORA_PORTAL_BASE_URL")
    previous_rate_limit = os.environ.get("FISORA_RATE_LIMIT_ENABLED")
    os.environ["FISORA_PORTAL_BASE_URL"] = "https://portal.test"
    os.environ["FISORA_RATE_LIMIT_ENABLED"] = "false"
    with tempfile.TemporaryDirectory() as temp_dir:
        phase0.DEFAULT_STORE_PATH = Path(temp_dir) / "store.json"
        yield phase0.get_workflow_store()
    phase0.DEFAULT_STORE_PATH = previous_store_path
    if previous_base_url is None:
        os.environ.pop("FISORA_PORTAL_BASE_URL", None)
    else:
        os.environ["FISORA_PORTAL_BASE_URL"] = previous_base_url
    if previous_rate_limit is None:
        os.environ.pop("FISORA_RATE_LIMIT_ENABLED", None)
    else:
        os.environ["FISORA_RATE_LIMIT_ENABLED"] = previous_rate_limit
def create_account(store, email="known@example.com"):
    store.upsert_portal_user(
        user_id=email,
        display_name="Known User",
        role="admin",
        allowed_client_ids=["*"],
        email=email,
    )
    store.set_auth_password(user_id=email, password_hash=create_password_hash("OldPassword123"))


def token(raw):
    return AuthActionToken(raw_token=raw, token_hash=hash_session_token(raw))
def test_reset_request_does_not_enumerate_accounts(isolated_store):
    create_account(isolated_store)
    client = TestClient(app)
    with patch("app.api.phase0_routes_auth.send_auth_email") as sender:
        sender.return_value = {"status": "sent", "provider": "test"}
        known = client.post("/phase0/store/auth/password-reset/request", json={"email": "known@example.com"})
        unknown = client.post("/phase0/store/auth/password-reset/request", json={"email": "unknown@example.com"})

    assert known.status_code == 200
    assert unknown.status_code == 200
    assert known.json() == unknown.json()
    assert known.json()["accepted"] is True
    assert "reset_token" not in known.json()
    assert sender.call_count == 1

def test_passwordless_existing_user_can_set_first_password_via_reset(isolated_store):
    email = "first-password@example.com"
    isolated_store.upsert_portal_user(
        user_id=email, display_name="First Password User", role="admin", allowed_client_ids=["*"], email=email
    )
    client = TestClient(app)
    with patch("app.api.phase0_routes_auth.create_auth_action_token", return_value=token("first-password-reset")), patch(
        "app.api.phase0_routes_auth.send_auth_email", return_value={"status": "sent", "provider": "test"}
    ) as sender:
        requested = client.post("/phase0/store/auth/password-reset/request", json={"email": email})
    assert requested.status_code == 200
    assert sender.call_count == 1
    confirmed = client.post(
        "/phase0/store/auth/password-reset/confirm",
        json={"reset_token": "first-password-reset", "password": "FirstPassword123"},
    )
    assert confirmed.status_code == 200
    assert client.post("/phase0/store/auth/login", json={"user_id": email, "password": "FirstPassword123"}).status_code == 200


def test_new_reset_supersedes_old_and_confirm_revokes_sessions(isolated_store):
    email = "known@example.com"
    create_account(isolated_store, email)
    client = TestClient(app)
    login = client.post("/phase0/store/auth/login", json={"user_id": email, "password": "OldPassword123"})
    assert login.status_code == 200
    old_session = login.json()["session_token"]

    with patch("app.api.phase0_routes_auth.create_auth_action_token", side_effect=[token("reset-one"), token("reset-two")]), patch(
        "app.api.phase0_routes_auth.send_auth_email", return_value={"status": "sent", "provider": "test"}
    ):
        assert client.post("/phase0/store/auth/password-reset/request", json={"email": email}).status_code == 200
        assert client.post("/phase0/store/auth/password-reset/request", json={"email": email}).status_code == 200

    stale = client.post("/phase0/store/auth/password-reset/confirm", json={"reset_token": "reset-one", "password": "NewPassword123"})
    assert stale.status_code == 400
    confirmed = client.post("/phase0/store/auth/password-reset/confirm", json={"reset_token": "reset-two", "password": "NewPassword123"})
    assert confirmed.status_code == 200
    assert confirmed.json()["revoked_sessions"] >= 1

    old_session_check = client.get("/phase0/store/auth/session", headers={"X-Fisora-Session": old_session})
    assert old_session_check.status_code == 401
    assert old_session_check.json()["detail"]["reason"] == "session_revoked"
    assert client.post("/phase0/store/auth/login", json={"user_id": email, "password": "OldPassword123"}).status_code == 401
    assert client.post("/phase0/store/auth/login", json={"user_id": email, "password": "NewPassword123"}).status_code == 200
    reused = client.post("/phase0/store/auth/password-reset/confirm", json={"reset_token": "reset-two", "password": "AnotherPassword123"})
    assert reused.status_code == 400
