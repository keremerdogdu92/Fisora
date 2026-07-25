# QNB Giden Fatura Sandbox Hazırlık Uygulama Planı

> **Agentic worker zorunluluğu:** Bu plan görev görev uygulanırken
> `superpowers:subagent-driven-development` (önerilen) veya
> `superpowers:executing-plans` kullanılmalıdır. Takip için checkbox (`- [ ]`)
> biçimi kullanılır.

**Hedef:** Mevcut giden fatura akışını fail-closed routing, immutable kanıt,
belirsiz sonuç mutabakatı ve sıfır production gönderim kabiliyetiyle gerçek QNB
e-Fatura/e-Arşiv sandbox operasyonlarına bağlamak.

**Mimari:** Yalnız server tarafında çalışan provider factory varsayılan olarak
`disabled` olur ve sadece doğrulanmış QNB test endpointleri için client-kapsamlı
`QnbSandboxOutgoingInvoiceProvider` kurar. Outgoing service tek bir append-only
attempt'i atomik olarak claim eder, dondurulmuş UBL'yi doğrular, mutating SOAP
çağrısını yalnız bir kez yapar ve kesin sonuçları `reconciliation_required`
durumundan ayırır. Doğrulanmış QNB belgeleri mevcut canonical satış faturası ve
review-gate'li muhasebe akışına girer.

**Teknoloji:** Python 3, FastAPI, dataclass/protocol, QNB SOAP adapterleri, JSON
workflow store, PostgreSQL `workflow_records`, `unittest`, mevcut readiness
kontratları.

**Tasarım:** `docs/superpowers/specs/2026-07-21-qnb-outgoing-sandbox-readiness-design.md`

**Ana plan:** `docs/superpowers/plans/2026-07-10-qnb-end-to-end-integration.md`
Faz 8-9.

## 2026-07-21 uygulama durumu

- Gorev 1-6 yerel olarak uygulandi. Son proof backend `554 OK (skipped=19)`,
  frontend `147/147`, Next production build basarili; bagimsiz son engineering
  review'da kalan P0/P1 bulgu yok.
- Uzlastirma icin atomik owner/lease ve stale takeover eklendi; aktif gonderim
  veya uzlastirma ile ikinci uzlastirma ayni provider/canonical isi yurutemez.
- Gorev 7 plan-only e-Fatura ve e-Arsiv kosularinda `sent=false` tamamlandi.
  Kullanici onayli gercek kabul denemelerinin sonucu asagida kayitli.
- Gorev 8'in tam yerel proof'u tamamlandi. Gercek PostgreSQL concurrency
  smoke'u `DATABASE_URL` olmadigi icin acik
  DSN-gated kabul kapisidir.

### 2026-07-21 gercek sandbox kabul sonucu

- Kullanici iki test belgesi icin acik onay verdi.
- e-Fatura TEST1 WS login HTTP 500 nedeniyle etiket preflight'inda durdu;
  mutating `belgeGonderExt` cagrisi cikmadi ve belge olusmadi.
- e-Arsiv icin tek `faturaOlusturExt` cagrisi yapildi ve QNB `AE00001` ile
  kesin reddetti. Retry/resend yapilmadi. Fatura no ile salt-okunur sorgu
  `AE00002` ile belgenin QNB'de kayitli olmadigini kanitladi.
- Sorgu kontratinin `islemId` degil provider fatura kimlikleri istedigi
  kanitlandi; adapter, reconciliation ve secret-safe resultText saklanmasi
  duzeltildi. Hedefli QNB proof `55 OK`.
- Canli kanitla e-Arsiv reconciliation `faturaUuid`/`faturaNo` sorgusuna
  duzeltildi; `resultText` hata kanitinda korunuyor. Hedefli testler `55 OK`.
- Gercek e-Fatura/e-Arsiv basari kapilari acik: TEST1 WS hesabi ve e-Arsiv
  portal mali muhur/e-imza + ayri WS kullanicisi QNB tarafinda tamamlanmali.

>>>>>>> codex/qnb-outgoing-sandbox
## Genel kısıtlar

- Production provider modu veya production endpoint desteği eklenmeyecek.
- Varsayılan runtime dispatch-disabled olacak; fake mode açıkça seçilecek.
- Provider/endpoint modu server-controlled olacak ve request payload'dan
  alınmayacak.
- Mutating QNB operasyonları otomatik retry edilmeyecek.
- `reconciliation_required`, read-only kanıt attempt'i kapatana kadar bütün
  mutating retry'ları engelleyecek.
- Credential client-kapsamlı ve encrypted olacak; secret/session token API,
  log, attempt kanıtı veya committed dosyaya girmeyecek.
- Approval-time UBL byte'ları immutable olacak ve SHA-256 gönderim öncesi tekrar
  doğrulanacak.
- QNB delivery durumu canonical, review, muhasebe veya export gate'ini aşmayacak.
- İlgisiz dirty-worktree değişiklikleri korunacak.
- Gerçek sandbox artifact'leri ignored/private kalacak.
- Ayrı release onayı verilmeden commit, push, deploy veya production mutation
  yapılmayacak.

---

### Görev 1: Outgoing durum ve provider kontratlarını sabitle

**Dosyalar:**
- Değiştir: `backend/app/domain/outgoing_invoices.py`
- Test et: `backend/tests/test_outgoing_invoices.py`

**Arayüzler:**
- Üretir: `OutgoingProviderReceipt`, `OutgoingProviderOutcomeUnknown`, normalize
  `OutgoingInvoiceProvider.send/reconcile`.
- Üretir: `approved`, `sending`, `sent`, `failed`,
  `reconciliation_required` durumları.

- [ ] Açık provider reddinin `failed`, post-submit timeout'ın
  `reconciliation_required` olduğunu ve ambiguous durumda aynı/yeni key'in
  ikinci gönderim çıkarmadığını kanıtlayan failing testleri yaz.
- [ ] `python -m unittest backend.tests.test_outgoing_invoices.OutgoingInvoiceServiceTests`
  çalıştır; mevcut blanket `failed` davranışının yeni assertion'larda fail
  verdiğini doğrula.
- [ ] Frozen receipt ve outcome tiplerini ekle:

```python
@dataclass(frozen=True)
class OutgoingProviderReceipt:
    provider: str
    provider_operation: str
    provider_document_id: str = ""
    provider_transaction_id: str = ""
    provider_invoice_no: str = ""
    provider_status: str = ""
    response_received: bool = True
    evidence: dict[str, object] = field(default_factory=dict)

class OutgoingProviderOutcomeUnknown(RuntimeError):
    pass
```

- [ ] `OutgoingInvoiceProvider` dönüşünü `OutgoingProviderReceipt` yap ve
  read-only `reconcile(invoice, attempt)` kontratını ekle.
- [ ] `FakeOutgoingInvoiceProvider`ı normalize receipt ve deterministic SHA-256
  kanıtı döndürecek şekilde güncelle.
- [ ] `OutgoingInvoiceService.send()` içinde açık ret, unknown outcome ve
  confirmed success için farklı geçişler uygula; unknown outcome'u sıradan
  failure olarak yakalama.
- [ ] Provider çağrısından önce UBL SHA-256'yı yeniden hesapla; mismatch'i
  request başlamadan reddet.
- [ ] Hedefli servis testlerini çalıştır ve tamamının geçtiğini doğrula.

### Görev 2: Append-only attempt persistence ve atomik idempotency ekle

**Dosyalar:**
- Değiştir: `backend/app/persistence/workflow_store.py`
- Değiştir: `backend/app/persistence/postgres_workflow_store.py`
- Test et: `backend/tests/test_workflow_store.py`
- Test et: `backend/tests/test_outgoing_invoices.py`
- Test et: `backend/tests/test_normalized_invoice_journal_postgres.py`

**Arayüzler:**
- Üretir: `claim_outgoing_invoice_attempt(...) -> tuple[bool, invoice, attempt]`.
- Üretir: `append_outgoing_invoice_attempt_event(...)`,
  `get_outgoing_invoice_attempt(...)`, `list_outgoing_invoice_attempts(...)`.

- [ ] JSON store için `client_id + idempotency_key` başına tek attempt, farklı
  invoice/hash ile key reuse reddi ve append-only event sırasını kanıtlayan
  failing testleri yaz.
- [ ] PostgreSQL için iki aynı-key claim'in tek `request_started` attempt
  ürettiğini ve iki caller'ın aynı attempt ID'yi gördüğünü kanıtlayan failing
  concurrency testi yaz.
- [ ] Hedefli testleri çalıştır; mevcut send-key-only kontratın yeni attempt
  assertion'larını karşılamadığını doğrula.
- [ ] Immutable attempt payload'ını sakla:

```python
{
    "attempt_id": str,
    "client_id": str,
    "invoice_id": str,
    "idempotency_key": str,
    "ubl_sha256": str,
    "document_type": "efatura" | "earsiv",
    "provider": str,
    "provider_operation": str,
    "state": "claimed" | "request_started" | "response_received" | "sent" | "failed" | "reconciliation_required",
    "events": list[dict[str, object]],
}
```

- [ ] JSON store'da claim+attempt+`sending` geçişini mevcut process lock içinde
  tek işlem olarak yap.
- [ ] PostgreSQL'de invoice'ı kilitle; unique send-key/attempt'i aynı transaction
  içinde yaz. Unique conflict olursa hata veya yeniden dispatch yerine kazanan
  attempt'i yeniden okuyup döndür.
- [ ] Invoice `sending`, `sent` veya `reconciliation_required` iken farklı key'i
  engelle.
- [ ] Completion sırasında sadece event append et ve son invoice/attempt
  projection'ını güncelle; önceki eventleri değiştirme.
- [ ] JSON, PostgreSQL ve outgoing service testlerini çalıştır.

### Görev 3: Mutating SOAP transport ile read-only retry'ı ayır

**Dosyalar:**
- Değiştir: `backend/app/domain/qnb_efatura.py`
- Değiştir: `backend/app/domain/qnb_earsiv.py`
- Test et: `backend/tests/test_qnb_integration.py`
- Test et: `backend/tests/test_qnb_earsiv.py`

**Arayüzler:**
- Tüketir: `send_outgoing_invoice_ubl()` ve `create_invoice_ubl()`.
- Üretir: Tek-denemeli mutating transport ve typed ambiguous error.

- [ ] Request'i kaydettikten sonra timeout veren fake HTTP client testi yaz;
  genel adapter retry sayısı birden büyük olsa bile `belgeGonderExt` için tek
  POST çıktığını doğrula.
- [ ] Aynı tek-POST timeout testini `faturaOlusturExt` için yaz.
- [ ] Read-only connection/list/download/status metotlarının bounded retry
  testlerini koru.
- [ ] İki QNB test modülünü çalıştır; mutating operasyonların unsafe ortak retry
  yolunu kullandığını doğrula.
- [ ] Mutating operasyonları `_post_soap_once(...)` yoluna ayır. Request başladıktan
  sonraki timeout, connection reset, 429 ve 5xx'i provider wrapper sınırında
  `OutgoingProviderOutcomeUnknown` yap.
- [ ] Her mutating adapter metodunun içine bağımsız test-endpoint guard ekle;
  yalnız CLI veya provider factory kontrolüne güvenme.
- [ ] e-Arşiv `resultCode`/`ok` ve e-Fatura zorunlu OID alanlarını doğrula;
  başarısız/eksik receipt'i `sent` olarak normalize etme.
- [ ] Hedefli adapter testlerini çalıştır.

### Görev 4: Client-kapsamlı fail-closed QNB sandbox routing kur

**Dosyalar:**
- Oluştur: `backend/app/domain/qnb_outgoing.py`
- Değiştir: `backend/app/api/phase0_context.py`
- Değiştir: `backend/app/domain/qnb_earsiv.py`
- Test et: `backend/tests/test_qnb_outgoing.py`
- Test et: `backend/tests/test_outgoing_invoices.py`
- Test et: `backend/tests/test_cors_config.py`

**Arayüzler:**
- Üretir: `build_outgoing_invoice_provider(env, store)`.
- Üretir: `DisabledOutgoingInvoiceProvider`,
  `QnbSandboxOutgoingInvoiceProvider`.
- Tüketir: Mevcut encrypted client-kapsamlı QNB connection store.

- [ ] Missing mode -> disabled, `fake` -> fake, `qnb_sandbox` -> QNB sandbox ve
  diğer değer -> fail-closed factory testlerini yaz.
- [ ] Production endpoint, QNB dışı host, inactive connection, yanlış client
  credential ve supplier VKN/TCKN mismatch için network-free ret testleri yaz.
- [ ] API payload içindeki `provider`, `mode` veya endpoint benzeri alanların
  factory'yi etkileyemediğini kanıtla.
- [ ] Hedefli testleri çalıştır; mevcut context'in implicit fake service
  kurduğunu doğrula.
- [ ] Yalnız server tarafında
  `FISORA_OUTGOING_PROVIDER_MODE=disabled|fake|qnb_sandbox` uygula;
  `qnb_production` ekleme.
- [ ] Credential'ı `invoice.client_id` üzerinden encrypted connection'dan çöz;
  frozen `document_type` ile adapter seç ve bütün test endpointlerini doğrula.
- [ ] `get_outgoing_invoice_service()` içine factory sonucunu enjekte et. Fake
  isteyen unit/API testleri bunu açıkça seçsin.
- [ ] Routing, auth, CORS/config ve outgoing testlerini çalıştır.

### Görev 5: Read-only reconciliation ve API-safe projection ekle

**Dosyalar:**
- Değiştir: `backend/app/domain/qnb_outgoing.py`
- Değiştir: `backend/app/domain/outgoing_invoices.py`
- Değiştir: `backend/app/api/phase0_routes_outgoing_invoices.py`
- Değiştir: `backend/app/api/phase0_schemas.py`
- Değiştir: `backend/app/domain/qnb_efatura.py`
- Değiştir: `backend/app/domain/qnb_earsiv.py`
- Test et: `backend/tests/test_qnb_outgoing.py`
- Test et: `backend/tests/test_outgoing_invoices.py`

**Arayüzler:**
- Üretir: `OutgoingInvoiceService.reconcile(client_id, invoice_id, actor_user_id)`.
- Üretir: accountant/admin rollerine özel
  `POST /outgoing-invoices/{client_id}/drafts/{invoice_id}/reconcile`.

- [ ] Implementasyondan önce güncel QNB WSDL/query metotlarında e-Fatura
  invoice-no/OID ve e-Arşiv transaction-ID/UUID lookup kontratını doğrula; exact
  method ve response identity'yi adapter mapping/test adına yaz.
- [ ] Reconciliation'ın yalnız `reconciliation_required` durumunda, read-only
  çalıştığını ve yalnız pozitif provider kanıtıyla `sent/failed` kapandığını
  kanıtlayan failing testleri yaz.
- [ ] Accountant/admin authorization, client-user reddi, cross-client isolation
  ve safe error projection API testlerini yaz.
- [ ] En güçlü stable provider identity ile belge türüne özgü reconciliation
  uygula. QNB yokluğu kanıtlayamıyorsa `failed` yerine
  `reconciliation_required` durumunu koru.
- [ ] Password, session ID, raw auth payload veya unsanitized SOAP içermeyen
  reconciliation event ve provider snapshot'ları append et.
- [ ] Hedefli provider/service/API testlerini çalıştır.

### Görev 6: Doğrulanmış sandbox kanıtını canonical satış muhasebesine bağla

**Dosyalar:**
- Değiştir: `backend/app/domain/outgoing_invoices.py`
- Değiştir: `backend/app/services/document_service.py`
- Test et: `backend/tests/test_outgoing_invoices.py`
- Test et: `backend/tests/test_phase0_domain.py`
- Test et: `backend/tests/test_normalized_invoice_journal.py`

**Arayüzler:**
- Tüketir: Confirmed `OutgoingProviderReceipt`, frozen UBL/hash ve dönen
  provider evidence.
- Üretir: `invoice_id` ve `attempt_id` ile bağlı tek canonical sales invoice.

- [ ] Tek storage/job seam olarak `DocumentService.store_document_upload(...)`
  kullan. Confirmed UBL byte'larını, exact SHA-256'yı, `einvoice_xml`,
  `sales_invoice` ve authorized actor olarak onaylayan müşaviri aktar; outgoing
  domain içinde storage/enqueue mantığını kopyalama.
- [ ] Confirmed QNB UBL'nin exact party, direction, line, KDV, total, source
  hash, invoice ID ve attempt ID ile canonical sales invoice olduğunu kanıtlayan
  failing test yaz.
- [ ] Eksik canonical satır veya gerçek hesap planı bağlamında hesap
  uydurulmadığını ve export-ready olunmadığını kanıtlayan insufficient-evidence
  testi yaz.
- [ ] Gerçek direction-filtered hesap planı sağlandığında her borç/alacak
  tutarını canonical satır/KDV/toplama bağlayan balanced journal testi yaz.
- [ ] Confirmed receipt'i mevcut document/canonical pipeline'a ver; provider
  delivery, müşavir review ve export readiness durumlarını ayrı tut.
- [ ] Sonraki iptal/status kanıtının onaylı/export edilmiş muhasebe işini
  sessizce silmesini veya otomatik ters çevirmesini engelle.
- [ ] Outgoing, canonical, normalized journal, review ve export testlerini
  çalıştır.

### Görev 7: Kontrollü gerçek QNB sandbox kabulünü yürüt

**Dosyalar:**
- Değiştir: `backend/scripts/run_qnb_earsiv_sandbox_smoke.py`
- Değiştir: `backend/scripts/send_qnb_sandbox_invoice.py`
- Oluştur: `backend/scripts/run_qnb_outgoing_service_sandbox_acceptance.py`
- Test et: `backend/tests/test_qnb_outgoing.py`
- Test et: `backend/tests/test_qnb_earsiv.py`
- Test et: `backend/tests/test_qnb_integration.py`

**Arayüzler:**
- Üretir: e-Fatura/e-Arşiv ortak-servis kabulü için secret-safe JSON özet.
- Zorunlu: Açık `--confirm-send`; bütün non-test endpointleri reddeder.

- [ ] `--confirm-send` yokken yalnız gönderim planı basıldığını ve sıfır mutating
  çağrı yapıldığını; non-test endpointte network öncesi nonzero exit olduğunu
  kanıtlayan script testlerini yaz.
- [ ] Fake transport ile forced post-submit-timeout acceptance modu yaz: tek
  mutating request, `reconciliation_required`, sıfır resend.
- [ ] Acceptance scriptini adapter'ı doğrudan çağırmadan
  `OutgoingInvoiceService` ve gerçek provider factory üzerinden uygula.
- [ ] Plan-only çalıştır; secret basmadan exact taraflar, VKN/TCKN, belge türü,
  numara/seri, toplam, endpoint ve output pathleri gözden geçir.
- [ ] Harici sandbox side effect için kullanıcıya exact kapsamı açıklayıp onay
  aldıktan sonra kontrollü tek TEST2 -> TEST1 e-Fatura gönder; OID/status'u al,
  incoming sync ile geri çek ve duplicate korumasını kanıtla.
- [ ] Aynı açıklanmış onay sınırında kontrollü tek e-Arşiv sandbox faturası
  oluştur; result code, transaction ID, UUID, invoice no, dönen UBL/PDF hash ve
  status'u sakla.
- [ ] Doğrulanmış sandbox kontratı güvenli iptali destekliyorsa yalnız bu test
  e-Arşiv belgesini iptal edip snapshot'ı sakla; desteklemiyorsa iptali açıkça
  kanıtlanmamış non-production madde olarak kaydet.
- [ ] Raw/private artifact'leri yalnız ignored output pathlerde sakla. Yalnız
  test, kod ve redacted summary template commit kapsamına girebilir.

### Görev 8: Doğrulama, readiness gerçeği ve süreklilik

**Dosyalar:**
- Değiştir: `docs/superpowers/plans/2026-07-10-qnb-end-to-end-integration.md`
- Değiştir: `docs/current-handoff.md`
- Değiştir: `backend/README.md`
- Değiştir: `docs/product-plan/00-canonical-decision-register.md`

**Arayüzler:**
- Üretir: Sandbox hazırlığını production hazırlığından ayıran secret-safe kabul
  ifadesi.

- [ ] Hedefli proof setini çalıştır:

```powershell
python -m unittest backend.tests.test_outgoing_invoices backend.tests.test_qnb_outgoing backend.tests.test_qnb_integration backend.tests.test_qnb_earsiv
```

- [ ] Stable tam yerel proof setini çalıştır:

```powershell
python -m unittest discover -s backend/tests
node --test frontend/app/*.test.cjs
Push-Location frontend
npm.cmd run build
Pop-Location
git diff --check
```

- [ ] Sıfır failure iste. Skip edilen PostgreSQL testlerini listele ve atomik
  concurrency kabulü iddia etmeden önce isolated gerçek PostgreSQL smoke
  ortamında çalıştır.
- [ ] Gerçek sandbox kanıtını incele: frozen/sent/returned hash eşitliği, QNB
  kimlikleri, status snapshot, tek-request timeout kanıtı, duplicate koruması,
  tenant isolation ve secret-free loglar.
- [ ] Ana QNB planı ile handoff'a yalnız doğrulanmış gerçekleri yaz. e-Fatura ve
  e-Arşiv common-service kapıları geçmeden `QNB giden fatura sandbox
  doğrulandı; production gönderimi kapalı` ifadesini kullanma.
- [ ] Canonical decision register'a settled sınırı yaz: bu dilim sandbox
  hazırlığını kanıtlar; production fatura kesme veya kullanıcıya açık send UI
  sağlamaz.
- [ ] Intentional diff ve generated summary üzerinde final secret scan yap;
  `.env.qnb.local`, raw UBL/PDF, password, session token veya kişisel müşteri
  verisini stage etme.
- [ ] `git status --short` ile final kapsamı incele ve ilgisiz kullanıcı
  değişikliklerini koru. Ayrı release preflight/onayı olmadan commit, push veya
  deploy yapma.
