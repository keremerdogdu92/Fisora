# QNB Real Method Mapping

**Goal:** Map the real QNB eSolutions SOAP documentation, WSDL, and mail-provided test environment details to the Fisora Phase 1 incoming e-Fatura integration design.

**Sources used:**
- Mail text provided by QNB in `C:\Users\kerem\.codex\attachments\cc149412-cf43-43be-904b-d032d8560d39\pasted-text.txt`
- QNB public API documentation: https://www.qnbesolutions.com.tr/api-docs-tr-final.html
- e-Fatura test1 user WSDL: https://erpefaturatest1.qnbesolutions.com.tr/efatura/ws/userService?wsdl
- e-Fatura test1 connector WSDL: https://erpefaturatest1.qnbesolutions.com.tr/efatura/ws/connectorService?wsdl
- WSDL imports: `?wsdl=1` and `?xsd=1`

---

## Mail-Derived Integration Facts

| Item | Value / Rule | Fisora impact |
| --- | --- | --- |
| ERP code | `FSR31422` | Use as the fixed QNB ERP code for all firms in this ERP integration. Store in env/config, not per client. |
| Rate limit | 180 requests per minute | Add adapter-level throttling or conservative sync batching before scheduled sync. |
| e-Fatura test platform | `erpefaturatest1` and `erpefaturatest2` | Use these for incoming e-Fatura Phase 1 validation. |
| e-Fatura test1 VKN/user | `5910611340` | Candidate receiving account for Fisora tests. Password is not in the mail. |
| e-Fatura test2 VKN/user | `5910611341` | Candidate sending account for cross-test documents. Password is not in the mail. |
| Cross-account test rule | Test1 and test2 can exchange documents with each other; same-account send is not supported. | Use one account as sender and the other as the Fisora receiving account. |
| e-Arsiv test platform | `portaltest` / `earsivtest` | Out of Phase 1 scope. Keep separate for later phases. |
| Portal vs WS user | QNB recommends a separate WS user to avoid lockout when portal password changes. | Prefer a dedicated WS user before repeated automated tests. |

Do not paste QNB passwords into docs, commits, pipeline events, or chat. Use local environment variables or a secret store during connection tests.

---

## Endpoint Mapping

| Purpose | Test1 endpoint | Test2 endpoint |
| --- | --- | --- |
| Portal | `https://erpefaturatest1.qnbesolutions.com.tr/yonetim` | `https://erpefaturatest2.qnbesolutions.com.tr/yonetim/` |
| User service WSDL | `https://erpefaturatest1.qnbesolutions.com.tr/efatura/ws/userService?wsdl` | `https://erpefaturatest2.qnbesolutions.com.tr/efatura/ws/userService?wsdl` |
| Connector service WSDL | `https://erpefaturatest1.qnbesolutions.com.tr/efatura/ws/connectorService?wsdl` | `https://erpefaturatest2.qnbesolutions.com.tr/efatura/ws/connectorService?wsdl` |

The two WSDLs expose the same operation set. The selected client connection decides which host and credentials are used.

---

## Authentication

### `wsLogin`

WSDL/XSD fields:

```text
wsLogin
  userId: string
  password: string
  lang: string
```

Recommended `lang`: `tr`.

`wsLoginResponse` has no body fields in the XSD. Session state is cookie-based, so the SOAP client must preserve the cookie container between `userService` and `connectorService` calls.

### `logout`

WSDL exposes `logout` with no request fields. Use it after manual sync/test runs when the SOAP client supports session cleanup.

### Fisora mapping

| QNB step | Fisora field / behavior |
| --- | --- |
| `wsLogin` succeeds | `qnb_connection.status = active` |
| Auth failure | `qnb_connection.status = auth_failed` |
| Network/SOAP failure | `qnb_connection.status = connection_failed` |
| Cookie/session returned | Keep in process only; never store as document metadata or event detail. |

---

## ERP Code Handling

The mail says the ERP code applies to receiving methods as well as sending methods.

Two patterns are available:

| Pattern | Rule |
| --- | --- |
| `Ext` methods | Fill the method's `erpKodu` / `erpKodu`-equivalent request field. |
| Non-`Ext` methods | Call `erpBilgileriBelirle(vergiTcKimlikNo, erpBilgileri)` before the operation. |

Phase 1 should prefer `Ext` methods so the ERP code is carried directly in the request parameters and does not rely on a preceding state-setting call.

`erpBilgileriBelirle` exists in the connector WSDL/XSD:

```text
erpBilgileriBelirle
  vergiTcKimlikNo: string
  erpBilgileri:
    kod: string
    aciklama: string
```

Keep it available as a fallback if QNB support instructs us to use non-`Ext` methods in a specific account setup.

---

## Phase 1 Method Mapping

### 1. Test Connection

| Adapter operation | QNB operation | Notes |
| --- | --- | --- |
| `test_connection` | `wsLogin` then optional lightweight connector call | Requires credentials and cookie-preserving SOAP session. |

Initial implementation can call `wsLogin` only. A stronger test should also call a safe connector method with the same cookie session, such as a small incoming list request with an empty/future date range.

### 2. List Incoming e-Fatura

Primary method:

```text
gelenBelgeleriListeleExt(parametreler: gelenBelgeParametreleri)
```

XSD request wrapper:

```text
gelenBelgeleriListeleExt
  parametreler: gelenBelgeParametreleri
```

Relevant `gelenBelgeParametreleri` fields:

```text
vergiTcKimlikNo: string
belgeTuru: string
sonAlinanBelgeSiraNumarasi: string
donusTipiVersiyon: string
erpKodu: string
ettn: string[]
faturaTarihiBaslangic: string
faturaTarihiBitis: string
gelisTarihiBaslangic: string
gelisTarihiBitis: string
onayDurum: string
alanEtiket: string[]
belgelerAlindiMi: boolean
belgeFormati: string
belgeVersiyon: string
```

Phase 1 request choices:

| QNB field | Phase 1 value | Reason |
| --- | --- | --- |
| `vergiTcKimlikNo` | Client VKN/TCKN for the QNB account | Required account scope. |
| `belgeTuru` | `FATURA` | Incoming e-Fatura only. |
| `erpKodu` | `FSR31422` | Required ERP code from QNB mail for ERP integrations. |
| `donusTipiVersiyon` | Start with `5.0` | QNB sample uses `5.0`; verify exact returned subtype during spike. |
| `sonAlinanBelgeSiraNumarasi` | Cursor value when paging by portal sequence | QNB documents say each response returns up to 100 documents ordered by `belgeSiraNo`. |
| `gelisTarihiBaslangic` / `gelisTarihiBitis` | Manual sync date range if using arrival date | Good first match for "QNB'den gelenleri al". |
| `faturaTarihiBaslangic` / `faturaTarihiBitis` | Optional alternate range | Use only if accountant wants invoice issue-date filtering. |
| `onayDurum` | `HEPSI` or blank | Blank returns only approved documents per docs; `HEPSI` is better for status-aware review if QNB accepts it. Verify with sandbox. |

Important QNB rule from documentation: `sonAlinanBelgeSiraNumarasi` should not be combined with some other filters such as arrival date, approval status, branch code, and mailbox label. Phase 1 manual date-range sync should use date filters. Phase 2 cursor sync should use `belgeSiraNo`.

Response:

```text
gelenBelgeleriListeleExtResponse
  return: serviceReturnType[]
```

Known response subtype fields from XSD:

```text
belge extends serviceReturnType
  aliciVkn
  belgeNo
  belgeSiraNo
  belgeTarihi
  belgeTuru
  belgeVerisi
  dovizCinsi
  ettn
  faturaSenaryo
  gonderenEtiket
  gonderenIsim
  gonderenVknTckn
  payableAmount
  yanitDetayi
  yanitDurumu

belgev2 extends belge
  alanEtiket
  aliciUnvan
  belgeVersiyon
  belgeXmlZipped
  ekBilgiler
  saticiUnvan
  subeKodu
  zarfId
  zarfVerisi
  zarfXml
```

Fisora summary mapping:

| QNB response | Fisora summary field |
| --- | --- |
| `ettn` | `source_external_uuid` and primary duplicate key |
| `belgeNo` | `source_invoice_no` |
| `belgeSiraNo` | `source_qnb_sequence_no` and Phase 2 cursor |
| `belgeTarihi` | `source_issue_date` |
| `gonderenVknTckn` | `source_supplier_tax_id` |
| `gonderenIsim` / `saticiUnvan` | source supplier title evidence |
| `payableAmount` | `source_payable_total` |
| `yanitDurumu` / `yanitDetayi` | source response/status evidence |

### 3. Download Incoming UBL

Primary method:

```text
gelenBelgeleriIndirExt(parametreler: gelenBelgeParametreleri) -> base64Binary
```

Alternative method:

```text
gelenBelgeIndirExt(vergiTcKimlikNo, belgeEttn, belgeTuru, belgeFormati) -> base64Binary
```

Phase 1 should prefer `gelenBelgeleriIndirExt` because it carries `erpKodu` through `gelenBelgeParametreleri`.

Download request choices:

| QNB field | Phase 1 value |
| --- | --- |
| `vergiTcKimlikNo` | Client VKN/TCKN |
| `belgeTuru` | `FATURA` |
| `belgeFormati` | `UBL` |
| `ettn` | Single ETTN from list result |
| `erpKodu` | `FSR31422` |

QNB docs say the return is base64 compressed content. Phase 1 implementation must decode base64 and unzip before storing the UBL XML. The stored Fisora document should be the XML, not the zip wrapper.

Fisora document mapping:

| Download result | Fisora field |
| --- | --- |
| Decoded XML bytes | document content |
| SHA-256 of XML bytes | `source_content_sha256` |
| File name | `qnb-{ettn}.xml` or invoice-number-safe equivalent |
| `belgeFormati=UBL` | `document_type = einvoice_xml` |
| Incoming e-Fatura source | `intake_category = purchase_invoice` as a hint |

### 4. Status Reconciliation

Phase 1.5 method candidate:

```text
gelenBelgeDurumSorgulaExt(parametreler: gelenBelgeParametreleri) -> serviceReturnType
```

Request likely uses the same identity fields:

```text
vergiTcKimlikNo
belgeTuru = FATURA
ettn
erpKodu
```

Implementation must verify exact returned status fields and values with sandbox payloads before coding review behavior.

---

## Cursor and Paging Rules

QNB documentation says:
- One list call returns at most 100 documents.
- Returned documents are ordered by `belgeSiraNo`.
- To continue paging, call `gelenBelgeleriListeleExt` again with the last returned `belgeSiraNo` as `sonAlinanBelgeSiraNumarasi`.

Fisora Phase 1:
- Manual date-range sync can page within the selected window.
- Duplicate detection still uses ETTN/content identity, not dates.

Fisora Phase 2:
- Scheduled sync should maintain `last_qnb_belge_sira_no` as a cursor per client/connection.
- Date backfill and cursor sync should be separate modes to avoid invalid QNB parameter combinations.

---

## Environment Variables for Spike

Do not commit values.

```text
QNB_ERP_CODE=FSR31422
QNB_EFATURA_TEST1_BASE_URL=https://erpefaturatest1.qnbesolutions.com.tr/efatura/ws
QNB_EFATURA_TEST1_USERNAME=5910611340
QNB_EFATURA_TEST1_PASSWORD=store the test password only in local env or a secret manager
QNB_EFATURA_TEST2_BASE_URL=https://erpefaturatest2.qnbesolutions.com.tr/efatura/ws
QNB_EFATURA_TEST2_USERNAME=5910611341
QNB_EFATURA_TEST2_PASSWORD=store the test password only in local env or a secret manager
```

If a dedicated WS user is created, replace the username/password values with that WS user. Keep the original portal user for human portal access.

---

## Implementation Questions To Verify With Sandbox

These are not product blockers, but they must be proven before final implementation:

1. Whether `donusTipiVersiyon=5.0` returns `belge`, `belgev2`, or another concrete shape in Python SOAP clients.
2. Whether `onayDurum=HEPSI` is accepted for the selected test account and whether blank status hides useful pending/rejected documents.
3. Whether `gelisTarihiBaslangic` accepts `yyyyMMdd` or the longer timestamp format shown in sample snippets for this exact method.
4. Whether `gelenBelgeleriIndirExt` returns a zip containing exactly one XML file for UBL.
5. Whether QNB requires `erpBilgileriBelirle` before `gelenBelgeleriIndirExt` despite the `erpKodu` field.
6. What concrete fault codes are returned for bad password, bad ERP code, no documents, and rate limit.
7. Whether `gelenBelgeDurumSorgulaExt` returns enough cancellation/rejection state for Phase 1.5 or whether another status/history method is more appropriate.

---

## Recommended Next Step

Create the implementation plan around a fake-adapter-first backend slice:

1. Define Fisora-side QNB connection, summary, download, and sync result models.
2. Build a fake QNB adapter from the mapped response fields.
3. Wire sync service into existing document storage and processing job creation.
4. Add API and minimal portal UI.
5. Add the real SOAP adapter behind the same interface.
6. Run sandbox login/list/download after passwords are available in local env.
