from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4


class InMemoryOutageEpisodeRepository:
    def __init__(self) -> None:
        self.episodes: dict[str, dict[str, Any]] = {}

    def open_for_task(self, *, tenant_id: str, task_kind: str, now: datetime) -> dict[str, Any]:
        for episode in self.episodes.values():
            if episode["tenant_id"] == tenant_id and episode["task_kind"] == task_kind and episode["status"] == "open":
                return deepcopy(episode)
        episode = {
            "id": str(uuid4()), "tenant_id": tenant_id, "task_kind": task_kind,
            "status": "open", "opened_at": now, "last_failure_at": now,
            "failed_provider_categories": [], "affected_document_count": 0,
        }
        self.episodes[episode["id"]] = deepcopy(episode)
        return episode

    def update(self, episode: dict[str, Any]) -> dict[str, Any]:
        self.episodes[episode["id"]] = deepcopy(episode)
        return deepcopy(episode)


class AiOutageEpisodeService:
    def __init__(self, *, repository: InMemoryOutageEpisodeRepository, tenant_id: str) -> None:
        self.repository = repository
        self.tenant_id = tenant_id

    def record_failure(self, *, task_kind: str, document_id: str, evidence: dict[str, str], now: datetime | None = None) -> dict[str, Any]:
        timestamp = now or datetime.now(UTC)
        episode = self.repository.open_for_task(tenant_id=self.tenant_id, task_kind=task_kind, now=timestamp)
        episode["last_failure_at"] = timestamp
        episode["affected_document_count"] = int(episode.get("affected_document_count") or 0) + 1
        evidence_key = (str(evidence.get("provider") or "unknown"), str(evidence.get("category") or "unavailable"))
        existing = {(str(item.get("provider") or ""), str(item.get("category") or "")) for item in episode.get("failed_provider_categories") or [] if isinstance(item, dict)}
        if evidence_key not in existing:
            episode.setdefault("failed_provider_categories", []).append({"provider": evidence_key[0], "category": evidence_key[1], "attempted_at": str(evidence.get("attempted_at") or timestamp.isoformat())})
        episode["last_document_id"] = document_id
        return self.repository.update(episode)

    def recover(self, *, episode_id: str, now: datetime | None = None) -> dict[str, Any]:
        episode = self.repository.episodes.get(episode_id)
        if episode is None:
            raise KeyError("outage_episode_not_found")
        updated = deepcopy(episode)
        updated["status"] = "recovered"
        updated["recovered_at"] = now or datetime.now(UTC)
        return self.repository.update(updated)
