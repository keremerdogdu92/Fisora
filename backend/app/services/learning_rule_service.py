from __future__ import annotations

from typing import Any, Mapping

from app.persistence.learning_rule_repository import LearningRuleRepository


class LearningRuleService:
    def __init__(self, *, repository: LearningRuleRepository) -> None:
        self.repository = repository

    def create_version(
        self,
        *,
        rule_key: str,
        expected_version: int,
        snapshot: Mapping[str, Any],
        actor: str,
    ) -> dict[str, Any]:
        provenance = snapshot.get("confirmation_provenance")
        if not isinstance(provenance, Mapping) or provenance.get("source") != "accountant_confirmed":
            raise ValueError("learning_rule_confirmation_required")
        if not str(snapshot.get("source_review_decision_id") or "").strip():
            raise ValueError("learning_rule_confirmation_required")
        return self.repository.create_version(
            rule_key=rule_key,
            expected_version=expected_version,
            snapshot=snapshot,
            actor=actor,
        )

    def activate(self, *, rule_key: str, expected_version: int, actor: str) -> dict[str, Any]:
        return self.repository.transition(rule_key=rule_key, expected_version=expected_version, status="active", actor=actor)

    def pause(self, *, rule_key: str, expected_version: int, actor: str) -> dict[str, Any]:
        return self.repository.transition(rule_key=rule_key, expected_version=expected_version, status="paused", actor=actor)

    def archive(self, *, rule_key: str, expected_version: int, actor: str) -> dict[str, Any]:
        return self.repository.transition(rule_key=rule_key, expected_version=expected_version, status="archived", actor=actor)

    def list_active(self, *, client_id: str | None = None, rule_key: str | None = None) -> list[dict[str, Any]]:
        return self.repository.list_active(client_id=client_id, rule_key=rule_key)
