from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass, field, replace
import hashlib
import json
from typing import Any, Mapping, Protocol, Sequence

from app.domain.accounting_candidate_builder import (
    AccountingCandidate,
    AccountingCandidateCatalog,
    build_accounting_candidates,
)
from app.domain.accounting_decision_capacity import plan_accounting_decision_chunks
from app.domain.accounting_projection import build_accounting_projection
from app.domain.accounting_proposal import (
    AccountingDecisionV2,
    AccountingProposalRequestContextV2,
    AccountingProposalRequestV2,
    AccountingProposalV2,
    attach_semantic_conflicts,
    parse_accounting_proposal_result,
    required_decision_refs_for_projection,
)
from app.domain.accounting_quality import AccountingQualityResult, evaluate_accounting_quality
from app.domain.canonical_invoices import (
    CanonicalExtractionRequest,
    CanonicalInvoice,
    canonical_evidence_categories,
    canonical_invoice_from_ai_payload,
    derive_line_to_vat_linkage,
)
from app.domain.document_ai_artifacts import ArtifactKind, ArtifactWrite, DocumentAiArtifact
from app.domain.journal_draft_builder import JournalDraftV2, build_journal_draft


PIPELINE_VERSION = "gemini-two-stage-v2"
EXTRACTION_PROMPT_VERSION = "invoice-facts-v2"
EXTRACTION_SCHEMA_VERSION = "canonical-invoice-v2"


class _ExtractionProvider(Protocol):
    def extract_invoice_canonical(self, request: CanonicalExtractionRequest) -> Mapping[str, object]: ...


class _AccountingProvider(Protocol):
    def classify_product(self, request: AccountingProposalRequestV2) -> Mapping[str, object]: ...


class _ArtifactRepository(Protocol):
    def append(
        self,
        write: ArtifactWrite,
        *,
        content: bytes | None = None,
        request_body: bytes | None = None,
        response_body: bytes | None = None,
    ) -> DocumentAiArtifact: ...

    def list_for_document(
        self,
        *,
        tenant_id: str,
        taxpayer_id: str,
        document_id: str,
        kind: ArtifactKind | None = None,
    ) -> list[DocumentAiArtifact]: ...


@dataclass(frozen=True)
class GeminiInvoiceExtractionIdentity:
    source_file_id: str
    source_file_sha256: str
    provider: str
    model_alias: str
    resolved_model: str
    prompt_version: str
    schema_version: str
    pipeline_version: str

    def to_metadata(self) -> dict[str, str]:
        return asdict(self)


@dataclass(frozen=True)
class GeminiInvoiceAccountingIdentity:
    chart_revision: str
    canonical_revision: str
    candidate_builder_version: str
    client_context_revision: str
    pipeline_version: str

    def to_metadata(self) -> dict[str, str]:
        return {
            "chart_revision": self.chart_revision,
            "canonical_revision": self.canonical_revision,
            "candidate_builder_version": self.candidate_builder_version,
            "client_context_revision": self.client_context_revision,
            "pipeline_version": self.pipeline_version,
        }


@dataclass(frozen=True)
class GeminiInvoicePipelineRequest:
    tenant_id: str
    taxpayer_id: str
    document_id: str
    source_file_id: str
    source_file_sha256: str
    source_bytes: bytes = field(repr=False)
    workspace: Mapping[str, object] = field(default_factory=dict)
    tenant_tax_id: str = ""
    chart_revision: str = ""
    client_context: Mapping[str, object] = field(default_factory=dict)
    client_context_revision: str = ""
    candidate_builder_version: str = "accounting-candidate-builder-v2"
    prior_valid_result: GeminiInvoicePipelineResult | None = field(
        default=None,
        repr=False,
        compare=False,
    )
    pipeline_version: str = PIPELINE_VERSION
    extraction_prompt_version: str = EXTRACTION_PROMPT_VERSION
    extraction_schema_version: str = EXTRACTION_SCHEMA_VERSION
    max_parallel_accounting_chunks: int = 1
    candidate_discovery_mode: str = "adaptive"
    candidate_experiment_group: str = "control"
    candidate_experiment_bucket: int = 0
    candidate_experiment_percent: int = 0
    max_accounting_request_bytes: int = 3_000_000
    accounting_identity: GeminiInvoiceAccountingIdentity = field(init=False)

    def __post_init__(self) -> None:
        for name in (
            "tenant_id",
            "taxpayer_id",
            "document_id",
            "source_file_id",
            "source_file_sha256",
        ):
            if not str(getattr(self, name) or "").strip():
                raise ValueError(f"Gemini V2 pipeline {name} is required")
        if not isinstance(self.source_bytes, bytes) or not self.source_bytes:
            raise ValueError("Gemini V2 pipeline requires native PDF bytes")
        if not self.source_bytes.startswith(b"%PDF"):
            raise ValueError("Gemini V2 pipeline source must be a native PDF")
        actual_sha = hashlib.sha256(self.source_bytes).hexdigest()
        if actual_sha != self.source_file_sha256:
            raise ValueError("Gemini V2 pipeline source SHA-256 mismatch")
        if not str(self.candidate_builder_version or "").strip():
            raise ValueError("Gemini V2 candidate_builder_version is required")
        if not str(self.chart_revision or "").strip():
            raise ValueError("Gemini V2 chart_revision is required")
        if not str(self.pipeline_version or "").strip():
            raise ValueError("Gemini V2 pipeline_version is required")
        if not str(self.extraction_prompt_version or "").strip():
            raise ValueError("Gemini V2 extraction_prompt_version is required")
        if not str(self.extraction_schema_version or "").strip():
            raise ValueError("Gemini V2 extraction_schema_version is required")
        if not 1 <= int(self.max_parallel_accounting_chunks) <= 8:
            raise ValueError("Gemini V2 max_parallel_accounting_chunks must be between 1 and 8")
        discovery_mode = str(self.candidate_discovery_mode or "").strip().lower()
        if discovery_mode not in {"adaptive", "exhaustive"}:
            raise ValueError("Gemini V2 candidate_discovery_mode must be adaptive or exhaustive")
        if self.candidate_experiment_group not in {"control", "experiment"}:
            raise ValueError("Gemini V2 candidate_experiment_group must be control or experiment")
        if not 0 <= int(self.candidate_experiment_bucket) < 100:
            raise ValueError("Gemini V2 candidate_experiment_bucket must be between 0 and 99")
        if not 0 <= int(self.candidate_experiment_percent) <= 100:
            raise ValueError("Gemini V2 candidate_experiment_percent must be between 0 and 100")
        if int(self.max_accounting_request_bytes) <= 0:
            raise ValueError("Gemini V2 max_accounting_request_bytes must be positive")
        object.__setattr__(self, "candidate_discovery_mode", discovery_mode)
        context_revision = str(self.client_context_revision or "").strip() or hashlib.sha256(
            _json_bytes(dict(self.client_context))
        ).hexdigest()
        object.__setattr__(self, "client_context_revision", context_revision)
        object.__setattr__(
            self,
            "accounting_identity",
            GeminiInvoiceAccountingIdentity(
                chart_revision=str(self.chart_revision or "").strip(),
                canonical_revision="",
                candidate_builder_version=str(self.candidate_builder_version).strip(),
                client_context_revision=context_revision,
                pipeline_version=str(self.pipeline_version or "").strip(),
            ),
        )


@dataclass(frozen=True)
class GeminiInvoiceCandidateRound:
    round_index: int
    candidate_ids: tuple[str, ...]
    receipt_artifact_id: str
    status: str
    chunk_index: int = 0
    universe_count: int = 0
    sent_count: int = 0
    coverage_ratio: float = 0.0
    candidate_universe_truncated: bool = False
    serialized_request_bytes: int = 0
    candidate_discovery_mode: str = "adaptive"
    candidate_experiment_group: str = "control"
    candidate_experiment_bucket: int = 0


@dataclass(frozen=True)
class GeminiInvoicePipelineResult:
    status: str
    tenant_id: str
    taxpayer_id: str
    document_id: str
    source_file_id: str
    source_file_sha256: str
    extraction_identity: GeminiInvoiceExtractionIdentity
    accounting_identity: GeminiInvoiceAccountingIdentity
    canonical_invoice: CanonicalInvoice | None
    projection: Mapping[str, object] | None
    proposal: AccountingProposalV2 | None
    draft: JournalDraftV2 | None
    quality: AccountingQualityResult | None
    artifacts: tuple[DocumentAiArtifact, ...]
    warnings: tuple[str, ...]
    candidate_rounds: tuple[GeminiInvoiceCandidateRound, ...] = ()
    proposal_artifact_id: str = ""
    retained_prior_result: bool = False
    processing_status: str = "partial"
    extraction_validation_status: str = "unavailable"
    reconciliation_status: str = "unavailable"
    accounting_decision_status: str = "unavailable"
    draft_balance_status: str = "unavailable"
    review_status: str = "review_required"
    export_status: str = "review_required"


def run_gemini_invoice_pipeline_v2(
    request: GeminiInvoicePipelineRequest,
    *,
    extraction_provider: _ExtractionProvider,
    accounting_provider: _AccountingProvider,
    artifact_repository: _ArtifactRepository,
) -> GeminiInvoicePipelineResult:
    """Run the isolated native-PDF fact and accounting stages."""

    warnings: list[str] = []
    artifacts: list[DocumentAiArtifact] = []
    prior = _valid_prior(request)
    extraction_request = CanonicalExtractionRequest(
        document_text="",
        document_bytes=request.source_bytes,
        document_mime_type="application/pdf",
        deterministic_payload={},
        client_identity={
            "tenant_id": request.tenant_id,
            "taxpayer_id": request.taxpayer_id,
        },
        mode="discovery",
    )
    try:
        raw_extraction = extraction_provider.extract_invoice_canonical(extraction_request)
        extraction_attempt = _attempt(raw_extraction)
        extraction_identity = _extraction_identity(request, extraction_attempt)
        prior = _prior_for_extraction_identity(prior, extraction_identity)
        extraction_receipt = _append_receipt(
            artifact_repository,
            request,
            extraction_attempt,
            stage="document_extraction",
            retry_of_artifact_id=_latest_extraction_receipt_id(
                artifact_repository,
                request,
                extraction_identity=extraction_identity,
            ),
            extraction_identity=extraction_identity,
        )
        artifacts.append(extraction_receipt)
    except Exception as exc:
        extraction_attempt = _attempt(exc)
        extraction_identity = _extraction_identity(request, extraction_attempt)
        prior = _prior_for_extraction_identity(prior, extraction_identity)
        failed_receipt = _append_receipt(
            artifact_repository,
            request,
            extraction_attempt,
            stage="document_extraction",
            retry_of_artifact_id=_latest_extraction_receipt_id(
                artifact_repository,
                request,
                extraction_identity=extraction_identity,
            ),
            extraction_identity=extraction_identity,
        )
        artifacts.append(failed_receipt)
        warnings.append("document_extraction_failed")
        return _failure_result(
            request,
            prior=prior,
            artifacts=artifacts,
            warnings=warnings,
            extraction_identity=extraction_identity,
        )

    try:
        canonical = canonical_invoice_from_ai_payload(raw_extraction)
    except (TypeError, ValueError):
        warnings.append("document_extraction_mapping_failed")
        return _failure_result(
            request,
            prior=prior,
            artifacts=artifacts,
            warnings=warnings,
            extraction_identity=extraction_identity,
        )
    canonical, direction_warning = _bind_document_direction_to_tenant(
        canonical,
        taxpayer_id=request.tenant_tax_id or request.taxpayer_id,
    )
    if direction_warning:
        warnings.append(direction_warning)
    warnings.extend(canonical.extraction_notes)
    warnings.extend(canonical.validation.reason_codes)
    canonical_content = _json_bytes(asdict(canonical))
    canonical_artifact = artifact_repository.append(
        ArtifactWrite(
            **_scope(request),
            kind=ArtifactKind.CANONICAL_INVOICE_FORM,
            stage="canonical_mapping",
            status="successful",
            parent_artifact_id=extraction_receipt.artifact_id,
            provider_receipt_artifact_id=extraction_receipt.artifact_id,
            schema_version="canonical-invoice-v2",
            mapper_version="gemini-canonical-mapper-v2",
        ),
        content=canonical_content,
    )
    artifacts.append(canonical_artifact)
    accounting_identity = GeminiInvoiceAccountingIdentity(
        chart_revision=request.accounting_identity.chart_revision,
        canonical_revision=str(canonical_artifact.content_sha256 or ""),
        candidate_builder_version=request.accounting_identity.candidate_builder_version,
        client_context_revision=request.accounting_identity.client_context_revision,
        pipeline_version=request.accounting_identity.pipeline_version,
    )
    prior = (
        prior
        if prior is not None and prior.accounting_identity == accounting_identity
        else None
    )

    projection = build_accounting_projection(
        canonical,
        warnings,
        client_context=request.client_context,
    )
    vat_linkage = derive_line_to_vat_linkage(canonical)
    projection = {
        **projection,
        "derived_line_to_vat_linkage": vat_linkage,
        "canonical_evidence_categories": canonical_evidence_categories(
            canonical,
            vat_linkage,
        ),
    }
    warnings.extend(_strings(projection.get("projection_warnings")))
    projection_artifact = artifact_repository.append(
        ArtifactWrite(
            **_scope(request),
            kind=ArtifactKind.ACCOUNTING_INPUT_PROJECTION,
            stage="accounting_projection",
            status="successful",
            parent_artifact_id=canonical_artifact.artifact_id,
            schema_version="accounting-projection-v2",
            mapper_version="accounting-projection-v2",
            metadata={
                "accounting_identity": accounting_identity.to_metadata(),
            },
        ),
        content=_json_bytes(projection),
    )
    artifacts.append(projection_artifact)

    catalog = build_accounting_candidates(request.workspace, projection)
    required_refs = required_decision_refs_for_projection(projection)
    capacity_plan = plan_accounting_decision_chunks(required_refs)
    chunk_proposals: dict[int, AccountingProposalV2] = {}
    chunk_receipts: dict[int, DocumentAiArtifact] = {}
    successful_accounting_receipts: list[DocumentAiArtifact] = []
    candidate_rounds: list[GeminiInvoiceCandidateRound] = []
    sent_candidate_ids_across_calls: list[str] = []
    active_chunk_indexes = {chunk.chunk_index for chunk in capacity_plan.chunks}

    for round_index in range(3):
        expansion_terms: list[str] = []
        expansion_requested = False
        next_active_chunk_indexes: set[int] = set()
        active_chunks = tuple(
            chunk
            for chunk in capacity_plan.chunks
            if chunk.chunk_index in active_chunk_indexes
        )
        accounting_request_details = {
            chunk.chunk_index: _bounded_accounting_request(
                projection=projection,
                sent_candidates=catalog.sent_candidates,
                required_decision_refs=chunk.required_decision_refs,
                max_request_bytes=request.max_accounting_request_bytes,
                universe_count=catalog.universe_count,
            )
            for chunk in active_chunks
        }
        accounting_requests = {
            chunk_index: detail[0]
            for chunk_index, detail in accounting_request_details.items()
        }
        if any(
            bool(detail[1]["candidate_universe_truncated"])
            for detail in accounting_request_details.values()
        ):
            warnings.append("candidate_universe_truncated")
        call_outcomes: dict[int, tuple[object | None, Exception | None]] = {}
        parallelism = min(request.max_parallel_accounting_chunks, len(active_chunks))
        if parallelism > 1:
            with ThreadPoolExecutor(max_workers=parallelism) as executor:
                futures = {
                    executor.submit(
                        accounting_provider.classify_product,
                        accounting_requests[chunk.chunk_index],
                    ): chunk.chunk_index
                    for chunk in active_chunks
                }
                for future in as_completed(futures):
                    chunk_index = futures[future]
                    try:
                        call_outcomes[chunk_index] = (future.result(), None)
                    except Exception as exc:  # noqa: BLE001 - persisted below
                        call_outcomes[chunk_index] = (None, exc)
        else:
            for chunk in active_chunks:
                try:
                    call_outcomes[chunk.chunk_index] = (
                        accounting_provider.classify_product(
                            accounting_requests[chunk.chunk_index]
                        ),
                        None,
                    )
                except Exception as exc:  # noqa: BLE001 - persisted below
                    call_outcomes[chunk.chunk_index] = (None, exc)

        for chunk in active_chunks:
            accounting_request = accounting_requests[chunk.chunk_index]
            request_metadata = accounting_request_details[chunk.chunk_index][1]
            sent_candidate_ids_across_calls.extend(
                candidate.candidate_id
                for candidate in accounting_request.sent_candidates
            )
            prior_chunk_receipt = chunk_receipts.get(chunk.chunk_index)
            try:
                raw_accounting, call_error = call_outcomes[chunk.chunk_index]
                if call_error is not None:
                    raise call_error
                accounting_attempt = _attempt(raw_accounting)
                receipt = _append_receipt(
                    artifact_repository,
                    request,
                    accounting_attempt,
                    stage="accounting_selection",
                    retry_of_artifact_id=(
                        _latest_accounting_receipt_id(
                            artifact_repository,
                            request,
                            accounting_identity=accounting_identity,
                            chunk_index=chunk.chunk_index,
                        )
                        if round_index == 0
                        else None
                    ),
                    expanded_from_receipt_id=(
                        prior_chunk_receipt.artifact_id
                        if round_index > 0 and prior_chunk_receipt is not None
                        else None
                    ),
                    accounting_identity=accounting_identity,
                    metadata={
                        "capacity_chunk_index": chunk.chunk_index,
                        "capacity_chunk_count": len(capacity_plan.chunks),
                        "candidate_round_index": round_index,
                        "required_decision_refs": list(chunk.required_decision_refs),
                        "candidate_discovery_mode": request.candidate_discovery_mode,
                        "candidate_experiment_group": request.candidate_experiment_group,
                        "candidate_experiment_bucket": request.candidate_experiment_bucket,
                        "candidate_experiment_percent": request.candidate_experiment_percent,
                        **request_metadata,
                    },
                )
                artifacts.append(receipt)
                successful_accounting_receipts.append(receipt)
                candidate_rounds.append(
                    GeminiInvoiceCandidateRound(
                        round_index=round_index,
                        chunk_index=chunk.chunk_index,
                        candidate_ids=tuple(
                            item.candidate_id for item in accounting_request.sent_candidates
                        ),
                        receipt_artifact_id=receipt.artifact_id,
                        status="successful",
                        universe_count=int(request_metadata["candidate_universe_count"]),
                        sent_count=int(request_metadata["candidate_sent_count"]),
                        coverage_ratio=float(request_metadata["candidate_coverage_ratio"]),
                        candidate_universe_truncated=bool(request_metadata["candidate_universe_truncated"]),
                        serialized_request_bytes=int(request_metadata["serialized_request_bytes"]),
                        candidate_discovery_mode=request.candidate_discovery_mode,
                        candidate_experiment_group=request.candidate_experiment_group,
                        candidate_experiment_bucket=request.candidate_experiment_bucket,
                    )
                )
            except Exception as exc:
                accounting_attempt = _attempt(exc)
                failed_receipt = _append_receipt(
                    artifact_repository,
                    request,
                    accounting_attempt,
                    stage="accounting_selection",
                    retry_of_artifact_id=(
                        _latest_accounting_receipt_id(
                            artifact_repository,
                            request,
                            accounting_identity=accounting_identity,
                            chunk_index=chunk.chunk_index,
                        )
                        if round_index == 0
                        else None
                    ),
                    expanded_from_receipt_id=(
                        prior_chunk_receipt.artifact_id
                        if round_index > 0 and prior_chunk_receipt is not None
                        else None
                    ),
                    accounting_identity=accounting_identity,
                    metadata={
                        "capacity_chunk_index": chunk.chunk_index,
                        "capacity_chunk_count": len(capacity_plan.chunks),
                        "candidate_round_index": round_index,
                        "required_decision_refs": list(chunk.required_decision_refs),
                        "candidate_discovery_mode": request.candidate_discovery_mode,
                        "candidate_experiment_group": request.candidate_experiment_group,
                        "candidate_experiment_bucket": request.candidate_experiment_bucket,
                        "candidate_experiment_percent": request.candidate_experiment_percent,
                        **request_metadata,
                    },
                )
                artifacts.append(failed_receipt)
                candidate_rounds.append(
                    GeminiInvoiceCandidateRound(
                        round_index=round_index,
                        chunk_index=chunk.chunk_index,
                        candidate_ids=tuple(
                            item.candidate_id for item in accounting_request.sent_candidates
                        ),
                        receipt_artifact_id=failed_receipt.artifact_id,
                        status="failed",
                        universe_count=int(request_metadata["candidate_universe_count"]),
                        sent_count=int(request_metadata["candidate_sent_count"]),
                        coverage_ratio=float(request_metadata["candidate_coverage_ratio"]),
                        candidate_universe_truncated=bool(request_metadata["candidate_universe_truncated"]),
                        serialized_request_bytes=int(request_metadata["serialized_request_bytes"]),
                        candidate_discovery_mode=request.candidate_discovery_mode,
                        candidate_experiment_group=request.candidate_experiment_group,
                        candidate_experiment_bucket=request.candidate_experiment_bucket,
                    )
                )
                warnings.append(
                    "accounting_chunk_failed"
                    if capacity_plan.chunking_required
                    else (
                        "accounting_expansion_failed"
                        if chunk_proposals
                        else "accounting_initial_call_failed"
                    )
                )
                continue

            sent_by_id = {
                item.candidate_id: item
                for item in accounting_request.sent_candidates
            }
            parse_result = parse_accounting_proposal_result(
                raw_accounting,
                required_decision_refs=chunk.required_decision_refs,
                sent_candidates=sent_by_id,
                decision_ref_aliases=_projection_decision_ref_aliases(projection),
                projection=projection,
                round_index=round_index,
                chunk_index=chunk.chunk_index,
                receipt_artifact_id=receipt.artifact_id,
            )
            proposal = parse_result.to_proposal(
                required_decision_refs=chunk.required_decision_refs,
                sent_candidate_ids=tuple(sent_by_id),
            )
            proposal = _preserve_last_valid_chunk_decisions(
                chunk_proposals.get(chunk.chunk_index),
                proposal,
            )
            chunk_proposals[chunk.chunk_index] = proposal
            chunk_receipts[chunk.chunk_index] = receipt
            if proposal.request_more_candidates:
                expansion_requested = True
                expansion_terms.extend(proposal.search_terms)
                next_active_chunk_indexes.add(chunk.chunk_index)

        if request.candidate_discovery_mode == "exhaustive":
            if round_index >= 2:
                break
            catalog = catalog.for_round(
                round_index + 1,
                search_terms=tuple(dict.fromkeys(expansion_terms)),
            )
            active_chunk_indexes = {
                chunk.chunk_index for chunk in capacity_plan.chunks
            }
            continue
        if not expansion_requested:
            break
        if round_index >= 2:
            warnings.append("candidate_expansion_limit_reached")
            break
        expanded = catalog.for_round(
            round_index + 1,
            search_terms=tuple(dict.fromkeys(expansion_terms)),
        )
        if expanded.sent_candidate_ids == catalog.sent_candidate_ids:
            warnings.append("candidate_expansion_returned_no_new_candidates")
            break
        catalog = expanded
        active_chunk_indexes = next_active_chunk_indexes

    if not chunk_proposals or not chunk_receipts:
        return _failure_result(
            request,
            prior=prior,
            canonical=canonical,
            projection=projection,
            artifacts=artifacts,
            warnings=warnings,
            extraction_identity=extraction_identity,
            accounting_identity=accounting_identity,
            candidate_rounds=candidate_rounds,
        )

    last_proposal = _merge_chunk_proposals(
        required_refs,
        capacity_plan=capacity_plan,
        chunk_proposals=chunk_proposals,
        sent_candidate_ids=tuple(dict.fromkeys(sent_candidate_ids_across_calls)),
    )
    for decision_ref in tuple(last_proposal.treatment_clarification_refs):
        incomplete_decision = last_proposal.decision_for(decision_ref)
        clarification_context = AccountingProposalRequestContextV2(
            semantic_stage="treatment_clarification",
            clarification_decision={
                "decision_ref": incomplete_decision.decision_ref,
                "action": incomplete_decision.action,
                "selected_candidate_id": incomplete_decision.selected_candidate_id,
                "selected_treatment": incomplete_decision.selected_treatment,
                "reason": incomplete_decision.reason,
            },
        )
        chunk = next(
            item
            for item in capacity_plan.chunks
            if decision_ref in item.required_decision_refs
        )
        prior_receipt = chunk_receipts[chunk.chunk_index]
        clarification_round_index = max(
            (
                item.round_index
                for item in candidate_rounds
                if item.chunk_index == chunk.chunk_index
            ),
            default=0,
        )
        clarification_catalog = catalog
        expanded_from_receipt_id = prior_receipt.artifact_id

        for clarification_attempt_index in (1, 2):
            attempt_round_index = clarification_round_index
            clarification_receipt: DocumentAiArtifact | None = None
            clarification_request, clarification_metadata = _bounded_accounting_request(
                projection=projection,
                sent_candidates=clarification_catalog.sent_candidates,
                required_decision_refs=("counterparty", decision_ref),
                max_request_bytes=request.max_accounting_request_bytes,
                universe_count=clarification_catalog.universe_count,
                context=clarification_context,
            )
            sent_candidate_ids_across_calls.extend(
                candidate.candidate_id
                for candidate in clarification_request.sent_candidates
            )
            receipt_metadata = {
                "capacity_chunk_index": chunk.chunk_index,
                "capacity_chunk_count": len(capacity_plan.chunks),
                "candidate_round_index": attempt_round_index,
                "required_decision_refs": ["counterparty", decision_ref],
                "clarification_for_ref": decision_ref,
                "clarification_attempt": clarification_attempt_index,
                "candidate_discovery_mode": request.candidate_discovery_mode,
                "candidate_experiment_group": request.candidate_experiment_group,
                "candidate_experiment_bucket": request.candidate_experiment_bucket,
                "candidate_experiment_percent": request.candidate_experiment_percent,
                **clarification_metadata,
            }
            try:
                raw_clarification = accounting_provider.classify_product(
                    clarification_request
                )
                clarification_attempt = _attempt(raw_clarification)
                clarification_receipt = _append_receipt(
                    artifact_repository,
                    request,
                    clarification_attempt,
                    stage="accounting_selection",
                    expanded_from_receipt_id=expanded_from_receipt_id,
                    accounting_identity=accounting_identity,
                    metadata=receipt_metadata,
                )
                artifacts.append(clarification_receipt)
                successful_accounting_receipts.append(clarification_receipt)
                clarification_sent_by_id = {
                    item.candidate_id: item
                    for item in clarification_request.sent_candidates
                }
                clarification_parse = parse_accounting_proposal_result(
                    raw_clarification,
                    required_decision_refs=("counterparty", decision_ref),
                    sent_candidates=clarification_sent_by_id,
                    decision_ref_aliases=_projection_decision_ref_aliases(projection),
                    projection=projection,
                    round_index=attempt_round_index,
                    chunk_index=chunk.chunk_index,
                    receipt_artifact_id=clarification_receipt.artifact_id,
                )
                clarification_proposal = clarification_parse.to_proposal(
                    required_decision_refs=("counterparty", decision_ref),
                    sent_candidate_ids=tuple(clarification_sent_by_id),
                )
                corrected = clarification_proposal.decision_for(decision_ref)
                corrected_is_complete = (
                    (
                        corrected.action == "select_existing"
                        and corrected.candidate is not None
                        and bool(corrected.selected_treatment)
                    )
                    or (
                        corrected.action in {"represented", "excluded"}
                        and bool(corrected.selected_treatment)
                    )
                )
                clarification_resolved = (
                    corrected_is_complete
                    and not corrected.treatment_review_required
                    and not clarification_proposal.request_more_candidates
                    and not clarification_proposal.provisional
                )
                if clarification_resolved:
                    last_proposal = _replace_proposal_decision(
                        last_proposal,
                        corrected,
                        sent_candidate_ids=tuple(clarification_sent_by_id),
                        resolved_issue_code="treatment_clarification_required",
                        warning="treatment_clarification_resolved",
                    )
                    chunk_receipts[chunk.chunk_index] = clarification_receipt
                    break

                can_expand = (
                    clarification_attempt_index == 1
                    and clarification_proposal.request_more_candidates
                    and clarification_round_index < 2
                )
                if can_expand:
                    expanded_catalog = clarification_catalog.for_round(
                        clarification_round_index + 1,
                        search_terms=clarification_proposal.search_terms,
                    )
                    if (
                        expanded_catalog.sent_candidate_ids
                        != clarification_catalog.sent_candidate_ids
                    ):
                        clarification_catalog = expanded_catalog
                        clarification_round_index += 1
                        expanded_from_receipt_id = clarification_receipt.artifact_id
                        continue

                failure_warning = (
                    "treatment_clarification_candidate_expansion_unresolved"
                    if clarification_proposal.request_more_candidates
                    else "treatment_clarification_failed"
                )
                last_proposal = replace(
                    last_proposal,
                    warnings=tuple(
                        dict.fromkeys((*last_proposal.warnings, failure_warning))
                    ),
                )
                break
            except Exception as exc:  # noqa: BLE001 - immutable failed receipt below
                clarification_attempt = _attempt(exc)
                clarification_receipt = _append_receipt(
                    artifact_repository,
                    request,
                    clarification_attempt,
                    stage="accounting_selection",
                    expanded_from_receipt_id=expanded_from_receipt_id,
                    accounting_identity=accounting_identity,
                    metadata=receipt_metadata,
                )
                artifacts.append(clarification_receipt)
                last_proposal = replace(
                    last_proposal,
                    warnings=tuple(
                        dict.fromkeys(
                            (*last_proposal.warnings, "treatment_clarification_failed")
                        )
                    ),
                )
                break
            finally:
                if clarification_receipt is not None:
                    candidate_rounds.append(
                        GeminiInvoiceCandidateRound(
                            round_index=attempt_round_index,
                            chunk_index=chunk.chunk_index,
                            candidate_ids=tuple(
                                item.candidate_id
                                for item in clarification_request.sent_candidates
                            ),
                            receipt_artifact_id=clarification_receipt.artifact_id,
                            status=clarification_receipt.status,
                            universe_count=int(
                                clarification_metadata["candidate_universe_count"]
                            ),
                            sent_count=int(clarification_metadata["candidate_sent_count"]),
                            coverage_ratio=float(
                                clarification_metadata["candidate_coverage_ratio"]
                            ),
                            candidate_universe_truncated=bool(
                                clarification_metadata["candidate_universe_truncated"]
                            ),
                            serialized_request_bytes=int(
                                clarification_metadata["serialized_request_bytes"]
                            ),
                            candidate_discovery_mode=request.candidate_discovery_mode,
                            candidate_experiment_group=request.candidate_experiment_group,
                            candidate_experiment_bucket=request.candidate_experiment_bucket,
                        )
                    )
    last_proposal = attach_semantic_conflicts(projection, last_proposal)
    warnings.extend(last_proposal.warnings)
    authoritative_receipts = tuple(
        chunk_receipts[index]
        for index in sorted(chunk_receipts)
    )
    last_successful_receipt = successful_accounting_receipts[-1]

    proposal_artifact = artifact_repository.append(
        ArtifactWrite(
            **_scope(request),
            kind=ArtifactKind.ACCOUNTING_PROPOSAL,
            stage="accounting_selection",
            status="successful",
            parent_artifact_id=projection_artifact.artifact_id,
            provider_receipt_artifact_id=last_successful_receipt.artifact_id,
            component_receipt_artifact_ids=tuple(
                item.artifact_id for item in successful_accounting_receipts
            ),
            provider=str(getattr(accounting_provider, "provider_name", "") or "gemini"),
            model_alias=str(getattr(accounting_provider, "model", "") or ""),
            prompt_version="accounting-selection-v2",
            schema_version="accounting-proposal-v2",
            metadata={
                "accounting_identity": accounting_identity.to_metadata(),
                "candidate_round_count": len(candidate_rounds),
                "capacity_chunk_count": len(capacity_plan.chunks),
                "candidate_discovery_mode": request.candidate_discovery_mode,
                "candidate_experiment_group": request.candidate_experiment_group,
                "candidate_experiment_bucket": request.candidate_experiment_bucket,
                "candidate_experiment_percent": request.candidate_experiment_percent,
            },
        ),
        content=_json_bytes(asdict(last_proposal)),
    )
    artifacts.append(proposal_artifact)
    draft = build_journal_draft(projection, last_proposal)
    quality = evaluate_accounting_quality(projection, last_proposal, draft)
    warnings.extend(quality.warnings)
    reconciliation = projection.get("monetary_reconciliation")
    reconciliation = reconciliation if isinstance(reconciliation, Mapping) else {}
    reconciliation_status = str(reconciliation.get("status") or "unavailable")
    compatibility_status = (
        "complete"
        if quality.status == "complete"
        and canonical.validation.status == "valid"
        and reconciliation_status == "exact"
        and quality.accounting_decision_status == "complete"
        and quality.draft_balance_status == "balanced"
        else "partial"
    )
    return GeminiInvoicePipelineResult(
        status=compatibility_status,
        tenant_id=request.tenant_id,
        taxpayer_id=request.taxpayer_id,
        document_id=request.document_id,
        source_file_id=request.source_file_id,
        source_file_sha256=request.source_file_sha256,
        extraction_identity=extraction_identity,
        accounting_identity=accounting_identity,
        canonical_invoice=canonical,
        projection=projection,
        proposal=last_proposal,
        draft=draft,
        quality=quality,
        artifacts=tuple(artifacts),
        warnings=tuple(dict.fromkeys(_strings(warnings))),
        candidate_rounds=tuple(candidate_rounds),
        proposal_artifact_id=proposal_artifact.artifact_id,
        processing_status="complete",
        extraction_validation_status=canonical.validation.status,
        reconciliation_status=reconciliation_status,
        accounting_decision_status=quality.accounting_decision_status,
        draft_balance_status=quality.draft_balance_status,
        review_status="review_required",
        export_status="review_required",
    )


def _failure_result(
    request: GeminiInvoicePipelineRequest,
    *,
    prior: GeminiInvoicePipelineResult | None,
    artifacts: Sequence[DocumentAiArtifact],
    warnings: Sequence[str],
    extraction_identity: GeminiInvoiceExtractionIdentity,
    accounting_identity: GeminiInvoiceAccountingIdentity | None = None,
    canonical: CanonicalInvoice | None = None,
    projection: Mapping[str, object] | None = None,
    candidate_rounds: Sequence[GeminiInvoiceCandidateRound] = (),
) -> GeminiInvoicePipelineResult:
    if prior is not None:
        combined = tuple(
            {item.artifact_id: item for item in (*prior.artifacts, *artifacts)}.values()
        )
        return GeminiInvoicePipelineResult(
            status="partial",
            tenant_id=request.tenant_id,
            taxpayer_id=request.taxpayer_id,
            document_id=request.document_id,
            source_file_id=request.source_file_id,
            source_file_sha256=request.source_file_sha256,
            extraction_identity=prior.extraction_identity,
            accounting_identity=prior.accounting_identity,
            canonical_invoice=prior.canonical_invoice,
            projection=prior.projection,
            proposal=prior.proposal,
            draft=prior.draft,
            quality=prior.quality,
            artifacts=combined,
            warnings=tuple(dict.fromkeys((*prior.warnings, *_strings(warnings)))),
            candidate_rounds=tuple(candidate_rounds) or prior.candidate_rounds,
            proposal_artifact_id=prior.proposal_artifact_id,
            retained_prior_result=True,
            processing_status="partial",
            extraction_validation_status=prior.extraction_validation_status,
            reconciliation_status=prior.reconciliation_status,
            accounting_decision_status=prior.accounting_decision_status,
            draft_balance_status=prior.draft_balance_status,
            review_status=prior.review_status,
            export_status=prior.export_status,
        )
    reconciliation = projection.get("monetary_reconciliation") if projection else None
    reconciliation = reconciliation if isinstance(reconciliation, Mapping) else {}
    return GeminiInvoicePipelineResult(
        status="partial",
        tenant_id=request.tenant_id,
        taxpayer_id=request.taxpayer_id,
        document_id=request.document_id,
        source_file_id=request.source_file_id,
        source_file_sha256=request.source_file_sha256,
        extraction_identity=extraction_identity,
        accounting_identity=accounting_identity or request.accounting_identity,
        canonical_invoice=canonical,
        projection=projection,
        proposal=None,
        draft=None,
        quality=None,
        artifacts=tuple(artifacts),
        warnings=tuple(dict.fromkeys(_strings(warnings))),
        candidate_rounds=tuple(candidate_rounds),
        processing_status="partial" if canonical is not None else "failed",
        extraction_validation_status=(
            canonical.validation.status if canonical is not None else "unavailable"
        ),
        reconciliation_status=str(reconciliation.get("status") or "unavailable"),
        accounting_decision_status="unavailable",
        draft_balance_status="unavailable",
        review_status="review_required",
        export_status="review_required",
    )


def _valid_prior(request: GeminiInvoicePipelineRequest) -> GeminiInvoicePipelineResult | None:
    prior = request.prior_valid_result
    if prior is None:
        return None
    authority_scope = (
        prior.tenant_id,
        prior.taxpayer_id,
        prior.document_id,
    )
    current_authority_scope = (
        request.tenant_id,
        request.taxpayer_id,
        request.document_id,
    )
    if authority_scope != current_authority_scope:
        raise ValueError("prior Gemini V2 result lineage scope mismatch")
    if (
        prior.source_file_id,
        prior.source_file_sha256,
    ) != (
        request.source_file_id,
        request.source_file_sha256,
    ):
        return None
    if prior.proposal is None or prior.draft is None or not prior.proposal_artifact_id:
        return None
    if (
        prior.extraction_identity.prompt_version,
        prior.extraction_identity.schema_version,
        prior.extraction_identity.pipeline_version,
    ) != (
        request.extraction_prompt_version,
        request.extraction_schema_version,
        request.pipeline_version,
    ):
        return None
    prior_identity = prior.accounting_identity
    requested_identity = request.accounting_identity
    if (
        prior_identity.chart_revision,
        prior_identity.candidate_builder_version,
        prior_identity.client_context_revision,
        prior_identity.pipeline_version,
    ) != (
        requested_identity.chart_revision,
        requested_identity.candidate_builder_version,
        requested_identity.client_context_revision,
        requested_identity.pipeline_version,
    ):
        return None
    return prior


def _prior_for_extraction_identity(
    prior: GeminiInvoicePipelineResult | None,
    extraction_identity: GeminiInvoiceExtractionIdentity,
) -> GeminiInvoicePipelineResult | None:
    if prior is None or not _compatible_extraction_identity(
        current=extraction_identity,
        previous=prior.extraction_identity,
    ):
        return None
    return prior


def _scope(request: GeminiInvoicePipelineRequest) -> dict[str, str]:
    return {
        "tenant_id": request.tenant_id,
        "taxpayer_id": request.taxpayer_id,
        "document_id": request.document_id,
        "source_file_id": request.source_file_id,
        "source_file_sha256": request.source_file_sha256,
        "pipeline_version": request.pipeline_version,
    }


def _attempt(value: object) -> object:
    attempt = getattr(value, "attempt", None)
    if attempt is None:
        raise ValueError("Gemini V2 provider result requires an exact attempt envelope")
    return attempt


def _append_receipt(
    repository: _ArtifactRepository,
    request: GeminiInvoicePipelineRequest,
    attempt: object,
    *,
    stage: str,
    retry_of_artifact_id: str | None = None,
    expanded_from_receipt_id: str | None = None,
    accounting_identity: GeminiInvoiceAccountingIdentity | None = None,
    extraction_identity: GeminiInvoiceExtractionIdentity | None = None,
    metadata: Mapping[str, object] | None = None,
) -> DocumentAiArtifact:
    status = str(getattr(attempt, "status", "") or "failed")
    return repository.append(
        ArtifactWrite(
            **_scope(request),
            kind=ArtifactKind.PROVIDER_RECEIPT,
            stage=stage,
            status=status,
            credential_slot=str(getattr(attempt, "credential_slot", "") or ""),
            retry_of_artifact_id=retry_of_artifact_id,
            expanded_from_receipt_id=expanded_from_receipt_id,
            provider=str(getattr(attempt, "provider", "") or "gemini"),
            model_alias=str(getattr(attempt, "model_alias", "") or ""),
            resolved_model=str(getattr(attempt, "resolved_model", "") or ""),
            prompt_version=(
                extraction_identity.prompt_version
                if stage == "document_extraction"
                else "accounting-selection-v2"
            ),
            schema_version=(
                extraction_identity.schema_version
                if stage == "document_extraction"
                else "accounting-proposal-v2"
            ),
            elapsed_ms=getattr(attempt, "elapsed_ms", None),
            http_status=getattr(attempt, "http_status", None),
            started_at=getattr(attempt, "started_at", None),
            finished_at=getattr(attempt, "finished_at", None),
            token_usage=dict(getattr(attempt, "token_usage", None) or {}),
            error_metadata=dict(getattr(attempt, "error_metadata", None) or {}),
            metadata={
                **(
                    {"accounting_identity": accounting_identity.to_metadata()}
                    if accounting_identity is not None
                    else {}
                ),
                **(
                    {"extraction_identity": extraction_identity.to_metadata()}
                    if extraction_identity is not None
                    else {}
                ),
                **dict(metadata or {}),
            },
        ),
        request_body=getattr(attempt, "request_body", b""),
        response_body=getattr(attempt, "response_body", b""),
    )


def _latest_extraction_receipt_id(
    repository: _ArtifactRepository,
    request: GeminiInvoicePipelineRequest,
    *,
    extraction_identity: GeminiInvoiceExtractionIdentity,
) -> str | None:
    receipts = repository.list_for_document(
        tenant_id=request.tenant_id,
        taxpayer_id=request.taxpayer_id,
        document_id=request.document_id,
        kind=ArtifactKind.PROVIDER_RECEIPT,
    )
    matching = [
        item
        for item in receipts
        if item.stage == "document_extraction"
        and item.status == "failed"
        and item.source_file_id == request.source_file_id
        and item.source_file_sha256 == request.source_file_sha256
        and _compatible_extraction_receipt(
            current=extraction_identity,
            receipt=item,
        )
    ]
    return matching[-1].artifact_id if matching else None


def _latest_accounting_receipt_id(
    repository: _ArtifactRepository,
    request: GeminiInvoicePipelineRequest,
    *,
    accounting_identity: GeminiInvoiceAccountingIdentity,
    chunk_index: int = 0,
) -> str | None:
    receipts = repository.list_for_document(
        tenant_id=request.tenant_id,
        taxpayer_id=request.taxpayer_id,
        document_id=request.document_id,
        kind=ArtifactKind.PROVIDER_RECEIPT,
    )
    expected_identity = accounting_identity.to_metadata()
    matching = [
        item
        for item in receipts
        if item.stage == "accounting_selection"
        and item.status == "failed"
        and item.source_file_id == request.source_file_id
        and item.source_file_sha256 == request.source_file_sha256
        and item.metadata.get("accounting_identity") == expected_identity
        and int(item.metadata.get("capacity_chunk_index", 0)) == chunk_index
    ]
    return matching[-1].artifact_id if matching else None


def _bounded_accounting_request(
    *,
    projection: Mapping[str, object],
    sent_candidates: Sequence[AccountingCandidate],
    required_decision_refs: Sequence[str],
    max_request_bytes: int,
    universe_count: int,
    context: AccountingProposalRequestContextV2 | None = None,
) -> tuple[AccountingProposalRequestV2, dict[str, object]]:
    candidates = tuple(sent_candidates)

    def request_for(count: int) -> tuple[AccountingProposalRequestV2, int]:
        accounting_request = AccountingProposalRequestV2(
            projection=projection,
            sent_candidates=candidates[:count],
            required_decision_refs=tuple(required_decision_refs),
            context=context or AccountingProposalRequestContextV2(),
        )
        serialized_bytes = len(
            _json_bytes(accounting_request.to_schema_payload())
        )
        return accounting_request, serialized_bytes

    empty_request, empty_size = request_for(0)
    if empty_size > max_request_bytes:
        raise ValueError(
            "Gemini V2 accounting request base payload exceeds max_accounting_request_bytes"
        )
    low = 0
    high = len(candidates)
    selected_request = empty_request
    selected_size = empty_size
    while low <= high:
        midpoint = (low + high) // 2
        candidate_request, serialized_size = request_for(midpoint)
        if serialized_size <= max_request_bytes:
            selected_request = candidate_request
            selected_size = serialized_size
            low = midpoint + 1
        else:
            high = midpoint - 1
    sent_count = len(selected_request.sent_candidates)
    coverage_ratio = sent_count / universe_count if universe_count else 1.0
    return selected_request, {
        "candidate_universe_count": universe_count,
        "candidate_sent_count": sent_count,
        "candidate_coverage_ratio": coverage_ratio,
        "candidate_universe_truncated": sent_count < len(candidates),
        "serialized_request_bytes": selected_size,
        "max_accounting_request_bytes": max_request_bytes,
    }


def _merge_chunk_proposals(
    required_refs: Sequence[str],
    *,
    capacity_plan: object,
    chunk_proposals: Mapping[int, AccountingProposalV2],
    sent_candidate_ids: Sequence[str],
) -> AccountingProposalV2:
    required = tuple(required_refs)
    decisions_by_ref: dict[str, AccountingDecisionV2] = {}
    counterparty: AccountingDecisionV2 | None = None
    search_terms: list[str] = []
    sufficiency_reasons: list[str] = []
    validation_issues = []
    proposal_warnings: list[str] = []

    for chunk in capacity_plan.chunks:
        proposal = chunk_proposals.get(chunk.chunk_index)
        if proposal is None:
            continue
        if counterparty is None or proposal.counterparty.action != "unresolved":
            counterparty = proposal.counterparty
        for decision in proposal.decisions:
            if decision.decision_ref != "counterparty":
                decisions_by_ref[decision.decision_ref] = decision
        search_terms.extend(proposal.search_terms)
        if proposal.sufficiency_reason:
            sufficiency_reasons.append(proposal.sufficiency_reason)
        validation_issues.extend(proposal.validation_issues)
        proposal_warnings.extend(proposal.warnings)

    if counterparty is None:
        counterparty = AccountingDecisionV2(
            decision_ref="counterparty",
            action="unresolved",
            reason="no valid accounting chunk returned a counterparty decision",
        )
    decisions: list[AccountingDecisionV2] = [counterparty]
    for decision_ref in required:
        if decision_ref == "counterparty":
            continue
        decisions.append(
            decisions_by_ref.get(decision_ref)
            or AccountingDecisionV2(
                decision_ref=decision_ref,
                action="unresolved",
                reason="accounting decision chunk did not return a valid decision",
            )
        )

    all_chunks_valid = len(chunk_proposals) == len(capacity_plan.chunks)
    all_sufficient = all_chunks_valid and all(
        proposal.candidate_sufficient
        and not proposal.request_more_candidates
        and not proposal.provisional
        for proposal in chunk_proposals.values()
    )
    request_more = any(
        proposal.request_more_candidates for proposal in chunk_proposals.values()
    )
    return AccountingProposalV2(
        counterparty=counterparty,
        decisions=tuple(decisions),
        required_decision_refs=required,
        candidate_sufficient=all_sufficient,
        request_more_candidates=request_more,
        search_terms=tuple(dict.fromkeys(search_terms)),
        sufficiency_reason=" | ".join(dict.fromkeys(sufficiency_reasons)),
        provisional=(not all_sufficient),
        sent_candidate_ids=tuple(dict.fromkeys(sent_candidate_ids)),
        validation_issues=tuple(validation_issues),
        warnings=tuple(dict.fromkeys(proposal_warnings)),
    )


def _preserve_last_valid_chunk_decisions(
    prior: AccountingProposalV2 | None,
    current: AccountingProposalV2,
) -> AccountingProposalV2:
    if prior is None:
        return current
    invalid_refs = {
        issue.decision_ref
        for issue in current.validation_issues
        if issue.decision_ref != "candidate_sufficiency"
        and issue.code
        not in {
            "nonoperative_treatment_ignored",
            "treatment_clarification_required",
            "zero_fact_normalized_to_no_separate_posting",
        }
    }
    prior_by_ref = {decision.decision_ref: decision for decision in prior.decisions}
    current_by_ref = {decision.decision_ref: decision for decision in current.decisions}
    preserved_refs: list[str] = []
    merged: list[AccountingDecisionV2] = []
    for decision_ref in current.required_decision_refs:
        current_decision = current_by_ref.get(decision_ref)
        prior_decision = prior_by_ref.get(decision_ref)
        if (
            decision_ref in invalid_refs
            and prior_decision is not None
            and prior_decision.action != "unresolved"
        ):
            merged.append(prior_decision)
            preserved_refs.append(decision_ref)
        elif current_decision is not None:
            merged.append(current_decision)
    counterparty = next(
        (decision for decision in merged if decision.decision_ref == "counterparty"),
        current.counterparty,
    )
    warnings = list(prior.warnings)
    if preserved_refs:
        warnings.extend(
            ("latest_ai_decision_invalid", "using_last_valid_ai_decision")
        )
    return replace(
        current,
        counterparty=counterparty,
        decisions=tuple(merged),
        validation_issues=(*prior.validation_issues, *current.validation_issues),
        warnings=tuple(dict.fromkeys(warnings)),
    )


def _replace_proposal_decision(
    proposal: AccountingProposalV2,
    corrected: AccountingDecisionV2,
    *,
    sent_candidate_ids: Sequence[str],
    resolved_issue_code: str,
    warning: str,
) -> AccountingProposalV2:
    decisions = tuple(
        corrected if decision.decision_ref == corrected.decision_ref else decision
        for decision in proposal.decisions
    )
    validation_issues = tuple(
        issue
        for issue in proposal.validation_issues
        if not (
            issue.decision_ref == corrected.decision_ref
            and issue.code == resolved_issue_code
        )
    )
    return replace(
        proposal,
        decisions=decisions,
        sent_candidate_ids=tuple(
            dict.fromkeys((*proposal.sent_candidate_ids, *sent_candidate_ids))
        ),
        validation_issues=validation_issues,
        warnings=tuple(dict.fromkeys((*proposal.warnings, warning))),
    )


def _projection_decision_ref_aliases(
    projection: Mapping[str, object],
) -> dict[str, str]:
    aliases: dict[str, str] = {}
    for section in ("line_items", "vat_summary", "tax_components", "monetary_components"):
        raw_items = projection.get(section)
        if not isinstance(raw_items, Sequence) or isinstance(raw_items, (str, bytes)):
            continue
        for raw_item in raw_items:
            if not isinstance(raw_item, Mapping):
                continue
            identity_ref = str(raw_item.get("identity_ref") or "").strip()
            decision_ref = str(raw_item.get("decision_ref") or "").strip()
            if identity_ref and decision_ref and identity_ref != decision_ref:
                aliases[identity_ref] = decision_ref
    return aliases


def _extraction_identity(
    request: GeminiInvoicePipelineRequest,
    attempt: object,
) -> GeminiInvoiceExtractionIdentity:
    return GeminiInvoiceExtractionIdentity(
        source_file_id=request.source_file_id,
        source_file_sha256=request.source_file_sha256,
        provider=str(getattr(attempt, "provider", "") or ""),
        model_alias=str(getattr(attempt, "model_alias", "") or ""),
        resolved_model=str(getattr(attempt, "resolved_model", "") or ""),
        prompt_version=request.extraction_prompt_version,
        schema_version=request.extraction_schema_version,
        pipeline_version=request.pipeline_version,
    )


def _compatible_extraction_receipt(
    *,
    current: GeminiInvoiceExtractionIdentity,
    receipt: DocumentAiArtifact,
) -> bool:
    previous = GeminiInvoiceExtractionIdentity(
        source_file_id=receipt.source_file_id,
        source_file_sha256=receipt.source_file_sha256,
        provider=str(receipt.provider or ""),
        model_alias=str(receipt.model_alias or ""),
        resolved_model=str(receipt.resolved_model or ""),
        prompt_version=str(receipt.prompt_version or ""),
        schema_version=str(receipt.schema_version or ""),
        pipeline_version=receipt.pipeline_version,
    )
    return (
        receipt.metadata.get("extraction_identity") == previous.to_metadata()
        and _compatible_extraction_identity(current=current, previous=previous)
    )


def _compatible_extraction_identity(
    *,
    current: GeminiInvoiceExtractionIdentity,
    previous: GeminiInvoiceExtractionIdentity,
) -> bool:
    if (
        current.source_file_id,
        current.source_file_sha256,
        current.provider,
        current.model_alias,
        current.prompt_version,
        current.schema_version,
        current.pipeline_version,
    ) != (
        previous.source_file_id,
        previous.source_file_sha256,
        previous.provider,
        previous.model_alias,
        previous.prompt_version,
        previous.schema_version,
        previous.pipeline_version,
    ):
        return False
    return not current.resolved_model or current.resolved_model == previous.resolved_model


def _bind_document_direction_to_tenant(
    invoice: CanonicalInvoice,
    *,
    taxpayer_id: str,
) -> tuple[CanonicalInvoice, str]:
    tenant_identity = _normalized_tax_identity(taxpayer_id)
    supplier_identity = _normalized_tax_identity(invoice.supplier_party.tax_id)
    customer_identity = _normalized_tax_identity(invoice.customer_party.tax_id)
    supplier_match = bool(tenant_identity and tenant_identity == supplier_identity)
    customer_match = bool(tenant_identity and tenant_identity == customer_identity)
    if supplier_match != customer_match:
        direction = "sales" if supplier_match else "purchase"
        return (
            replace(
                invoice,
                header=replace(invoice.header, document_direction=direction),
            ),
            "",
        )
    current_direction = str(invoice.header.document_direction or "").strip().lower()
    if current_direction in {"purchase", "sales"}:
        return invoice, ""
    return (
        replace(
            invoice,
            header=replace(invoice.header, document_direction="unknown"),
        ),
        "document_direction_unresolved",
    )


def _normalized_tax_identity(value: object) -> str:
    return "".join(
        character
        for character in str(value or "").upper()
        if character.isalnum()
    )


def _json_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")


def _strings(values: object) -> tuple[str, ...]:
    if isinstance(values, str):
        values = (values,)
    if not isinstance(values, Sequence) or isinstance(values, bytes):
        return ()
    return tuple(str(value).strip() for value in values if str(value).strip())
