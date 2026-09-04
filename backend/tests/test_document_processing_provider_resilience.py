# File: backend/tests/test_document_processing_provider_resilience.py
# Summary: Verifies three-stage Gemini model isolation and retry classification for transient provider failures.
from __future__ import annotations

from types import SimpleNamespace
import unittest

import httpx

from app.domain.gemini_pdf_runtime import build_gemini_pdf_runtime_from_env
from app.workflows.document_processing import (
    _three_stage_gemini_runtime,
    is_transient_provider_error,
)


class DocumentProcessingProviderResilienceTests(unittest.TestCase):
    def test_three_stage_runtime_uses_general_gemini_model_without_mutating_v2_model(self) -> None:
        env = {
            "GEMINI_API_KEY": "test-key",
            "FISORA_GEMINI_MODEL": "gemini-2.5-flash-lite",
            "FISORA_GEMINI_PDF_V2_MODEL": "gemini-3.5-flash-lite",
        }

        three_stage = _three_stage_gemini_runtime(env)
        dedicated_v2 = build_gemini_pdf_runtime_from_env(env)

        self.assertTrue(three_stage.available)
        self.assertTrue(dedicated_v2.available)
        self.assertEqual(three_stage.provider.model, "gemini-2.5-flash-lite")
        self.assertEqual(dedicated_v2.provider.model, "gemini-3.5-flash-lite")

    def test_http_503_and_timeout_are_retryable_but_http_400_is_not(self) -> None:
        request = httpx.Request("POST", "https://provider.test/generate")
        unavailable = httpx.Response(503, request=request)
        bad_request = httpx.Response(400, request=request)

        unavailable_error = httpx.HTTPStatusError(
            "unavailable", request=request, response=unavailable
        )
        bad_request_error = httpx.HTTPStatusError(
            "bad request", request=request, response=bad_request
        )
        timeout_error = httpx.ReadTimeout("read timed out", request=request)

        self.assertTrue(is_transient_provider_error(unavailable_error))
        self.assertTrue(is_transient_provider_error(timeout_error))
        self.assertFalse(is_transient_provider_error(bad_request_error))

    def test_attempt_receipt_503_is_retryable(self) -> None:
        error = RuntimeError("provider attempt failed")
        error.attempt = SimpleNamespace(http_status=503)  # type: ignore[attr-defined]

        self.assertTrue(is_transient_provider_error(error))


if __name__ == "__main__":
    unittest.main()
