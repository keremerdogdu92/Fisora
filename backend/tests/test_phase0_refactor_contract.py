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
            phase0_routes_ai,
            phase0_routes_auth,
            phase0_routes_operations,
            phase0_routes_review_export,
            phase0_routes_simulation,
            phase0_routes_upload_processing,
            phase0_routes_workspace,
        )

        direct_route_decorators = Path(phase0.__file__).read_text(encoding="utf-8").count("@router.")
        self.assertLessEqual(direct_route_decorators, 2)

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
            (
                phase0_routes_workspace.router,
                {
                "/onboarding/check",
                "/store/client",
                "/store/clients",
                "/store/chart-accounts/upload",
                "/store/client-onboarding-package",
                "/store/workspace/{client_id}",
                },
            ),
            (
                phase0_routes_ai.router,
                {
                "/classification/product",
                "/statement/ai-suggestions",
                "/store/ai-usage",
                "/classification/batch-benchmark",
                "/classification/model-comparison",
                },
            ),
            (
                phase0_routes_simulation.router,
                {
                "/counterparty/match",
                "/simulation/invoice",
                "/store/simulation",
                "/relevance/assess",
                },
            ),
        ]

        for route_router, expected_paths in route_groups:
            with self.subTest(router=route_router):
                route_paths = {route.path for route in route_router.routes}
                self.assertTrue(expected_paths.issubset(route_paths))

    def test_core_phase0_routes_delegate_workflow_logic_to_services(self) -> None:
        service_modules = [
            "workspace_service",
            "document_service",
            "review_service",
            "export_service",
        ]
        for module_name in service_modules:
            with self.subTest(module=module_name):
                module = __import__(f"app.services.{module_name}", fromlist=[""])
                self.assertIsNotNone(module)

        from app.services.document_service import DocumentService
        from app.services.export_service import ExportService
        from app.services.review_service import ReviewService
        from app.services.workspace_service import WorkspaceService

        self.assertTrue(callable(WorkspaceService.store_client))
        self.assertTrue(callable(DocumentService.store_document_upload))
        self.assertTrue(callable(ReviewService.store_review_decision))
        self.assertTrue(callable(ExportService.store_export_package_from_workspace))

        core_route_files = [
            "phase0_routes_workspace.py",
            "phase0_routes_upload_processing.py",
            "phase0_routes_review_export.py",
        ]
        forbidden_snippets = [
            "get_workflow_store().",
            "store.save_",
            "store.replace_",
            "store.create_processing_job",
            "store.record_operation_event",
            "record_operation_event(",
        ]
        api_dir = BACKEND / "app" / "api"
        for file_name in core_route_files:
            source = (api_dir / file_name).read_text(encoding="utf-8")
            for snippet in forbidden_snippets:
                with self.subTest(file=file_name, snippet=snippet):
                    self.assertNotIn(snippet, source)


if __name__ == "__main__":
    unittest.main()
