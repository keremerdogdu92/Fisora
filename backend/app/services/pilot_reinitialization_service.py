from __future__ import annotations

from pathlib import Path
from typing import Any


PILOT_REINITIALIZATION_CONFIRMATION = "YALNIZ_50_FATURA_ILE_BASLAT"


class PilotReinitializationError(ValueError):
    def __init__(self, reason: str, *, status_code: int = 409) -> None:
        super().__init__(reason)
        self.reason = reason
        self.status_code = status_code


class PilotReinitializationService:
    def __init__(
        self,
        *,
        store: Any,
        document_storage_path: Path | str,
        export_path: Path | str,
        protected_storage_path: Path | str,
    ) -> None:
        self.store = store
        self.document_storage_path = Path(document_storage_path)
        self.export_path = Path(export_path)
        self.protected_storage_path = Path(protected_storage_path)

    def _require_normalized(self) -> None:
        if not bool(getattr(self.store, "normalized_accounting_enabled", False)):
            raise PilotReinitializationError("normalized_accounting_required")

    def preview(self) -> dict[str, object]:
        self._require_normalized()
        try:
            return dict(self.store.preview_pilot_reinitialization())
        except PilotReinitializationError:
            raise
        except ValueError as exc:
            raise PilotReinitializationError(str(exc)) from exc

    def execute(
        self,
        *,
        actor_user_id: str,
        confirmation: str,
        preview_fingerprint: str,
        delete_files: bool = True,
    ) -> dict[str, object]:
        self._require_normalized()
        if confirmation != PILOT_REINITIALIZATION_CONFIRMATION:
            raise PilotReinitializationError("confirmation_required", status_code=400)
        try:
            return dict(
                self.store.reinitialize_pilot_data(
                    actor_user_id=actor_user_id,
                    preview_fingerprint=preview_fingerprint,
                    document_storage_path=self.document_storage_path,
                    export_path=self.export_path,
                    protected_storage_path=self.protected_storage_path,
                    delete_files=delete_files,
                )
            )
        except PilotReinitializationError:
            raise
        except ValueError as exc:
            raise PilotReinitializationError(str(exc)) from exc
