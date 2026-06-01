from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
from typing import Any

from app.domain.ai_classification import AiClassificationPolicy, StaticFirstClassifier
from app.domain.business_relevance import ClientProfile, check_client_onboarding
from app.domain.chart_accounts import ChartAccount
from app.domain.counterparty_matching import match_counterparty
from app.domain.export_packages import ExportCandidate, build_export_package
from app.domain.journal_entries import JournalEntry, JournalLine, money
from app.domain.matching_simulation import (
    SimulatedInvoiceResult,
    select_accounts,
    simulate_invoice,
)
from app.domain.pdf_invoices import ParsedInvoice
from app.domain.review_learning import ReviewDecision, build_learning_event
from app.persistence.workflow_store import JsonWorkflowStore


def synthetic_client_profile() -> ClientProfile:
    return ClientProfile(
        client_id="pilot-isitme-001",
        title="Pilot Isitme Merkezi",
        tax_id="1234567890",
        activity_description="Isitme cihazi satis ve uygulama merkezi",
        workplace_addresses=("Ataturk Cad. No:1",),
        has_chart_accounts=True,
    )


def synthetic_chart_accounts() -> list[ChartAccount]:
    return [
        ChartAccount("102.01", "102.01", "Test Bankasi", is_detail_account=True),
        ChartAccount("191.01", "191.01", "Indirilecek KDV %20", is_detail_account=True),
        ChartAccount("320.01.015", "320.01.015", "Rexton Medikal", is_detail_account=True, tax_id="5555555555"),
        ChartAccount("320.01.020", "320.01.020", "Market Tedarik", is_detail_account=True, tax_id="6666666666"),
        ChartAccount("770.01", "770.01", "Genel Yonetim Giderleri", is_detail_account=True),
    ]


def synthetic_invoices() -> list[ParsedInvoice]:
    return [
        _invoice(
            file_name="pilot-rexton.pdf",
            provider_hint="Rexton Medikal",
            tax_id="5555555555",
            payable_total="12000.00",
            line_item="Rexton RLi 20",
        ),
        _invoice(
            file_name="pilot-urban-care.pdf",
            provider_hint="Market Tedarik",
            tax_id="6666666666",
            payable_total="450.00",
            line_item="Urban Care sac bakim seti",
        ),
        _invoice(
            file_name="pilot-yeni-tedarikci.pdf",
            provider_hint="Yeni Tedarikci A.S.",
            tax_id="7777777777",
            payable_total="999.90",
            line_item="Kolay Soft e-fatura hizmeti",
        ),
    ]


def run_synthetic_pilot(store_path: Path | str = "exports/synthetic_pilot_store.json") -> dict[str, Any]:
    profile = synthetic_client_profile()
    accounts = synthetic_chart_accounts()
    invoices = synthetic_invoices()
    selection = select_accounts("synthetic_pilot_chart", accounts)
    classifier = StaticFirstClassifier(policy=AiClassificationPolicy(enabled=False))
    store = JsonWorkflowStore(store_path)

    onboarding = check_client_onboarding(profile)
    store.upsert_client(
        client_id=profile.client_id,
        profile=asdict(profile),
        onboarding={"is_ready": onboarding.is_ready, "missing_fields": list(onboarding.missing_fields)},
    )
    store.replace_chart_accounts(client_id=profile.client_id, accounts=[asdict(account) for account in accounts])

    results: list[SimulatedInvoiceResult] = []
    for invoice in invoices:
        counterparty = match_counterparty(accounts, tax_ids=invoice.tax_ids, name_hint=invoice.provider_hint)
        result = simulate_invoice(invoice, selection, profile, counterparty, classifier)
        results.append(result)
        store.save_simulation_result(
            client_id=profile.client_id,
            document_ref=result.file_name,
            result=asdict(result),
        )

    for result in results:
        if result.export_status == "export_ready":
            continue
        decision = _review_decision_for_result(result)
        learning = build_learning_event(decision)
        store.save_review_decision(
            client_id=profile.client_id,
            decision=asdict(decision),
            learning_event=asdict(learning),
        )

    package = build_export_package([_export_candidate_from_result(result) for result in results if result.draft_lines])
    package_record = store.save_export_package(
        client_id=profile.client_id,
        package={
            "export_type": package.export_type,
            "entry_count": len(package.entries),
            "excluded_document_refs": list(package.excluded_document_refs),
            "entries": [_entry_summary(entry) for entry in package.entries],
        },
    )

    return {
        "client_id": profile.client_id,
        "store_path": str(store.path),
        "invoice_count": len(results),
        "export_ready_count": sum(1 for result in results if result.export_status == "export_ready"),
        "review_required_count": sum(1 for result in results if result.export_status != "export_ready"),
        "export_ready_documents": [result.file_name for result in results if result.export_status == "export_ready"],
        "review_required_documents": [
            result.file_name for result in results if result.export_status != "export_ready"
        ],
        "export_package_id": package_record["id"],
        "export_package_entry_count": len(package.entries),
        "excluded_document_refs": list(package.excluded_document_refs),
    }


def _invoice(
    *,
    file_name: str,
    provider_hint: str,
    tax_id: str,
    payable_total: str,
    line_item: str,
) -> ParsedInvoice:
    return ParsedInvoice(
        file_name=file_name,
        provider_hint=provider_hint,
        page_count=1,
        text_extractable=True,
        extracted_char_count=1000,
        scenario="TEMELFATURA",
        invoice_type="ALIS",
        invoice_no=file_name.replace(".pdf", "").upper(),
        ettn="",
        issue_date="01.05.2026",
        tax_ids=(tax_id,),
        vat_rates=("20",),
        goods_services_total="",
        vat_total="",
        special_tax_total="",
        tax_inclusive_total=payable_total,
        payable_total=payable_total,
        risk_flags=(),
        suggested_route="journal_candidate",
        parse_notes=(),
        line_items=(line_item,),
    )


def _review_decision_for_result(result: SimulatedInvoiceResult) -> ReviewDecision:
    if result.business_relevance_status == "is_alani_disi":
        return ReviewDecision(
            document_ref=result.file_name,
            action="business_out_of_scope",
            reviewer="synthetic_pilot",
            category=result.product_category,
            reason=result.business_relevance_reason,
        )
    if any(reason.startswith("counterparty_") for reason in result.review_reason_codes):
        return ReviewDecision(
            document_ref=result.file_name,
            action="wrong_counterparty",
            reviewer="synthetic_pilot",
            category=result.product_category,
            reason="Cari eslesmesi net degil.",
        )
    return ReviewDecision(
        document_ref=result.file_name,
        action="approve_with_changes",
        reviewer="synthetic_pilot",
        category=result.product_category,
        reason="Kontrollu pilot duzeltmesi.",
    )


def _export_candidate_from_result(result: SimulatedInvoiceResult) -> ExportCandidate:
    return ExportCandidate(
        document_ref=result.file_name,
        export_status=result.export_status,
        journal_entry=JournalEntry(
            entry_type=result.draft_entry_type or "purchase",
            entry_date=result.issue_date or "1900-01-01",
            description=f"Pilot fis {result.file_name}",
            lines=tuple(
                JournalLine(
                    line["account_code"],
                    line["description"],
                    debit=money(line["debit"]),
                    credit=money(line["credit"]),
                    document_ref=result.file_name,
                )
                for line in result.draft_lines
            ),
            risk_flags=tuple(result.review_reason_codes),
        ),
        risk_flags=tuple(result.review_reason_codes),
    )


def _entry_summary(entry: JournalEntry) -> dict[str, Any]:
    return {
        "entry_type": entry.entry_type,
        "entry_date": entry.entry_date,
        "description": entry.description,
        "total_debit": f"{entry.total_debit:.2f}",
        "total_credit": f"{entry.total_credit:.2f}",
        "is_balanced": entry.is_balanced,
        "line_count": len(entry.lines),
    }

