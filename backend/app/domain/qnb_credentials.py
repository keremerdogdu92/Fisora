from __future__ import annotations

import os
from pathlib import Path
from typing import Mapping

from cryptography.fernet import Fernet, InvalidToken


class QnbCredentialCipher:
    def __init__(self, key: str | bytes) -> None:
        normalized = key.encode("ascii") if isinstance(key, str) else key
        try:
            self._fernet = Fernet(normalized)
        except (TypeError, ValueError) as exc:
            raise ValueError("FISORA_QNB_CREDENTIAL_KEY must be a valid Fernet key") from exc

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> "QnbCredentialCipher":
        source = env or os.environ
        configured = str(source.get("FISORA_QNB_CREDENTIAL_KEY") or "").strip()
        if configured:
            return cls(configured)
        if str(source.get("FISORA_ENV") or "").strip().lower() in {"production", "prod"}:
            raise ValueError("FISORA_QNB_CREDENTIAL_KEY is required in production")
        key_path = Path(str(source.get("FISORA_QNB_CREDENTIAL_KEY_FILE") or "exports/.qnb-credential.key"))
        key_path.parent.mkdir(parents=True, exist_ok=True)
        if not key_path.exists():
            key_path.write_bytes(Fernet.generate_key())
        return cls(key_path.read_bytes().strip())

    def encrypt(self, value: str) -> str:
        if not str(value or ""):
            raise ValueError("QNB password is required")
        return self._fernet.encrypt(str(value).encode("utf-8")).decode("ascii")

    def decrypt(self, ciphertext: str) -> str:
        try:
            return self._fernet.decrypt(str(ciphertext or "").encode("ascii")).decode("utf-8")
        except (InvalidToken, ValueError) as exc:
            raise ValueError("QNB credential cannot be decrypted; rotate the credential") from exc


def qnb_platform_erp_code(env: Mapping[str, str] | None = None) -> str:
    return str((env or os.environ).get("FISORA_QNB_ERP_CODE") or "FSR31422").strip()


def validate_qnb_endpoint(base_url: str, environment: str) -> tuple[str, str]:
    value = str(base_url or "").strip().rstrip("/")
    normalized_environment = str(environment or "").strip().lower()
    if normalized_environment not in {"test", "production"}:
        raise ValueError("QNB environment must be test or production")
    if not value.lower().startswith("https://"):
        raise ValueError("QNB endpoint must use HTTPS")
    host = value.split("/", 3)[2].split(":", 1)[0].lower()
    if not host.endswith(".qnbesolutions.com.tr"):
        raise ValueError("QNB endpoint host is not allowed")
    is_test = "test" in host
    if normalized_environment == "test" and not is_test:
        raise ValueError("QNB test credential requires a test endpoint")
    if normalized_environment == "production" and is_test:
        raise ValueError("QNB production credential cannot use a test endpoint")
    return value, normalized_environment
