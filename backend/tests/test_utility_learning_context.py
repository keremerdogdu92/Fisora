from __future__ import annotations

from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.domain.learning_intelligence import enrich_learning_event
from app.domain.review_rule_interpretation import review_rule_interpretation_request


class UtilityLearningContextTests(unittest.TestCase):
    def test_vodafone_note_carries_profile_into_rule_preview(self) -> None:
        document = {
            "result": {
                "provider_id": "vodafone_tr",
                "provider_hint": "Vodafone Telekomunikasyon A.S.",
                "provider_match_kind": "vkn",
                "service_profile": "gsm_communication",
                "accounting_direction": "purchase",
                "selected_expense_account": "770.03.001",
                "selected_supplier_account": "320.01.001",
                "counterparty_tax_id": "9250353261",
                "product_line_hint": "Aylik mobil haberlesme bedeli",
            }
        }
        event = enrich_learning_event(
            {
                "action": "approve",
                "accountant_note": "Bu mukellefe kesilen Vodafone faturaları haberleşme gideridir.",
            },
            client_id="firma-1",
            decision={"action": "approve"},
            document=document,
        )

        self.assertEqual(event["utility_context"]["service_profile"], "gsm_communication")
        self.assertEqual(event["utility_context"]["provider_id"], "vodafone_tr")
        request = review_rule_interpretation_request(
            event=event,
            document=document,
            candidate=event["natural_language_rule_candidate"],
        )
        self.assertEqual(request["document"]["utility_context"]["provider_match_kind"], "vkn")

    def test_pdf_vkn_match_keeps_pdf_as_source(self) -> None:
        event = enrich_learning_event(
            {"action": "approve"},
            client_id="firma-1",
            decision={"action": "approve"},
            document={
                "document_type": "invoice",
                "result": {
                    "provider_id": "vodafone_tr",
                    "provider_match_kind": "vkn",
                    "service_profile": "gsm_communication",
                },
            },
        )

        self.assertEqual(event["utility_context"]["source"], "pdf")


if __name__ == "__main__":
    unittest.main()
