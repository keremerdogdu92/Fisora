from datetime import UTC, datetime
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.services.outage_service import AiOutageEpisodeService, InMemoryOutageEpisodeRepository


class AiOutageEpisodeTests(unittest.TestCase):
    def test_provider_failures_join_one_task_episode_and_deduplicate_categories(self) -> None:
        now = datetime(2026, 7, 27, 10, 0, tzinfo=UTC)
        service = AiOutageEpisodeService(repository=InMemoryOutageEpisodeRepository(), tenant_id="tenant-1")
        first = service.record_failure(task_kind="invoice_classification", document_id="doc-1", evidence={"provider": "groq", "category": "timeout", "attempted_at": now.isoformat()}, now=now)
        second = service.record_failure(task_kind="invoice_classification", document_id="doc-2", evidence={"provider": "groq", "category": "timeout", "attempted_at": now.isoformat()}, now=now)
        self.assertEqual(first["id"], second["id"])
        self.assertEqual(second["affected_document_count"], 2)
        self.assertEqual(len(second["failed_provider_categories"]), 1)

    def test_recovery_closes_episode(self) -> None:
        now = datetime(2026, 7, 27, 10, 0, tzinfo=UTC)
        service = AiOutageEpisodeService(repository=InMemoryOutageEpisodeRepository(), tenant_id="tenant-1")
        opened = service.record_failure(task_kind="invoice_classification", document_id="doc-1", evidence={"provider": "groq", "category": "unavailable"}, now=now)
        recovered = service.recover(episode_id=opened["id"], now=now)
        self.assertEqual(recovered["status"], "recovered")
        self.assertEqual(recovered["recovered_at"], now)
