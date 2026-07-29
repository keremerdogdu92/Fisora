# 50 Invoice Accountant Reference Runbook

This runbook defines local preflight and ordinary authenticated intake. It does not upload, enroll, freeze, or delete pilot data.

## Preflight

```powershell
python backend/scripts/prepare_reference_corpus_admission.py `
  --manifest private_samples/reference_corpus_manifest.json `
  --source-root private_samples/real_pilot `
  --output private_samples/reference_corpus_preflight.json
```

The manifest must contain exactly 35 purchase and 15 sales invoices, unique SHA-256 values, valid `YYYY-MM` periods, supported invoice document types, and paths contained by the source root. Preflight writes only a safe count/hash summary below the ignored `private_samples` directory.

## Ordinary intake and review

1. Authenticated accountant selects the correct client.
2. Upload through `POST /phase0/store/document-upload-multipart` with manifest `period` and `document_type`.
3. Compare response source hash and document reference with the manifest.
4. Verify direction from canonical XML/PDF parties and line evidence.
5. Enroll through `POST /phase0/store/corpora/{corpus_id}/items`.
6. After all sources are enrolled, process and review each document.

For each invoice inspect canonical parties, direction, lines, VAT, totals, proposed journal, and explanation. Approve unchanged or correct then approve. Save a rule only when the accountant confirms a genuinely reusable condition. Every completed invoice needs an authoritative reference outcome, including unchanged approvals.

Freeze requires 35 purchase items, 15 sales items, 50 unique source hashes, a reference outcome and balanced final journal for every item, complete canonical line/allocation coverage, current source-hash matches, and no cross-tenant item.
