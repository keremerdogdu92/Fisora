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

    def test_phase0_route_groups_are_split_into_feature_routers(self) -> None:
        from app.api import (
            phase0,
            phase0_routes_auth,
            phase0_routes_operations,
            phase0_routes_review_export,
            phase0_routes_upload_processing,
        )

        direct_route_decorators = Path(phase0.__file__).read_text(encoding="utf-8").count("@router.")
        self.assertLessEqual(direct_route_decorators, 24)

        route_groups = [
            (
                phase0_routes_auth.router,
                {
                "/store/auth/status",
                "/store/auth/login",
                "/store/auth/session",
                "/store/auth/logout",
                },
            ),
            (
                phase0_routes_operations.router,
                {
                "/store/system/readiness",
                "/store/operation-log",
                "/store/operation-health/{client_id}",
                },
            ),
            (
                phase0_routes_upload_processing.router,
                {
                "/store/document-upload",
                "/store/document-upload-multipart",
                "/store/processing/run",
                },
            ),
            (
                phase0_routes_review_export.router,
                {
                "/store/review-decision",
                "/store/export-package/from-workspace",
                "/store/export-package/download/{client_id}/{file_name}",
                },
            ),
        ]

        for route_router, expected_paths in route_groups:
            with self.subTest(router=route_router):
                route_paths = {route.path for route in route_router.routes}
                self.assertTrue(expected_paths.issubset(route_paths))


if __name__ == "__main__":
    unittest.main()
