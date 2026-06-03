from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
from typing import Protocol


@dataclass(frozen=True)
class StoredObject:
    backend: str
    path: str
    size_bytes: int


class DocumentStorageAdapter(Protocol):
    backend: str

    def write_bytes(self, *, client_key: str, document_id: str, file_name: str, content: bytes) -> StoredObject:
        ...

    def delete(self, storage_path: str) -> bool:
        ...

    def readiness(self) -> dict[str, object]:
        ...


@dataclass(frozen=True)
class LocalDocumentStorage:
    base_dir: Path
    backend: str = "local"

    def write_bytes(self, *, client_key: str, document_id: str, file_name: str, content: bytes) -> StoredObject:
        storage_dir = self.base_dir / client_key / document_id
        storage_dir.mkdir(parents=True, exist_ok=True)
        storage_path = storage_dir / file_name
        storage_path.write_bytes(content)
        return StoredObject(backend=self.backend, path=str(storage_path), size_bytes=len(content))

    def delete(self, storage_path: str) -> bool:
        path = Path(storage_path)
        if not path.exists() or not path.is_file():
            return False
        path.unlink()
        return True

    def readiness(self) -> dict[str, object]:
        self.base_dir.mkdir(parents=True, exist_ok=True)
        probe = self.base_dir / ".fisora-write-test"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        return {
            "backend": self.backend,
            "base_dir": str(self.base_dir),
            "writable": True,
        }


def build_document_storage_adapter(*, base_dir: Path | str, backend: str | None = None) -> DocumentStorageAdapter:
    selected = (backend or os.environ.get("FISORA_DOCUMENT_STORAGE_BACKEND") or "local").strip().lower()
    if selected == "local":
        return LocalDocumentStorage(Path(base_dir))
    if selected in {"s3", "s3_compatible", "object_storage"}:
        raise ValueError("S3-compatible document storage is planned but not implemented in the MVP adapter")
    raise ValueError(f"unsupported document storage backend: {selected}")


def storage_readiness(*, base_dir: Path | str, backend: str | None = None) -> dict[str, object]:
    try:
        return {"ok": True, **build_document_storage_adapter(base_dir=base_dir, backend=backend).readiness()}
    except Exception as exc:
        return {
            "ok": False,
            "backend": (backend or os.environ.get("FISORA_DOCUMENT_STORAGE_BACKEND") or "local").strip().lower(),
            "base_dir": str(base_dir),
            "reason": str(exc),
        }
