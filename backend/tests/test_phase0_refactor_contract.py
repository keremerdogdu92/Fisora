from __future__ import annotations

from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))


class Phase0RefactorContractTests(unittest.TestCase):
    def test_public_payloads_are_imported_from_schema_boundary(self) -> None:
        from app.api import phase0, phase0_schemas

        public_payloads = [
            "ClientProfilePayload",
            "ChartAccountPayload",
            "DocumentUploadPayload",
            "ReviewDecisionPayload",
            "WorkspaceExportPackagePayload",
        ]

        for name in public_payloads:
            with self.subTest(name=name):
                self.assertIs(getattr(phase0, name), getattr(phase0_schemas, name))

        upload = phase0_schemas.DocumentUploadPayload(
            client_id="client-1",
            file_name="fatura.pdf",
        )
        self.assertEqual(upload.document_type, "invoice")
        self.assertEqual(upload.intake_category, "")

    def test_phase0_router_keeps_private_pilot_endpoint_contract(self) -> None:
        from app.api import phase0

        route_paths = {route.path for route in phase0.router.routes}

        self.assertTrue(
            {
                "/store/clients",
                "/store/workspace/{client_id}",
                "/store/document-upload-multipart",
                "/store/review-decision",
                "/store/system/readiness",
            }.issubset(route_paths)
        )

    def test_phase0_helper_modules_keep_router_thin_boundaries(self) -> None:
        from app.api import phase0_dependencies, phase0_review_export, phase0_uploads

        self.assertTrue(callable(phase0_dependencies.require_mock_client_access))
        self.assertTrue(callable(phase0_dependencies.record_operation_event))
        self.assertTrue(callable(phase0_uploads.save_uploaded_document_with_job))
        self.assertTrue(callable(phase0_review_export.export_package_payload))
        self.assertEqual(
            phase0_review_export.safe_export_file_name("Demo Mukellef", "zirve_csv"),
            "Demo-Mukellef-zirve_csv.csv",
        )


if __name__ == "__main__":
    unittest.main()
