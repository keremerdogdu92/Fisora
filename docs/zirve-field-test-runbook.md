# Zirve Field Test Runbook

## Test Input

- Export adapter: `zirve_mapping_csv`
- File type: CSV, UTF-8-SIG, semicolon delimiter
- Documents: one purchase invoice, one sales invoice, one bank transaction if available
- Documents themselves are not uploaded to Zirve; only journal/voucher rows are tested.

## Generate Test File

Use the portal export flow or backend export package route with:

```text
export_type=zirve_mapping_csv
```

Record before opening Zirve:

- Client
- Period
- File name
- Entry count
- Debit total
- Credit total
- Export package id if available

Local synthetic sample generated on 2026-07-07:

- File: `exports/generated/zirve-field-test/sample-zirve_mapping_csv.csv`
- Entry count: 3
- Line count: 7
- Debit total: 390.00
- Credit total: 390.00
- Header: `hesap_kodu;evrak_tarihi;evrak_no;belge_turu;aciklama;borc;alacak;vkn_tckn;odeme_sekli;fis_turu;satir_no;kaynak_belge`

## Zirve Manual Mapping

Map the CSV columns manually in the Zirve import screen:

- `hesap_kodu`: Zirve account code field
- `evrak_tarihi`: document/voucher date field
- `evrak_no`: document number field
- `belge_turu`: document type or voucher type field
- `aciklama`: line description field
- `borc`: debit amount field
- `alacak`: credit amount field
- `vkn_tckn`: tax id field if Zirve screen accepts it
- `odeme_sekli`: payment method field if Zirve screen accepts it
- `fis_turu`: voucher type field if separate from document type
- `satir_no`: optional line order field
- `kaynak_belge`: optional audit/source reference field

## Pass Criteria

- Zirve accepts the file with manual column mapping.
- Debit and credit totals match the Fisora export.
- Voucher date, document number, account code, debit, credit, and description land in the expected Zirve fields.
- Optional fields are either accepted or documented as ignored.
- No document attachment is required for the import to succeed.

## Failure Log

If import fails, record:

- Zirve screen name
- Error message exactly as shown
- Failing column
- Required date format, decimal format, or mandatory field
- Whether the fix is CSV column rename, value formatting, or extra required field

## Result Log

| Date | Zirve version | Tester | File | Result | Required changes |
|---|---|---|---|---|---|
| TBD | TBD | TBD | TBD | field_test_pending | TBD |

## Adapter Status Rule

Keep `zirve_mapping_csv` as:

```text
verified_in_zirve=false
validation_status=field_test_pending
```

Only switch to `verified` after a successful accountant-side import with the
result log filled in.
