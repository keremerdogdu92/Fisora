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
from run_reference_corpus_pilot import _corpus_id, _direction_mismatch, _enroll_completed
from app.services.protected_corpus_service import ProtectedCorpusError


class ReferenceCorpusAdmissionTests(unittest.TestCase):
    def test_pilot_uses_protected_corpus_repository_identifier(self) -> None:
        self.assertEqual(
            _corpus_id({"corpus_id": "corpus-123", "corpus_key": "pilot"}),
            "corpus-123",
        )

    def test_pilot_reports_enrollment_evidence_error_without_aborting(self) -> None:
        class RejectingService:
            def enroll_document(self, **kwargs: object) -> None:
                raise ProtectedCorpusError("direction_evidence_mismatch")

        error = _enroll_completed(
            service=RejectingService(),
            corpus_id="corpus-123",
            client_id="firma-7",
            document_ref="document-123",
            expected_direction="sales",
        )

        self.assertEqual(error, "direction_evidence_mismatch")

    def test_pilot_treats_existing_corpus_source_as_resumed_success(self) -> None:
        class ExistingService:
            def enroll_document(self, **kwargs: object) -> None:
                raise ProtectedCorpusError("duplicate_corpus_source")

        error = _enroll_completed(
            service=ExistingService(),
            corpus_id="corpus-123",
            client_id="firma-7",
            document_ref="document-123",
            expected_direction="purchase",
        )

        self.assertEqual(error, "")

    def test_pilot_does_not_count_failed_job_as_direction_mismatch(self) -> None:
        self.assertFalse(
            _direction_mismatch(
                {
                    "job_status": "failed",
                    "expected_direction": "purchase",
                    "accounting_direction": "",
                }
            )
        )
        self.assertTrue(
            _direction_mismatch(
                {
                    "job_status": "completed",
                    "expected_direction": "purchase",
                    "accounting_direction": "sales",
                }
            )
        )

    def _fixture(self, root: Path) -> tuple[Path, Path]:
        items = []
        for index in range(50):
            client_id = f"firma-{index % 5}"
            chart = root / client_id / "chart_accounts" / "chart.xlsx"
            chart.parent.mkdir(parents=True, exist_ok=True)
            if not chart.exists():
                chart.write_bytes(b"TEST-CHART")
            relative = Path(client_id) / f"invoice-{index}.xml"
            path = root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            direction = "purchase" if index < 35 else "sales"
            client_tax_id = str(1000000000 + (index % 5))
            supplier_tax_id = client_tax_id if direction == "sales" else str(2000000000 + index)
            customer_tax_id = client_tax_id if direction == "purchase" else str(3000000000 + index)
            path.write_text(
                f"""
                <Invoice>
                  <AccountingSupplierParty><Party><PartyTaxScheme><CompanyID>{supplier_tax_id}</CompanyID></PartyTaxScheme></Party></AccountingSupplierParty>
                  <AccountingCustomerParty><Party><PartyTaxScheme><CompanyID>{customer_tax_id}</CompanyID></PartyTaxScheme></Party></AccountingCustomerParty>
                </Invoice>
                """,
                encoding="utf-8",
            )
            items.append(
                {
                    "relative_path": relative.as_posix(),
                    "client_id": client_id,
                    "client_tax_id": client_tax_id,
                    "period": "2026-02",
                    "direction": direction,
                    "intake_category": f"{direction}_invoice",
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
            self.assertEqual(summary["missing_direction_count"], 0)
            self.assertEqual(summary["duplicate_source_hash_count"], 0)
            self.assertEqual(summary["xml_party_direction_conflict_count"], 0)
            self.assertTrue(output.exists())
            self.assertNotIn("1000000000", output.read_text(encoding="utf-8"))

    def test_preflight_rejects_wrong_counts(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            manifest, output = self._fixture(root)
            payload = json.loads(manifest.read_text(encoding="utf-8"))
            first = payload["items"][0]
            first["direction"] = "sales"
            first["intake_category"] = "sales_invoice"
            path = root / first["relative_path"]
            path.write_text(
                f"""
                <Invoice>
                  <AccountingSupplierParty><Party><PartyTaxScheme><CompanyID>{first["client_tax_id"]}</CompanyID></PartyTaxScheme></Party></AccountingSupplierParty>
                  <AccountingCustomerParty><Party><PartyTaxScheme><CompanyID>9999999999</CompanyID></PartyTaxScheme></Party></AccountingCustomerParty>
                </Invoice>
                """,
                encoding="utf-8",
            )
            first["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
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

    def test_preflight_rejects_missing_intake_category(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            manifest, output = self._fixture(root)
            payload = json.loads(manifest.read_text(encoding="utf-8"))
            payload["items"][0].pop("intake_category")
            manifest.write_text(json.dumps(payload), encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "intake_category"):
                preflight(manifest_path=manifest, source_root=root, output_path=output)

    def test_preflight_rejects_xml_party_direction_conflict(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            manifest, output = self._fixture(root)
            payload = json.loads(manifest.read_text(encoding="utf-8"))
            first = payload["items"][0]
            path = root / first["relative_path"]
            path.write_text(
                """
                <Invoice>
                  <AccountingSupplierParty><Party><PartyTaxScheme><CompanyID>1000000000</CompanyID></PartyTaxScheme></Party></AccountingSupplierParty>
                  <AccountingCustomerParty><Party><PartyTaxScheme><CompanyID>9999999999</CompanyID></PartyTaxScheme></Party></AccountingCustomerParty>
                </Invoice>
                """,
                encoding="utf-8",
            )
            first["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
            manifest.write_text(json.dumps(payload), encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "xml_party_direction_conflict"):
                preflight(manifest_path=manifest, source_root=root, output_path=output)

    def test_preflight_can_write_validated_corrected_private_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            manifest, output = self._fixture(root)
            payload = json.loads(manifest.read_text(encoding="utf-8"))
            for item in payload["items"]:
                item.pop("intake_category")
                item.pop("client_tax_id")
            manifest.write_text(json.dumps(payload), encoding="utf-8")
            corrected = root / "manifest.corrected.json"
            intake_dir = root / "intake-manifests"

            summary = preflight(
                manifest_path=manifest,
                source_root=root,
                output_path=output,
                corrected_manifest_path=corrected,
                intake_manifest_dir=intake_dir,
            )

            corrected_payload = json.loads(corrected.read_text(encoding="utf-8"))
            self.assertEqual(summary["xml_party_direction_conflict_count"], 0)
            self.assertEqual(
                {item["intake_category"] for item in corrected_payload["items"]},
                {"purchase_invoice", "sales_invoice"},
            )
            self.assertTrue(all(item.get("client_tax_id") for item in corrected_payload["items"]))
            intake_manifests = sorted(intake_dir.glob("*.json"))
            self.assertEqual(len(intake_manifests), 5)
            first_intake = json.loads(intake_manifests[0].read_text(encoding="utf-8"))
            self.assertEqual(first_intake["files"][0]["document_kind"], "chart_accounts")
            self.assertTrue(
                all(
                    row.get("intake_category") in {"purchase_invoice", "sales_invoice"}
                    for row in first_intake["files"][1:]
                )
            )


if __name__ == "__main__":
    unittest.main()
