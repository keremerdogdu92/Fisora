from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
SCRIPTS = BACKEND / "scripts"
for path in (BACKEND, SCRIPTS):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from prepare_reference_corpus_admission import preflight


class ReferenceCorpusAdmissionTests(unittest.TestCase):
    def _fixture(self, root: Path) -> tuple[Path, Path]:
        items = []
        for index in range(50):
            relative = Path(f"firma-{index % 5}") / f"invoice-{index}.xml"
            path = root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(f"PRIVATE-BYTES-{index}".encode())
            items.append(
                {
                    "relative_path": relative.as_posix(),
                    "client_id": f"firma-{index % 5}",
                    "period": "2026-02",
                    "direction": "purchase" if index < 35 else "sales",
                    "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                    "document_type": "einvoice_xml",
                }
            )
        manifest = root / "manifest.json"
        manifest.write_text(
            json.dumps({"corpus_key": "pilot-accountant-reference", "version": 1, "items": items}),
            encoding="utf-8",
        )
        return manifest, root / "preflight.json"

    def test_preflight_validates_exact_counts_hashes_and_writes_only_summary(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "source"
            root.mkdir()
            manifest, output = self._fixture(root)
            summary = preflight(manifest_path=manifest, source_root=root, output_path=output)
            self.assertEqual(summary["item_count"], 50)
            self.assertEqual(summary["purchase_count"], 35)
            self.assertEqual(summary["sales_count"], 15)
            self.assertEqual(summary["unique_sha256_count"], 50)
            self.assertTrue(output.exists())
            self.assertNotIn("PRIVATE-BYTES-0", output.read_text(encoding="utf-8"))

    def test_preflight_rejects_wrong_counts(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            manifest, output = self._fixture(root)
            payload = json.loads(manifest.read_text(encoding="utf-8"))
            payload["items"][0]["direction"] = "sales"
            manifest.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "35_purchase"):
                preflight(manifest_path=manifest, source_root=root, output_path=output)

    def test_preflight_rejects_path_escape(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            manifest, output = self._fixture(root)
            payload = json.loads(manifest.read_text(encoding="utf-8"))
            payload["items"][0]["relative_path"] = "../outside.xml"
            manifest.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "inside_source_root"):
                preflight(manifest_path=manifest, source_root=root, output_path=output)


if __name__ == "__main__":
    unittest.main()
