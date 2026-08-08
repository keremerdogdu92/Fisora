# Current Handoff

### 2026-08-09 tax component accounting domain ve Gemini native PDF provider yayını (canlı)

- `main` runtime release commit'i `b340738` canlıya alındı.
- Sunucu checkout'u (`/opt/fisora/app`), `origin/main` ve yerel `main` birebir eşleşti (`b340738`).
- Canlı doğrulama: HTTPS `/health` `200` (`status: ok`), `/api/phase0/store/system/readiness` `200` (`ready=true`, `pilot_sellable=true`).
- Yayınlanan değişiklikler: Vergisel bileşen muhasebeleştirme etki analiz motoru (`tax_component_accounting.py`), Gemini native PDF extraction provider entegrasyonu, UBL/XML ve PDF fatura vergi bileşenleri ayrıştırma kurgusu ve ilgili unit testler (`test_tax_components.py`) `main` dalına dahil edilip canlıya dağıtıldı.
- Sürüm öncesi backend `776` test (23 skipped DSN-gated), frontend `170` test, Next.js production build ve `git diff --check` başarıyla tamamlandı.

### 2026-08-01 accountant-first client onboarding frontend değişiklikleri yayını (canlı)

- `main` runtime release commit'i `4e83de8` (feat commit `8012955` dahil) canlıya alındı.
- Sunucu checkout'u (`/opt/fisora/app`), `origin/main` ve yerel `main` birebir eşleşti (`4e83de8`).
- Canlı doğrulama: HTTPS `/health` `200` (`status: ok`), `/api/phase0/store/system/readiness` `200` (`ready=true`, `pilot_sellable=true`).
- Yayınlanan değişiklikler: Mükellef oluşturma ve onboarding akışında geçici şifre zorunluluğu kaldırıldı (`portal-clients-view.tsx`, `use-client-management-commands.ts`, `portal-client-actions.ts`, `upload-api.js`, `upload-api.test.cjs`), mükellef davet linki ve mükellefin kendi şifresini belirleme akışı birincil hale getirildi.
- Sürüm öncesi backend `737` test, frontend `170` test, Next.js production build ve `git diff --check` başarıyla tamamlandı.

### 2026-08-01 accountant-first client onboarding dokümantasyonu yayını (canlı)

- `main` runtime release commit'i `1c51239` canlıya alındı.
- Sunucu checkout'u (`/opt/fisora/app`), `origin/main` ve yerel `main` birebir eşleşti (`1c51239`).
- Canlı doğrulama: HTTPS `/health` `200` (`status: ok`), `/api/phase0/store/system/readiness` `200` (`ready=true`, `pilot_sellable=true`).
- Yayınlanan değişiklikler: Müşavir odaklı mükellef onboarding tasarım şartnamesi (`2026-08-01-accountant-first-client-onboarding-design.md`) ve uygulama planı (`2026-08-01-accountant-first-client-onboarding.md`) repoya eklendi ve canlıya dağıtıldı.
- Preflight ve release öncesi backend `737` test, frontend `169` test, Next.js production build ve `git diff --check` başarıyla tamamlandı.

### 2026-08-01 utility provider fast lane ve ogrenme kurallari entegrasyonu (canli)

- `main` runtime release commit'i `3816d93` canlıya alındı.
- Sunucu checkout'u (`/opt/fisora/app`), `origin/main` ve yerel `main` birebir eşleşti (`3816d93`).
- Izole yan çalışma ağacı (`codex/utility-provider-fast-lane`) `main` dalına sorunsuz birleştirildi ve yan worktree/dal temizlendi.
- Canlı doğrulama: HTTPS `/health` `200` (`status: ok`), `/api/phase0/store/system/readiness` `200` (`ready=true`, `pilot_sellable=true`).
- Yayınlanan değişiklikler: Dağıtıcı kurum/abonelik faturaları hızlı şeridi (`provider_directory.v1.json`, `utility_invoice_markers.py`, `provider_directory.py`), hızlı KDV/muhasebe eşleme mantığı ve ilgili 16 yeni backend testi `main` dalına dahil edildi.
- Preflight ve release öncesi backend `737` test, frontend `169` test, Next.js production build ve `git diff --check` başarıyla tamamlandı.

### 2026-08-01 reference corpus pilot script ve design QA raporu yayını (canlı)

- `main` runtime release commit'i `8009ffc` canlıya alındı.
- Sunucu checkout'u (`/opt/fisora/app`), `origin/main` ve yerel `main` birebir eşleşti (`8009ffc`).
- Docker servisleri ve web sunucusu başarıyla aktif durumda.
- Canlı doğrulama: HTTPS `/health` `200` (`status: ok`), `/api/phase0/store/system/readiness` `200` (`ready=true`, `pilot_sellable=true`).
- Yayınlanan değişiklikler: İzole referans korpus pilot betiği (`run_reference_corpus_pilot.py`) ve Müşavir Çalışma Alanı Design QA inceleme raporu (`design-qa.md`) repoya eklendi ve canlıya dağıtıldı.
- Sürüm öncesi backend `721` test, frontend `169` test, Next.js production build ve `git diff --check` başarıyla tamamlandı.

### 2026-07-31 VAT-grouped invoice draft repair ve corpus admission gelistirmeleri (canli)

- `main` runtime release commit'i `4a748e2` canlıya alındı.
- Sunucu checkout'u (`/opt/fisora/app`), `origin/main` ve yerel `main` birebir eşleşti (`4a748e2`).
- Docker servisleri (`backend`, `frontend`, `postgres`, `redis`, `qnb-scheduler`, `worker`) başarıyla başlatıldı ve `healthy` durumda.
- Canlı doğrulama: HTTPS `/health` `200` (`status: ok`), `/api/phase0/store/system/readiness` `200` (`ready=true`, `pilot_sellable=true`).
- Yayınlanan değişiklikler: KDV gruplamalı alış faturaları taslak fiş hattında tutar dağıtımı düzeltildi, referans corpus kabul betikleri ve testleri güncellendi.
- Preflight ve release öncesi backend `721` test, frontend `169` test, Next.js production build ve `git diff --check` başarıyla tamamlandı.

### 2026-07-30 accountant review UI repair and live quality audit (live)

- `main` runtime release commit `1dec1e3` is live on
  `185.184.208.188`. Server checkout, `origin/main`, and local `main` matched
  after deploy; backend/frontend/PostgreSQL/Redis/QNB scheduler were healthy,
  `/health` returned `200`, and system readiness returned `ready=true` and
  `pilot_sellable=true`.
- The release repaired session guarding, removed the duplicate header login
  shortcuts, restored the accountant workspace review data request, and made
  missing generated `120/320` counterparty accounts an amber new-counterparty
  notice while keeping genuinely missing chart accounts blocking/red.
- The release wrapper itself returned a false-negative after deployment because
  its remote smoke/readiness JSON parser received non-JSON output. Deployment
  success was verified independently from commit parity, containers, and HTTP
  endpoints. The wrapper parsing defect remains open.
- The live 50-document baseline is still `19 completed / 31 failed`. The 19
  completed Cansu documents are all balanced, canonical-valid, amount
  reconciled, and use non-counterparty accounts present in the 629-code chart.
  All require a new `120/320` counterparty; 18 have valid canonical line
  allocation and one is `ai_correction_required`.
- Semantic correctness is not yet an accepted quality result. Five zero-VAT
  exemption sales were mapped to `600.01.020` and correctly held for direction
  review; one off-activity clothing purchase produced a gross
  `153.01.001` draft and was held for AI correction/account mismatch. These
  must be decided by the accountant before measuring account-choice accuracy.
- The 31 failed jobs still hit
  `normalized journal requires populated draft lines` (`12` XML and `19` PDF).
  Their pipeline events show that extraction/AI can finish, but normalized
  persistence rejects an intentionally empty draft instead of preserving an
  accountant-visible `insufficient-evidence/review_required` result. The UI
  consequently reports the misleading terminal step `parser_failed`.
- `review_decisions=0`, `learning_rules=0`, and
  `protected_corpus_items=0`; therefore accountant-learning quality is not yet
  measurable. The next primary engineering task is to persist empty-draft
  review cases safely, reprocess the 31 failures, and then collect accountant
  decisions across all 50 documents.

### 2026-07-29 protected 50-invoice live baseline and semantic research repair (live)

- `main` runtime release commit `e06addc` is live. The release wrapper reported
  `before_commit=d4266ee`, `after_commit=e06addc`, HTTPS root/health/readiness
  `200`, `ready=true`, and `pilot_sellable=true`.
- Research no longer creates a second accounting authority when an initial
  semantic decision is already accepted. It appends
  `research_evidence_collection` evidence instead; research synthesis remains
  available when the initial decision was not accepted. The regression was
  reproduced before the fix, then the targeted scenarios and the full backend
  suite passed (`667 OK`, `19` DSN-gated skips).
- The Cansu + Arif 35-purchase/15-sales source set completed its first live
  processing pass: `19 completed`, `31 failed`, with no remaining queued or
  processing jobs. All 19 completed documents belong to Cansu. The failures are
  Cansu `12` and Arif `19`; every failure is
  `normalized journal requires populated draft lines`. The previous
  `multiple accepted unsuperseded semantic attempts` error is absent after the
  release. The worker remains running.
- The empty-draft condition is now the next product/runtime blocker. Canonical
  evidence and AI/review diagnostics exist, but normalized persistence turns an
  empty draft into a failed job instead of preserving an accountant-visible
  insufficient-evidence/review-required result. Do not treat the 50-document
  baseline or accountant-learning measurement as complete until this behavior
  is resolved and the failed documents are reprocessed.
- Protected corpus `8c302dec-7c47-411d-8b9c-b553bf7bfe8e` exists in `draft`
  state with targets `35 purchase + 15 sales`, but
  `protected_corpus_items=0`. No accountant reference outcome or learning rule
  has been created. Source uploads remain available; corpus admission/freeze
  must be completed only after the processing and tenant/source mappings are
  verified.
- A separate operational defect remains: there is no total document-level
  deadline across provider fallbacks, so slow PDF/provider calls can occupy a
  worker thread for several minutes. This did not prevent the current queue
  from reaching a terminal state but remains open.

### 2026-07-29 normalized 50-invoice pilot foundation, learning rules, period retention ve canlı deploy (canlı)

- `main` branch runtime release commit'i `5bf3db1` canlıya alındı.
- Release wrapper `before_commit=d026345`, `after_commit=5bf3db1`, `smoke=ok`, `ready=true` ve `pilot_sellable=true` döndü.
- Öğrenme kuralları yaşam döngüsü (`008_learning_rule_lifecycle.sql`), fiş düzenleme iş birliği kilitleri (`009_journal_edit_collaboration.sql`), dönem muhafazası (`007_period_retention.sql`) ve AI kesinti/retry altyapısı (`010_ai_outage_retry.sql`) canlı veritabanında doğrulandı.
- Deploy öncesi backend `665` test (`19` skipped DSN-gated), frontend `159/159` test, Next.js production build ve `git diff --check` başarıyla doğrulandı.

### 2026-07-25 QNB gelen fatura güvenliği, scheduler readiness ve canlı deploy (canlı)

- `main` branch runtime release commit'i `4d5d950` canlıya alındı.
- Release wrapper `before_commit=25d9e39`, `after_commit=4d5d950`, `smoke=ok`, `/health` 200, readiness 200, root route 200, `ready=true` ve `pilot_sellable=true` döndü.
- `006_qnb_incoming_safety.sql` migrasyonu, `qnb-scheduler` background worker'ı ve Nginx varsayılan yapılandırması canlı ortamda doğrulandı.
- Deploy öncesi backend `618` test (`15` skipped DSN-gated), frontend `147/147` test ve `git diff --check` başarıyla doğrulandı.

### 2026-07-23 yedekleme yaşam döngüsü (yerel)

- Pilot öncesinde `FISORA_BACKUP_MODE=disabled` varsayılandır. Backup Compose
  profile'ı başlamaz, yeni dump üretmez ve readiness bu aşamayı
  `not_required` sayar. Protected corpus freeze sonrasında tek seferlik
  `checkpoint`; ilk gerçek pilot faturası öncesinde ise günlük `scheduled`
  moda geçilir.
- Checkpoint paketi PostgreSQL, protected-corpus byte'ları, metadata ve
  `SHA256SUMS` içerir; geçici normal PDF/XML belgelerini içermez. Scheduled
  paket bunlara ek olarak aktif belge root'undaki normal PDF/XML byte'larını da
  taşır. Generation public `age` recipient ile şifrelenir; success receipt
  yalnızca atomik off-host copy tamamlandıktan sonra oluşur.
- Readiness artık yerel bir SQL dosyasını başarı saymaz. Güncel şifreli
  generation, digest, tamamlanmış off-host copy ve aynı generation/digest için
  güncel izole restore receipt'i gerekir. Ayrıca kod bind mount'un fiziksel
  yerini kanıtlayamadığı için `FISORA_BACKUP_OFFHOST_ATTESTED=true` operatör
  teyidi yoksa aynı-sunucu false-positive'i `offhost_target_unattested` ile
  bloklar.
- Sentetik Docker kanıtında checkpoint paketi normal belgeleri dışarıda bıraktı;
  scheduled paket PDF/XML byte'larını içerdi. Paket decrypt/hash/protected-byte
  açılımı ve PostgreSQL dump'ın izole DB'ye restore'u geçti. Geçersiz recipient
  koşusunda success receipt veya partial `.tmp` kalmadı. Gerçek PostgreSQL 16
  üzerinde DSN-gated protected-corpus testi ayrıca `1/1` geçti.
- Son tam yerel kanıt: backend `566 OK (skipped=20)`, frontend `147/147`,
  Next.js production build, Compose default/profile service listesi, Compose
  config, iki shell syntax kontrolü ve `git diff --check` başarılıdır.
- Çalışma `codex/backup-lifecycle` branch'inde
  `C:\Users\kerem\Documents\Fisero\.worktrees\backup-lifecycle` worktree'inde
  tutuluyor. Commit, push, deploy ve canlı cleanup yapılmadı. Canlı checkout
  halen `935a1fa`; backup restart döngüsü ile mevcut 1321 yerel dump, release
  ve ayrıca kapsamı gösterilmiş cleanup onayı verilene kadar değişmeden duruyor.

### 2026-07-23 NVIDIA, Cloudflare ve SambaNova provider release'i (canli)

- `main` runtime release commit'i `9159152` olarak canliya alindi.
  Release wrapper `before_commit=384ebac`, `after_commit=9159152`,
  `smoke=ok`, `/health` 200, readiness 200, root route 200,
  `ready=true` ve `pilot_sellable=true` dondu.
- Canli muhasebe provider sirasi
  `nvidia,groq,cerebras,cloudflare,sambanova,openrouter` olarak
  yapilandirildi. NVIDIA sirasi ve davranisi degistirilmedi; yeni benchmark
  release kapisi eklenmedi.
- NVIDIA, Cloudflare ve SambaNova anahtarlari yalniz ignored
  `/opt/fisora/app/deploy/production.env` dosyasina aktarildi. Dosya modu
  `600` olarak korundu ve degisiklikten once
  `production.env.before-ai-providers-20260723T101322Z` yedegi alindi.
- Canli zincir smoke'unda NVIDIA yaklasik 60 saniyede timeout olduktan sonra
  Groq devraldi; sentetik bilgisayar satirini `computer_equipment`, guven `95`
  olarak dondurdu. Tek cagrilik dogrudan smoke'larda Cloudflare 8.45 saniyede
  guven `90`, SambaNova 1.62 saniyede guven `95` ile ayni kategoriyi dondurdu.
- Release oncesi backend `550` test ile basarili (`13` skip), frontend
  `147/147` basarili, Next.js production build, Compose config ve
  `git diff --check` basariliydi.
- Server checkout'unda bu release'ten once bulunan
  `deploy/nginx/default.conf` degisikligi ile
  `deploy/nginx/default.conf.before-ui-prototype-20260714` dosyasi korundu;
  provider release'i bu nginx kapsamına dokunmadi.

### 2026-07-21 protected accountant-reference corpus (yerel)

- Migration `005_protected_accountant_reference_corpus.sql` ile tenant-scope
  `protected_corpora`, hash-unique `protected_corpus_items`, append-only
  `reference_outcome_versions` ve yalniz acik musavir onayindan dogan
  `protected_rule_versions` eklendi. Repository hem compatibility hem normalized
  PostgreSQL modunda baglidir; JSON store yalniz local/API contract parity'sidir.
- Corpus'a alinan kaynak dosya normal document/export root'larindan ayri
  `FISORA_PROTECTED_CORPUS_PATH` volume'una atomik kopyalanir ve SHA-256 ile
  dogrulanir. Normal `TEMIZLE` operasyonel musteri, belge, review ve learning
  state'ini silerken korumali corpus/item/reference/rule tablolari ile bu
  source byte'larini korur. Accountant/admin reset preview endpoint'i silinecek
  ve korunacak sayilari islemden once gosterir.
- Mevcut review kayit akisi degismedi: yalniz corpus'a onceden alinmis belge
  review edilince proposal/final/journal/allocation/provenance snapshot'i yeni
  reference version olarak eklenir. Onceki version degismez. Kural ancak mevcut
  `learning_confirmation=save_rule` ve `source=accountant_confirmed` sozlesmesi
  birlikte saglanirsa korunur.
- Freeze kapisi tam alis/satis hedef sayisini, authoritative referansi, dengeli
  journal'i, canonical line allocation coverage'ini ve protected byte hash'ini
  zorunlu tutar. Frozen corpus yeni item/reference/rule kabul etmez. Private
  benchmark `--corpus-id` ile yalniz frozen snapshot digestlerini read-only
  girdi olarak cikartabilir.
- Production compose'da korumali byte'lar ayri volume'dadir. Backup image'i
  PostgreSQL dump + gercek protected source archive + SHA manifest uretir;
  off-host hedefe yalniz public age recipient ile sifrelenmis paket kopyalar.
  Izole restore verifier source hash, monoton reference versionlari, dengeli
  authoritative journal, rule-reference bagi ve tenant bagini kontrol eder.
- Yerel gercek PostgreSQL 16 kaniti: temiz `001-005` migration, tekrar kosuda
  `No pending migrations`, ayri DB'de `001-004 -> 005` upgrade, iki reference +
  bir confirmed rule ve reset-sonrasi preservation basarili. Encrypted paket
  ayri DB/root'a restore edildi; verifier sekiz kontrolun tamaminda `true` dondu.
- Son tam local proof: backend `541 OK (skipped=13; 13 test DSN-gated)`,
  frontend `147/147`, Next production build, compose config, backup shell syntax
  ve `git diff --check` basarili. DSN-gated protected-corpus testi ayrica gercek
  PostgreSQL 16 uzerinde `1/1` gecti; genisletilmis restore verifier sekiz
  kontrolun tamaminda `true` dondu.
- Gercek 35 alis + 15 satis UBL corpus'u henuz yuklenmedi ve musavir reference
  parity sonucu yoktur; Phase 2 quality exit gate aciktir. Bu degisiklikler
  local dirty `main` uzerindedir; commit, push, deploy, production reset veya
  gercek fatura upload'i yapilmadi.

### 2026-07-21 QNB giden fatura ortak servis sandbox hazirligi (yerel)

- Calisma `codex/qnb-outgoing-sandbox` yan worktree'sindedir; commit, push veya
  deploy yapilmadi. Kullanici onayli sandbox kabul cagrilari asagida kayitli.
- Outgoing runtime varsayilani `disabled` oldu. `fake` ve `qnb_sandbox` yalniz
  server env ile acilir; request payload'i provider/endpoint secemez.
- Frozen UBL SHA-256 gonderim oncesi yeniden dogrulanir. Client-kapsamli
  idempotency claim, send attempt ve `sending` gecisi JSON/PostgreSQL hattinda
  tek islem olarak kaydedilir; attempt olaylari append-only izdir.
- `belgeGonderExt` ve `faturaOlusturExt` otomatik retry edilmez. Post-submit
  timeout/transport belirsizligi `reconciliation_required` olur ve yeni key
  dahil ikinci mutating gonderimi engeller.
- Uzlastirma atomik owner/lease claim'i kullanir. Aktif uzlastirma ikinci
  calisana verilmez; process cokmesinden kalan `request_started` denemesi ancak
  stale esigi gectikten sonra salt-okunur uzlastirmayla devralinabilir.
- QNB sandbox provider aktif client connection, encrypted credential, test
  endpoint ve supplier VKN/TCKN eslesmesini zorunlu tutar. e-Fatura yerel belge
  no, e-Arsiv provider fatura UUID/no ile salt-okunur mutabakat yapar.
- Pozitif QNB receipt ile dogrulanan UBL ayni byte/hash ve attempt bagiyla
  mevcut `einvoice_xml` + `sales_invoice` document processing hattina girer.
  Provider teslimi musavir review veya export-ready durumunu atlamaz.
- Yeni kabul araci ortak `OutgoingInvoiceService` ve provider factory yolunu
  kullanir. Plan-only kosular `sent=false` ile basariliydi; gercek kabul sonucu
  ve acik provider kapilari asagidadir.
- Son proof: backend `554 OK (skipped=19)`, frontend `147/147`, Next production
  build ve `git diff --check` basarili. Bagimsiz son engineering review'da
  kalan P0/P1 bulgu yok. Gercek PostgreSQL concurrency smoke'u bu worktree'de
  `DATABASE_URL` bulunmadigi icin calistirilmadi; PostgreSQL atomiklik kabul
  kaniti bu DSN-gated kosu tamamlanana kadar acik kapidir.
- 2026-07-21 kullanici onayli gercek sandbox kabulunde e-Fatura, TEST1
  `userService/wsLogin` HTTP 500 verdigi icin etiket preflight'inda durdu;
  `belgeGonderExt`, UBL, attempt veya QNB belgesi olusmadi. TEST2 login/etiket
  sorgusu ayni anda basariliydi. TEST1 WS credential/hesap aktivasyonu dis
  bagimlilik olarak acik.
- Tek e-Arsiv `faturaOlusturExt` cagrisi QNB tarafindan kesin `AE00001` ile
  reddedildi; otomatik veya manuel resend yapilmadi. Salt-okunur, fatura no
  tabanli `faturaSorgulaExt` `AE00002` ile belgenin sistemde kayitli olmadigini
  dogruladi. Portal mali muhur/e-imza dogrulamasi ve ayri WS kullanicisi kapisi
  acik kalmaya devam ediyor.
- Canli sorgu kaniti `faturaSorgulaExt` input'unun `islemId` degil
  `faturaUuid` veya `faturaNo` istedigini gosterdi. Adapter ve reconciliation
  bu provider kimliklerine duzeltildi; QNB `resultText` artik secret-safe hata
  kanitinda korunuyor. Hedefli QNB proof `55 OK`.

### 2026-07-20 AI semantic authority pipeline repair (yerel)

- Cold-start muhasebe karari static kategori guveniyle atlanmiyor. Semantic
  hesap yetkisi yalniz exact canonical satir kapsamli accepted AI attempt veya
  provenance'i dogrulanmis typed rule authority'den gelebiliyor.
- Deterministic katman hesap secmiyor; canonical net/KDV tutari, yon, denge,
  hard-rule review/export kapilari ve revision guvenligini uyguluyor. Accepted
  hesap kodu ordinary, mixed-VAT, return ve non-deductible akislarda korunuyor.
- Gecersiz schema veya aday disi hesap bir kez `account_correction` asamasina
  gidiyor. Ilk hata ve duzeltme attempt'i append-only saklaniyor; basarisizlikta
  generic deterministic hesap substitution yapilmiyor.
- Research evidence-only sinirinda: canonical satir scope'u, gercek claim,
  kaynak domaini, expiry ve privacy sanitization zorunlu. Provider category,
  treatment, confidence veya accountant override yetkisi uretemiyor.
- Research profilleri opaque `profile_id`, client scope ve revision tasiyor.
  JSON/PostgreSQL store lookup/list scope'u data-access katmaninda uyguluyor;
  accountant override expected revision ile atomik guncelleniyor, provider
  evidence korunuyor ve audit olayi yaziliyor.
- Yerel private baseline butun `firma-*` klasorlerini raporladi: firma-1 icin
  15, firma-2 icin 13 PDF bulundu; firma-3..7 dogrulanmis client profile eksigi
  nedeniyle tahmin yapilmadan bloke edildi. Bu kosu AI/research credentials
  olmadan yapildigi icin provider kalite kabul kaniti degildir.
- Son yerel proof: backend `523 OK (skipped=12)`, frontend `147/147`, Next
  production build ve `git diff --check` basarili. Skip edilen 12 test gercek
  PostgreSQL DSN gerektirir.
- Acik kabul kapilari: gercek provider credentials ile Yurtiçi 5/5 ve Muson
  regression'i; ayrica versioned 35 alis + 15 satis corpusunun musavir referans
  parity sonucu. Bunlar olmadan Phase 2 muhasebe kalitesi tamamlandi denmiyor.
- Calisma local dirty `main` uzerindedir; commit, push veya deploy yapilmadi.

### 2026-07-20 PDF discovery ve task-aware AI routing (yerel)

- UBL/XML canonical kaynak onceligi korunarak text-readable PDF canonical AI
  extraction `repair` ve `discovery` modlarina ayrildi.
- Discovery yalniz missing/tutarsiz deterministic satir halinde calisir;
  duplicate kaynak konumu reddedilir ve canonical line ID sunucuda uretilir.
- Canonical, classification ve counterparty gorevleri base chain icindeki
  provider'lari goreve gore siralar; statement zinciri base sirayi korur.
- Hedefli PDF/routing testleri, Phase0 (191), normalized journal (17),
  workflow-store/routing (52), tam backend (463; 9 skipped), frontend (145) ve
  production build yerelde gecti.
- Image-only/scanned PDF OCR ve gercek 50-fatura provider kalite/latency
  benchmark'i bu yerel dilimin disinda, acik kabul maddesidir.

Bu dosya, Fisora kapali server demo calismasina baska bilgisayardan veya baska
oturumdan devam etmek icin son durumu ozetler.

## Son Durum

### 2026-07-18 canonical Phase 1 normalized vertical slice (yerel)

- Canonical `docs/product-plan/01-product-requirements-document.md`,
  `02-system-architecture-document.md` ve `03-development-roadmap.md`
  dogrultusunda Phase 1'in ilk complete alis-faturasi vertical slice'i
  uygulandi. Bu calisma local `main` worktree'dedir; commit/push/deploy
  yapilmadi.
- `003_normalized_invoice_journal_slice.sql` ile immutable `source_files`,
  `document_sources`, canonical invoice line alanlari, normalized
  `processing_jobs`/`processing_attempts`, `ai_attempts`,
  `journal_revisions`/`journal_revision_lines`, append-only
  `workflow_events` ve approved revision'a bagli export item altyapisi eklendi.
- PostgreSQL normalized repository su zinciri sahipleniyor:
  kaynak hash'i ve dedup -> canonical fatura/satir -> dengeli journal draft
  revision -> `expected_revision` kontrollu review/onay -> authoritative
  approved revision export projection -> neden zorunlu reopen ile yeni
  working revision. Reopen onceki approved snapshot'i degistirmiyor.
- Worker queue claim'i `FOR UPDATE SKIP LOCKED` ile normalized
  `processing_jobs` tablosundan yapiliyor; her claim icin durable attempt
  aciliyor ve completion/error/metrics ayni normalized hatta kapaniyor.
- Mevcut Faturalar sayfasi yeniden tasarlanmadi. Workspace JSON sekli
  compatibility projection olarak korunuyor; frontend mevcut belge modelinde
  normalized revision numarasini tasiyor ve review POST'unda
  `expected_revision` gonderiyor. Eski sekme/yeni revision cakismasi backend'de
  `409 journal_revision_conflict` donuyor.
- Gelistirme cutover anahtari:
  `FISORA_STORE_BACKEND=postgres` ve
  `FISORA_ACCOUNTING_STORE_TARGET=normalized`. Varsayilan hedef bilincli olarak
  `compatibility`; bu local dilim deploy edilip gercek PostgreSQL migration ve
  kontrollu XML smoke'u yapilmadan production kendiliginden kesilmez.
- Yeni regression:
  `backend/tests/test_normalized_invoice_journal.py`. Tek alis faturasi icin
  duplicate kaynagin ayni authoritative belge/job'a donmesi, revision
  `1 draft -> 2 approved -> 3 reopened`, approved snapshot immutability,
  stale revision reddi ve export'un normalized approved projection'dan gelmesi
  kanitlandi.
- 2026-07-18 yerel kanit:
  backend `415/415`, frontend `145/145`, Next production build basarili,
  migration dry-run `001/002/003`, `git diff --check` temiz.
- Docker Desktop daemon'i yeniden dogrulandi. Izole `postgres:16` container'inda
  migration `001/002/003` gercek veritabanina uygulandi; `source_files`,
  `journal_revisions` ve `workflow_events` tablolarinin olustugu SQL ile
  dogrulandi.
- Ayni izole PostgreSQL'de gercek tek satirli, yuzde 20 KDV'li alis UBL'si
  normal upload -> normalized queue claim/attempt -> worker -> review/onay ->
  authoritative export -> reopen hattindan gecti. Worker sonucu `1 completed /
  0 failed`, export entry sayisi `1`; relational sayim source/document/
  canonical-line/attempt/revision/approved-revision/event icin
  `1/1/1/1/3/1/4` dondu. Revision zinciri
  `1 review_required -> 2 approved -> 3 working_draft`; revision 2 snapshot'i
  reopen sonrasi korundu.
- Ayni kaynak hash'iyle ikinci intake gercek PostgreSQL'de
  `deduplicated=true` dondu; `source_files/documents/processing_jobs/
  journal_entries` sayilari `1/1/1/1` kaldi. Izole smoke container'i kanit
  alindiktan sonra temizlendi.
- Kullaniciya ait `frontend/next-env.d.ts` degisikligi korundu.
  `.codebase-memory/` generated untracked graph artefakti kapsama alinmadi.

### 2026-07-18 canonical Phase 2 accounting-quality core (yerel)

- Roadmap Phase 2'nin canonical satir ve muhasebe-quality cekirdegi Phase 1
  normalized vertical slice uzerine uygulandi. Calisma local `main`
  worktree'dedir; commit/push/deploy yapilmadi ve production cutover anahtari
  `compatibility` olarak kalir.
- XML satirlari UBL `InvoiceLine/ID`, PDF satirlari kaynak satir/tablo konumu
  uzerinden deterministic `canonical_line_id` tasir. Parser sirasi degisse bile
  kimlik ayni kalir. Canonical satir yeniden islenince silinmez; ayni fingerprint
  reuse edilir, degisen extraction yeni version acar ve eski version
  `superseded_at` ile tarihsel revision lineage'inda korunur.
- AI veya deterministic line kararlarinda exact ID coverage zorunludur. Eksik,
  duplicate veya unknown ID `canonical_line_decision_incomplete` olarak
  review-only kalir. PDF AI extraction provider locator'ini authoritative kabul
  etmez; server-generated ID ve locator'lar modele verilir ve exact echo coverage
  dogrulanir. AI trace artik ilgili normalized processing attempt'e baglanir.
- `journal_line_allocations` tablosu canonical satir net/KDV/brut tutarini
  revision satirina ve hesaba relational olarak baglar. Allocation mutabakati
  eksikse dolu ve dengeli taslak korunur fakat approval/export acilmaz. Net
  allocation karar hesabina, KDV allocation canonical oranina birebir baglidir;
  heterojen AI kararlarinda net tutarlar hesap bazinda gruplanarak dolu fiş
  uretilir.
- Normalized persistence purchase yaninda sales ve return direction'larini da
  sahiplenir. UBL iade faturasi varsa `BillingReference /
  InvoiceDocumentReference` belge no/tarih kanitini canonical header ve
  normalized document uzerinde korur. Dogrulanmamis ozel vergi davranisi
  otomatik politika uretmez; focused review sinirinda kalir.
- Approval artik istemci header toplamlarina guvenmez: journal satirlarini
  server-side yeniden toplar; negatif, iki tarafli veya bos satiri reddeder;
  canonical validation, exact line coverage, allocation mutabakati ve ilgili
  mukellefin aktif detay hesaplarini kontrol eder. Yeni `120/320` onerisi
  gercek hesap planinda olusmadan export-ready sayilmaz.
- Taxpayer UUID tenant kapsamli hale geldi. Review/reopen audit actor'u serbest
  payload metni yerine authenticated user/session kimliginden gelir.
- Normalized queue expired lease'i reclaim eder, her claim'i immutable attempt
  ID ile fence eder ve explicit reprocess completed/failed job'i yeniden
  `queued` durumuna alabilir. Eski worker yeni attempt'i kapatamaz veya stale
  canonical/journal side-effect yazamaz.
- Tarihsel ve daha once production'da uygulanmis mutable-include `001` dosyasi
  degistirilmedi ve acik legacy allowlist ile upgrade uyumlulugu korundu. `003`
  self-contained immutable schema snapshot oldu; migration runner yeni
  migration'larda uygulanmis checksum drift'inde fail-fast davranir.
- Yeni migration:
  `004_phase2_canonical_line_allocations.sql`. Yeni regression'lar stable ID
  reorder, missing/duplicate/unknown decision ID, mixed-VAT allocation,
  tenant-scoped identity, iade original-reference ve migration constraint
  kontratlarini kapsar.
- 2026-07-18 yerel kanit: backend `429/429`, frontend `145/145`, Next production
  build ve `git diff --check` basarili.
- Ayni gun yapilan Superpowers-sonrasi kalite auditinde fake repository
  regression'larinin gercek transaction davranisini kanitlamadigi goruldu.
  Kalici `test_normalized_invoice_journal_postgres.py` paketi eklendi ve izole
  `postgres:16` uzerinde `9/9` gecti. Paket purchase/sales normalized owner,
  source/processing/review/reopen projection rollback atomikligi, reopen
  allocation lineage, tenant izolasyonu, stale attempt fencing ve eksik
  canonical line-decision approval guard'ini gercek SQL ile kapsar.
- Audit sirasinda dort somut kusur RED ile yeniden uretildi ve duzeltildi:
  source intake, processing sonucu, review ve reopen projection hatalarinda
  normalized state'in once commit edilmesi; ayrica reopen working revision'inda
  `journal_line_allocations` lineage'inin kaybolmasi. Normalized owner ile
  compatibility projection artik ayni PostgreSQL transaction'inda yazilir;
  reopen onceki approved allocation'lari yeni revision satirlarina audit
  metadata'siyle kopyalar.
- Duzeltme sonrasi normal backend discovery `439 OK (skipped=9)` dondu; skip
  edilenlerin tamami DSN-gated gercek PostgreSQL paketidir ve ayri kosuda
  `9/9` gecmistir. Frontend `145/145`, Next production build ve
  `git diff --check` de basarilidir.
- Izole gercek `postgres:16` smoke'unda migration `001/002/003/004` uygulandi.
  Ayni `client_id` iki tenantta iki ayri taxpayer olarak kaldi; iki satirli
  yuzde 20/yuzde 10 karma KDV alis faturasi chart import yolu ile relational
  hesap planina baglandi; stale side-effect reddedildi, iki satirdan bir satira
  valid re-extraction eski satiri supersede etti, TRY disi ve unresolved tevkifat
  approval'i kapatti, exact revision ile temiz TRY taslak onaylandi. Fresh
  migration runner `001/002/003/004` uyguladi ve checksum tamper'ini reddetti.
  Ayrica production-upgrade simulasyonunda legacy checksum'lu uygulanmis
  `001/002` uzerinden yeni runner `003/004` migration'larini basariyla uyguladi.
  Test container'lari smoke sonrasinda temizlendi.
- Phase 2 kod/SQL core tamamlandi fakat roadmap exit gate henuz kapanmadi:
  workspace'te 35 alis + 15 satis gercek faturadan olusan protected corpus yok.
  Bu nedenle `zero missing/duplicated/shifted line` ve muhasebe-quality
  hedefleri sentetik/izole smoke disinda iddia edilmiyor. Siradaki zorunlu is,
  pilot musavirin saglayacagi versioned 50-fatura corpusunu immutable kaynak ve
  referans musavir sonucu ile kurup Phase 2 parity/quality run'ini yapmaktir.

- Repo: `keremerdogdu92/Fisora`
- Aktif branch: `main`
- Son dogrulanan runtime kod release'i: `935a1fa`; kod release scripti
  `before_commit=935a1fa`, `after_commit=935a1fa`, `smoke=ok`, `/health`
  200, readiness 200, root route 200, `ready=true`, `pilot_sellable=true`
  dondu.
- Son deploy smoke: 2026-07-25, `/health` 200, readiness `ready=true`,
  `pilot_sellable=true`; root route 200.
- KDV ayrimi guven katmani canlida: PDF faturalarda `exact`, `derived`,
  `needs_review` statuleri uretildi; belge isleme sonucuna `vat_split_review`
  kaydi, pipeline'a `vat_split_classified`, musavir onayina
  `vat_split_review_saved` olayi eklendi.
- 2026-06-29 hesap plani ve AI karar kapisi release'i canliya alindi:
  kesin KDV/hukuki kurallar AI tarafindan ezilmez. Bu release'te AI yalniz
  belirsiz satir, zayif hesap adayi veya marka/model-only aciklamalarda
  devreye giriyordu; 2026-07-02 yururluk notuyla bu kapi AI-first soguk
  baslangic yorumlayicisi olacak sekilde genisletildi.
- 2026-07-02 yururluk notu: yeni AI-first karar motoru hedefinde AI soguk
  baslangicta ana fatura anlamlandirici katmandir. Deterministik motor KDV,
  borc/alacak dengesi, mevcut hesap plani aday listesi, kesin kanuni kurallar
  ve export kapisini korur. AI mevcut hesap plani adayindan hesap sectiyse
  motor bunu hesap ailesi filtresiyle daha genel bir hesaba kaydirmaz; yanlis
  muhasebe yorumu mustavir review/learning dongusunde duzeltilir. Tavily
  yalniz AI emin degilse, urun yeni/belirsizse veya faaliyet/NACE baglami
  eksikse calisir. Musavir onay/duzeltmeleri learning event olarak AI/research
  tekrarini azaltacak sekilde kullanilir.
- 2026-07-02 canli uygulama durumu: cold-start core business stok/COGS satiri
  `cold_start_core_accounting_line` gerekcesiyle kabul ediliyor; AI
  `needs_research=true` dediginde kategori bilinse veya guven yuksek olsa bile
  research calisiyor; portal karar zinciri urun kimligi, NACE/faaliyet,
  research ihtiyaci/sorgusu ve cari aday izini gosteriyor. Faz 8 icin cok
  mukellefli private sample matrix ve canli smoke henuz siradaki is.
- 2026-07-03 plan guncellemesi: sabit `12` hesap adayi kirpmasi yerine
  zengin ama olculu iki asamali AI hesap/cari secimi hedeflendi. Aday seti
  kucukse tek cagri kalir; buyukse Stage 1 hesap ailelerini, Stage 2 dar
  gercek hesap listesi ve ilgili `120/320` cari adaylarini secer. Her asama
  `candidate_count`, `input_chars`, secilen aile/hesap/cari ve fallback
  sebebiyle telemetry'ye yazilacak.
- 2026-07-02 belge onizleme duzeltmesi canlida: `/portal/belgeler` orijinal
  belge fetch'i artik diger backend cagrilariyla ayni API base resolver'i
  uzerinden `/api/phase0/store/document-file/...` yoluna gider. Orhan Elibol
  belgesi `1061386125_AVQ2026000000026.pdf` icin canli public API `200
  application/pdf` dondu. Fis toplamlari icin `3399.99` gibi nokta-decimal
  degerler artik `339999.00` olarak sismiyor.
- Muhasebe fisi UX'i guncellendi: `/portal/belgeler` ekraninda fis satirlari
  en onde duzenlenir; `Karar ve gerekce` sureci fisin altinda ikincil alanda
  kalir. `Duzeltme notu` ve `Kural talimati`, fis satiri/hesap-cari
  duzeltmesiyle ayni review payload'inda kaydedilir.
- UI/UX remediation deploy: 2026-06-26, `main` ucu `86000c7`.
  Release orchestrator `smoke=ok`, `/health` 200, readiness `ready=true`,
  `pilot_sellable=true` dondu.
- Canli UI smoke: `http://185.184.208.188/portal/belgeler`,
  `/portal/mukellefler`, `/portal/bilgi-havuzu` dolu render oldu; Next error
  overlay yok, console error/warn yok, desktop overflow `0px`.
  `/portal/mukellefler` yeni onboarding adimlari ve blocked-reason metniyle
  render oldu; `Yardim` topbar dialog'u canlida acildi.
- Belge isleme sayfasinda temkinli `Belge ajani` ve `Arastirma ajani`
  kapasite gostergesi canlida dogrulandi. Tavily usage snapshot'i 10 dakika
  cache edilir; hesap iki deneme ve yuzde 25 operasyon rezervi kullanir.
- Musavir dashboard metrikleri kompakt ikonlu kartlara tasindi; desktop 6
  sutun, tablet 3x2, mobil 2x3 duzeni ve sol menu ikonlari canlida
  dogrulanacak runtime kapsamindadir.
- Belge isleme ekrani altta genis belge listesi, ustte belge onizleme ve
  muhasebe fisi olacak sekilde yenilendi. Teknik pipeline varsayilan kapali,
  sol menu daraltilabilir; canli `/portal/belgeler` rotasinda dogrulandi.
- Server repo dizini: `/opt/fisora/app`
- Server runtime: Docker Compose production stack
- Aktif birincil provider: NVIDIA
- AI fallback sirasi:
  `FISORA_AI_PROVIDER_CHAIN=nvidia,groq,cerebras,cloudflare,sambanova,openrouter`.
  Keyler sadece serverdaki ignored `deploy/production.env` dosyasinda tutulur.
- Faz 3 Tavily Bilgi Havuzu pilot akisi hazirlandi. Otomatik research sadece
  belirsiz faturalarda calisir; OpenAI web research sonraki iterasyon icin
  kodda korunur. Tavily icin `FISORA_RESEARCH_ENABLED=true`,
  `FISORA_RESEARCH_PROVIDER=tavily` ve `TAVILY_API_KEY` gerekir. Bilgi Havuzu
  route'u: `/portal/bilgi-havuzu`.
- Server env dosyasi: `/opt/fisora/app/deploy/production.env`

### QNB Faz 3 durum uzlastirma - 2026-07-11

- Giden e-Fatura status uzlastirma backend hatti eklendi.
- Gercek TEST2 -> TEST1 kaniti: `FSR2026713888654`, OID
  `0wmqkswwso125r`, QNB kodu `3`, normalize durum `processed`.
- Her sorgu append-only snapshot; son durum ayrica tutuluyor ve degisim
  `previous_processing_state/changed` ile kanitlaniyor.
- Tekli endpoint:
  `POST /phase0/qnb/connections/{client_id}/outgoing-invoices/status`.
- Toplu endpoint:
  `POST /phase0/qnb/connections/{client_id}/outgoing-invoices/status/bulk`.
- Liste endpoint:
  `GET /phase0/qnb/connections/{client_id}/outgoing-invoices`.
- Unknown provider kodu basarili sayilmiyor. Muhasebe kaydi status sorgusuyla
  otomatik silinmiyor veya ters cevrilmiyor.
- Gelen belge Faz 3 tamamlama: `gelenBelgeDurumSorgulaExt` kontrati ve
  `yanitDurumu` kodlari dogrulandi. Gercek TEST1 ETTN sorgusu `-1/received`
  dondu. `1=rejected`, `2=accepted`, `iptalTarihi=cancelled`; unknown ayrica
  warning olarak kalir. Red/iptal/unknown otomasyon hold + review flag +
  pipeline event olusturur. Belge panelinde QNB durumu ve kontrol zamani
  gorunur; muhasebe kaydi otomatik ters cevrilmez.
- QNB Faz 4 tamamlandi: credential store'da Fernet ciphertext olarak tutulur;
  production anahtari `FISORA_QNB_CREDENTIAL_KEY`, ERP config'i
  `FISORA_QNB_ERP_CODE` ile server env'den gelir. Frontend ERP alani kaldirildi.
  Bos parola metadata update'te mevcut credential'i korur; yeni parola rotate
  ve connection test yapar. Disable endpoint/UI, QNB host allowlist'i,
  test-production ortam eslesmesi, actor/target audit ve client izolasyon
  negatif testi eklendi. Siradaki faz scheduler ve operasyon dayanıkliligi.

- QNB Faz 5 scheduler cekirdegi eklendi: mukellef bazli sync policy API/UI,
  worker tick, JSON lock ve Postgres `FOR UPDATE SKIP LOCKED` ile atomik claim,
  10 dakikalik lease expiry ve hata sonrasi exponential backoff mevcut. Aktif
  credential olmadan otomatik akis acilamaz; policy kapatmak belge/status
  kanitini silmez. Basarili cursor sync ardindan gelen belge status mutabakati
  calisir. Backend 398/398 ve frontend production build basarili. Faz 5'in
  kalan kabul kapisi iki workerli Docker restart/lease kaniti ile belge
  yasi/riskine gore status sikligi ve ortak provider request butcesidir.

- QNB Faz 5 uygulama kapsami tamamlandi: yeni belgeler 6 saat, 90 gun icindeki
  riskli/onayli/export edilmis belgeler 24 saat, eski stabil belgeler 7 gun
  aralikla status kontrolune girer. Liste/download/status ayni 150 request run
  butcesini paylasir. Double-claim ve restart sonrasi expired lease reclaim
  testli. Izole `fisero-qnb-test` Docker projesinde Postgres, Redis, migration,
  saglikli backend ve iki worker ayaga kalkti; iki worker restart sonrasi da
  idle tick uretmeye devam etti. Test container/volume'lari temizlendi.
- QNB Faz 6 tamamlandi: health API; maskeli WS kullanicisi, ortam ve son
  baglanti testi; son basarili/son deneme/sonraki run; cursor ve run sayilari;
  guvenli hata metni portal ayarlarinda gorunur. Belge paneli QNB cekilme ve
  status kontrol zamanini, resmi durum uyarilarini ve yetersiz canonical kaniti
  musavir dilinde gosterir. Siradaki faz sunucu/kapali pilot Faz 7'dir.
- QNB Faz 7 ilk kontrolu: `185.184.208.188:22` SSH baglantisi 2026-07-11'de
  timeout verdi; onceki "odeme nedeniyle kapali" sunucu beyaninin degistigine
  dair canli kanit yok. Bu nedenle disk/backup/env/deploy smoke kosulamadi.
  Sunucu acilana kadar production compose duzeltildi: QNB adapter, ERP kodu ve
  credential key artik scheduler'i calistiran worker'a da aktarilir. Readiness
  `qnb_pilot` altinda SOAP adapter, credential key varligi, ERP config,
  Postgres, backup ve restricted-access kapilarini secret gostermeden raporlar.
- Sunucusuz QNB PDF isi tamamlandi: resmi `gelenBelgeleriIndirExt` metodunda
  `belgeFormati=PDF` kullanilir. Tek PDF/ZIP/header guvenlik kontrolu, ETTN +
  parent UBL baglantisi, hash, pulled-at ve idempotent evidence API eklendi.
  e-Arsiv kamu dokumani gelen belge liste/download/status kontrati vermedigi
  icin varsayimsal adapter yazilmadi; gereken QNB WSDL/yetki listesi
  `docs/superpowers/specs/2026-07-11-qnb-pdf-and-earsiv-boundary.md` icinde.
- 2026-07-11 gercek local kapanis smoke'u: TEST1 connection `active`; 30 gunluk
  backfill 2 belge listeledi, 1 yeni UBL indirip worker'da tamamladi, tekrar
  sync 2/2 duplicate atladi. Ayni gercek belgenin QNB PDF'i 38.184 byte ve
  `%PDF-` header ile dogrulandi; SHA-256 secret-safe smoke ozetinde tutuldu.
  Cursor `1 -> 2` ilerledi, ikinci cursor run sifir belge dondu. Gercek
  scheduler policy'yi claim etti, cursor sync `completed` ve gelen status
  mutabakati `updated_count=2`, `error_count=0` oldu. Bu nedenle QNB gelen
  e-Fatura cekirdeginin local/sandbox kapsami kapanmistir.
- 2026-07-13 e-Arsiv gonderim spike'i: QNB mailindeki `portaltest`,
  `connectortest` ve `earsivtest` bilgileri ignored `.env.qnb.local` dosyasina
  alindi. Gercek WSDL/XSD; `faturaOlusturExt`, sorgu/liste, iptal/itiraz,
  taslak ve onizleme metotlarini dogruladi. `qnb_earsiv.py` Ext adapteri ve
  yalniz test hostlarini kabul eden, `--confirm-send` kapili secret-safe smoke
  araci eklendi. Gercek login `EF0556` dondu: portal kullanicisi mali muhur veya
  e-imza ile dogrulanmali ve QNB onerisine uygun ayri WS kullanicisi
  olusturulmali. Bu dis adim tamamlanmadan fatura gonderilmedi. Backend 406/406,
  frontend 144/144, production build ve `git diff --check` basarili.
- 2026-07-13 QNB cevabi beklenirken Faz 9 local cekirdegi ilerletildi:
  provider-bagimsiz `efatura`/`earsiv` taslagi, cok satirli kesin KDV/toplam
  hesabi, onayda dondurulan UBL 2.1 + SHA-256, `draft -> approved -> sending ->
  sent/failed` durumlari ve JSON/PostgreSQL atomik idempotency kaydi eklendi.
  Giden fatura API'si yalniz musavir/admin rollerine acik; onaysiz gonderim ve
  mukellefler arasi erisim reddedilir. Provider varsayilan olarak local `fake`
  ve receipt uretir; QNB blokaji kalkana kadar gercek dis gonderim kapali.

`deploy/production.env` GitHub'a girmez. `POSTGRES_PASSWORD`, `GROQ_API_KEY`,
`OPENROUTER_API_KEY`, `CEREBRAS_API_KEY` ve varsa fallback provider keyleri
sadece serverdaki bu dosyada tutulur.

## 2026-07-08 QNB e-Belge Entegrasyon Karari

QNB eSolutions test ortami basvurusu sonucunda Fisora, SaaS/ERP entegrasyonu
olarak kabul edildi ve Fisora'ya ERP kodu tanimlandi. ERP kodu QNB SOAP
parametrelerinde kullanilacak sabit uygulama kodudur; tum firmalarda ayni
kalir. Tam kod, test kullanici sifreleri ve canli kimlik bilgileri repoya
yazilmaz; mail/secret kaynagindan alinarak ignored env icinde tutulmalidir.

QNB tarafindan bildirilen teknik durum:

- Rate limit: dakikada 180 request.
- e-Fatura ve e-Irsaliye testleri `erpefaturatest1` ve `erpefaturatest2`
  ortamlarinda yapilacak. Bu iki ortam karsilikli belge gonderip alabilecek
  sekilde tanimli; ayni ortamdan ayni ortama belge gonderimi testte yok.
- e-Arsiv, e-Defter, eSMM, eMM, e-Adisyon ve e-SKGB testleri
  `portaltest` / `connectortest` / `earsivtest` ortamlarinda yapilacak.
- Canli ortamda tek kullanici adi/sifre ile butun servislere erisilebilecegi
  bildirildi; testte ortamlar ayridir.
- QNB, portal kullanicisi ile web servis kullanicisinin ayrilmasini onerdi.
  Portal sifresi degisimleri WS login tarafini bloke edebilecegi icin Fisora
  entegrasyonunda ayri WS kullanicisi olusturulmalidir.
- `Ext` ile biten metotlarda ERP kodu dogrudan `erpkodu` parametresiyle
  gonderilmeli; Ext olmayan metotlarda `erpBilgileriBelirle` akisi gerekiyor.
  SOAP header kullanan entegrasyonda Ext metotlari tercih edilmelidir.

Bu karar urun yonunu degistirdi: ana belge girisi artik "mukellef dosya
yuklesin" degil, "QNB'den otomatik belge senkronizasyonu" olmalidir. Manuel
upload sistemi cope gitmez; QNB disi entegratorler, eski belgeler, banka
ekstreleri, vergi levhasi, sozlesme, dekont ve API kesintisi durumlari icin
yedek/manual kaynak adaptoru olarak kalir.

Yeni hedef akisi:

```text
QNB baglantisi/yetkisi -> belge senkronizasyonu -> UBL/PDF/status alma
-> canonical invoice -> iptal/red/itiraz kaniti -> muhasebe fisi taslagi
-> musavir kontrolu -> export
```

Belge saklama politikasi yeniden tasarlanacak. QNB kaynakli belgelerde QNB
yeniden indirme kaynagi olabilir, fakat Fisora yine minimum kanit tutmalidir:

- QNB belge kimligi: ETTN/UUID, belge no, VKN/TCKN, tarih.
- Kaynak ve cekilme zamani.
- UBL/PDF hash'i ve islenen canonical veri.
- Muhasebe fisi taslagi, review kararlari ve export sonucu.
- Iptal/red/itiraz/status kaniti ve son sorgulama zamani.
- Pilot icin UBL/PDF cache tutulmasi onerilir; uzun vadede saklama politikasi
  musteri/mevzuat ihtiyacina gore ayarlanabilir.

QNB entegrasyonu tamamlaninca etkilenecek ana sistemler:

- Onboarding: mukelleften yalniz dosya istemek yerine QNB kullaniyor mu,
  VKN/TCKN, servis kullanicisi/yetki, senkron baslangic tarihi ve musavir
  yetkisi alinacak.
- Mukellef portali: belge yukleyen ana kullanici yerine baglanti/yetki veren,
  eksikleri tamamlayan ve yorum/onay veren role kayar.
- Musavir portali: cok mukellefli belge akisi, QNB baglanti durumu, yeni gelen
  belgeler, iptal/red uyarilari, fis taslaklari ve kontrol kuyrugu ana ekran
  haline gelir.
- Parser: UBL canonical veri birincil kaynak olur; PDF daha cok onizleme ve
  gorsel kanit/fallback icin kullanilir.
- Iptal politikasi: "UBL'de iptal yoksa iptal degildir" denmez. QNB status,
  uygulama yaniti, e-Arsiv iptal/itiraz bilgisi, iptalTarihi ve PDF gorsel
  damga ayri kanit katmani olarak izlenir.
- Storage: manuel document store kalir ama QNB icin source-adapter + metadata +
  evidence snapshot modeli hedeflenir.
- Rate limit/worker: dakikada 180 request siniri icin kuyruk, throttle, retry
  ve idempotent sync zorunludur.
- Cok mustavirli SaaS: Fisora platformu altinda birden fazla musavir ofisi,
  her musavirin altinda birden fazla mukellef ve her mukellef icin ayri QNB
  yetki/credential modeli hedeflenir.

Urun modulu kapsami:

- e-Fatura: ilk oncelik. Gelen/giden listeleme, UBL/PDF indirme, durum
  sorgulama, ticari faturada kabul/red uygulama yaniti, ileride Fisora'dan
  fatura kesme.
- e-Arsiv: ilk oncelik. e-Fatura mukellefi olmayanlara/son tuketiciye kesilen
  faturalar; UBL/PDF alma, sorgulama, iptal/itiraz/status kaniti ayrica test
  edilecek.
- e-Irsaliye: e-Fatura ile benzer altyapi ama sevkiyat belgesi. Fatura
  temelinden sonra daha hizli eklenebilir; alanlari ve is kurallari farklidir.
- e-Defter: fatura kesme degil, yasal defter/berat/donem kapanisi sureci.
  QNB donusunde testte CSV format hazirlayip portal upload ile deneme
  anlatildi. Fisora icin ileride e-Defter export/donem hazirligi olabilir.
- eSMM/eMM: muhasebe fisi degil, serbest meslek makbuzu ve mustahsil makbuzu
  gibi fatura benzeri resmi belge tipleri. Kesildikten sonra muhasebe fisine
  kaynak olabilir.
- e-Adisyon/e-SKGB: restoran/adisyon ve sigorta komisyon gider belgesi gibi
  nis alanlar; simdilik ana oncelik degil.

Bir sonraki planlama icin acik kararlar:

1. QNB'den cekilen UBL/PDF dosyalari pilotta kalici mi saklanacak, yoksa
   hash + canonical veri + yeniden indirme modeli mi uygulanacak?
2. Ilk entegrasyon yalniz belge okuma/status mu olacak, yoksa ayni fazda
   fatura kesme/gonderme de kapsama alinacak mi?
3. Cok mustavirli modelde credential sahipligi musavir ofisi bazinda mi,
   mukellef bazinda mi, yoksa ikisi birlikte mi tutulacak?
4. Manuel upload UI ana aksiyon olmaktan cikarilip "manuel/yedek kaynak" olarak
   yeniden konumlandirilacak mi?
5. QNB disi entegratorler icin simdiden generic `document_source_adapter`
   arayuzu tasarlanacak mi?

Pratik siradaki is: QNB entegrasyonu icin tasarim/spec yaz. Once mevcut
document upload pipeline'i kaynak-adaptorlu hale getiren mimariyi netlestir,
sonra kucuk bir proof hedefi sec: SOAP login + e-Fatura/e-Arsiv listeleme veya
belge indirme + status kaniti.

### 2026-07-10 QNB uygulama plani guncellemesi

Onceki "tasarim/spec yaz" adimi tamamlandi ve gelen e-Fatura Phase 1 cekirdegi
`main` branch'inde uygulandi. Mulkellef bazli QNB baglantisi, gercek SOAP
adapter, manuel tarih aralikli listeleme, UBL indirme/acma, duplicate kontrolu,
document/job kaydi ve portal ayarlari mevcuttur. Gercek TEST2 login ve bos liste
smoke'u basarili oldu; test gelen kutusu bos oldugu icin gercek QNB UBL'sinin
canonical invoice ve muhasebe taslagina kadar ilerlemesi henuz kanitlanmadi.

Uctan uca master plan:

`docs/superpowers/plans/2026-07-10-qnb-end-to-end-integration.md`

Siradaki is, kiralik sunucuyu acmadan yerel ortamda QNB test hesaplari arasinda
kontrollu bir e-Fatura olusturmak; alici hesaptan Fisora ile listelemek,
indirmek, canonical invoice ve fis taslagina kadar islemek ve tekrar sync'te
duplicate olusmadigini kanitlamaktir. Ardindan sirasiyla sayfalama/cursor,
status-iptal-red kaniti, credential guvenligi, scheduler/lease/retry, musavir
operasyon UX'i ve kapali pilot server dogrulamasi yapilacaktir.

Mevcut kiralik sunucu odeme nedeniyle kullanici beyanina gore kapali durumdadir.
Bu durum yerel QNB gelistirmesini engellemez. Ancak hosting panelindeki disk
saklama/silinme tarihi ayri bir veri koruma isi olarak kontrol edilmelidir.

2026-07-10 ilk uygulama ilerlemesi:

- Yerel ignored `.env.qnb.local` icinde receiver `TEST1`, sender `TEST2`
  rolleri dogrulandi.
- Iki hesabin gercek SOAP login'i basarili; TEST1 son 30 gun gelen listesi bos.
- Secret gostermeyen ve kalici local JSON store ile tekrar/duplicate smoke'u
  calistirabilen `backend/scripts/run_qnb_sandbox_smoke.py` eklendi.
- Yeni smoke araci ve mevcut QNB entegrasyon testleri birlikte 11 testle
  basarili oldu.
- TEST2 portalinin zorunlu ilk/90 gunluk parola degisikligi kullanici tarafindan
  tamamlandi ve yeni deger ignored local env'e kaydedildi. Ayri WS
  kullanicisi/credential'i ile portal credential'i production oncesi ayrilmali.

2026-07-10 QNB uctan uca sandbox kaniti tamamlandi:

- TEST2 credential rotate edildi ve yeni degerle SOAP login `active` kaldi.
- Resmi QNB API/WSDL kontratina gore `belgeGonderExt`, aktif PK/GB etiket
  sorgusu ve `gidenBelgeDurumSorgulaExt` adapter davranisi eklendi.
- `send_qnb_sandbox_invoice.py` TEST2 -> TEST1 tek satirli UBL-TR test faturasi
  uretip gonderdi. QNB OID dondu ve durum `3 / processed` oldu.
- Ayni ETTN TEST1 gelen listesinde goruldu; `run_qnb_sandbox_smoke.py` UBL'yi
  indirdi, document/job olusturdu ve worker bir belgeyi basariyla tamamladi.
- Canonical sonuc: `TEMELFATURA`, `SATIS`, purchase yonu, 1 satir, 100 TRY
  matrah, yuzde 20 KDV, 120 TRY odenecek tutar.
- Dengeli taslak: 770.01 borc 100, 191.01 borc 20, 320.5910611341 alacak 120.
  Profil/hesap plani olmadigi icin sonuc dogru bicimde `review_required` kaldi.
- Ikinci sync listede ayni belgeyi gordu ama `downloaded_count=0`,
  `skipped_duplicate_count=1`; ikinci document/job olusmadi.
- Sandbox gonderim araci non-test QNB endpoint'lerini reddeder, UBL
  fatura/gonderici/alici/toplam kontrollerini yapar, gercek gonderim icin
  `--confirm-send` ister ve sonraki gonderimlerde OID/status receipt saklar.
- QNB odak testleri 16/16, tam backend paketi 378/378 basarili; `git diff
  --check` temiz.

Siradaki teknik faz: gelen belge sayfalama/cursor, retry/rate limit ve kalici
idempotency hardening. Giden e-Fatura adapter cekirdegi yeniden kullanilabilir
hale geldi; musavir UI/API ve production gonderim yetkisi ayri kabul kapisi
olmadan acilmayacak.

2026-07-11 QNB Faz 2 sync hardening tamamlandi:

- Liste kontrati `items`, `last_sequence_no`, `has_more` alanli sayfa modeline
  cevrildi; gercek response'ta `belgeSiraNo` zorunlu.
- Cursor modu 100'luk sayfalari tarih filtresi eklemeden ilerletiyor. Cursor
  yalniz sayfanin tum belgeleri duplicate veya basarili oldugunda JSON/Postgres
  store'a kalici yaziliyor.
- Bir download/job hatasinda run `partial_failed`; cursor ilerlemiyor ve hatali
  ETTN identity claim'i serbest birakilarak yeniden denemeye acik kaliyor.
- Tarihli backfill ile cursor ayni QNB request'ine konmuyor. Tarihli sonuc 100
  sinirina dayanirsa sessiz eksik alma yerine `backfill_truncated` donuyor.
- JSON store'da lock altinda, Postgres'te unique workflow record + `ON CONFLICT
  DO NOTHING` ile mukellef kapsamli ETTN/fallback identity claim eklendi.
- Gercek TEST1 cursor smoke: cursor `1`; ardisik iki run `listed_count=0`,
  `status=completed`, cursor degismeden `1` kaldi; QNB logout basarili.
- Adapter konservatif 150 request/dakika throttle, timeout/429/5xx exponential
  backoff, max sayfa, guvenli hata kodlari, base64/ZIP boyut ve dosya sayisi,
  path traversal ve tek XML kontrolleriyle sertlestirildi.

Siradaki faz: QNB gelen belge status/iptal/red/kabul mutabakati. Once gercek
`gelenBelgeDurumSorgulaExt` response kontrati sandbox'tan alinacak; ardindan
append-only status evidence, review flag ve portal gorunurlugu eklenecek.

## Yeni Bilgisayarda Devam Etme

GitHub hesabi private repoya yetkili olmalidir. Aktif pilot branch'ini almak icin:

```bash
git clone -b main https://github.com/keremerdogdu92/Fisora.git
cd Fisora
```

Zaten clone varsa:

```bash
git fetch origin
git checkout main
git pull --ff-only origin main
```

## Serverda Kaldigimiz Yer

Serverda Docker kuruldu ve stack bir kez basariyla ayaga kalkti. Su servisler
healthy gorundu:

- `backend`
- `frontend`
- `postgres`
- `redis`
- `nginx`

Nginx `80` portunu disari aciyor. Tarayicida demo URL formati:

```text
http://<SERVER_IP>/
```

`<SERVER_IP>` degeri repoya yazilmaz; server panelinden veya mevcut SSH
bilgisinden bakilir.

## Serverda Son Kodu Cekme ve Redeploy

Serverda son commit'i almak icin:

```bash
cd /opt/fisora/app
git fetch origin
git checkout main
git pull --ff-only origin main
```

Config kontrolu ve deploy:

```bash
powershell -ExecutionPolicy Bypass -File deploy/scripts/fisora-release.ps1 -Branch main -BaseUrl http://185.184.208.188 -SkipLocalVerify -Json
```

## Env Kontrolu

Serverdaki asil env dosyasi:

```bash
nano /opt/fisora/app/deploy/production.env
```

Minimum beklenen satirlar:

```env
POSTGRES_PASSWORD=<strong-password>
FISORA_HTTP_PORT=80
FISORA_AUTH_MODE=mock_header_required
FISORA_AUTH_PASSWORD_BOOTSTRAP_ENABLED=false
FISORA_AI_PROVIDER=nvidia
FISORA_AI_PROVIDER_CHAIN=nvidia,groq,cerebras,cloudflare,sambanova,openrouter
FISORA_AI_MODEL=openai/gpt-oss-20b
FISORA_NVIDIA_MODEL=openai/gpt-oss-120b
FISORA_NVIDIA_MAX_TOKENS=1024
FISORA_NVIDIA_TIMEOUT_SECONDS=60
FISORA_GROQ_MODEL=openai/gpt-oss-20b
FISORA_CLOUDFLARE_MODEL=@cf/openai/gpt-oss-120b
FISORA_CLOUDFLARE_MAX_TOKENS=1024
FISORA_SAMBANOVA_MODEL=gpt-oss-120b
FISORA_OPENROUTER_MODEL=openai/gpt-oss-20b:free
FISORA_OPENROUTER_SITE_URL=http://185.184.208.188
FISORA_OPENROUTER_APP_TITLE=Fisora Operasyon Portal
FISORA_CEREBRAS_MODEL=gpt-oss-120b
FISORA_AI_COMPARISON_MODEL=openai/gpt-oss-120b
FISORA_AI_MONTHLY_CAP_USD=0.01
FISORA_RESEARCH_ENABLED=true
FISORA_RESEARCH_PROVIDER=tavily
FISORA_RESEARCH_MODEL=gpt-5.4-mini
FISORA_RESEARCH_MAX_PER_DOCUMENT=1
FISORA_RESEARCH_CONFIDENCE_THRESHOLD=70
GROQ_API_KEY=<groq-key>
NVIDIA_API_KEY=<nvidia-key>
CLOUDFLARE_API_TOKEN=<cloudflare-token>
CLOUDFLARE_ACCOUNT_ID=<cloudflare-account-id>
SAMBANOVA_API_KEY=<sambanova-key>
OPENROUTER_API_KEY=<rotated-openrouter-key>
CEREBRAS_API_KEY=<cerebras-key>
OPENAI_API_KEY=
TAVILY_API_KEY=<tavily-key>
```

Key'i gostermeden kontrol:

```bash
grep -E 'FISORA_AUTH_MODE|FISORA_AI_PROVIDER|FISORA_AI_PROVIDER_CHAIN|FISORA_AI_MODEL|FISORA_(NVIDIA|GROQ|CLOUDFLARE|SAMBANOVA|OPENROUTER|CEREBRAS)_MODEL|FISORA_AI_COMPARISON_MODEL' deploy/production.env
grep -q '^NVIDIA_API_KEY=.' deploy/production.env && echo "NVIDIA key var" || echo "NVIDIA key eksik"
grep -q '^GROQ_API_KEY=.' deploy/production.env && echo "GROQ key var" || echo "GROQ key eksik"
grep -q '^CLOUDFLARE_API_TOKEN=.' deploy/production.env && echo "Cloudflare token var" || echo "Cloudflare token eksik"
grep -q '^CLOUDFLARE_ACCOUNT_ID=.' deploy/production.env && echo "Cloudflare account ID var" || echo "Cloudflare account ID eksik"
grep -q '^SAMBANOVA_API_KEY=.' deploy/production.env && echo "SambaNova key var" || echo "SambaNova key eksik"
grep -q '^OPENROUTER_API_KEY=.' deploy/production.env && echo "OpenRouter key var" || echo "OpenRouter key eksik"
grep -q '^CEREBRAS_API_KEY=.' deploy/production.env && echo "Cerebras key var" || echo "Cerebras key eksik"
```

## Beklenen Health ve Readiness

Server icinden:

```bash
curl -i http://127.0.0.1/health
curl -s http://127.0.0.1/api/phase0/store/auth/status
curl -s http://127.0.0.1/api/phase0/store/system/readiness
```

Beklenen kritik degerler:

```text
health: 200 OK
auth_mode: mock_header_required
ready: true
pilot_sellable: true
production_ready: false
ai_provider: nvidia
ai_model: openai/gpt-oss-120b
ai_nvidia_key_present: true
zirve_mapping_adapter_available: true
rate_limit_configured: true
```

`zirve_verified_adapter_missing`, `zirve_field_test_pending` ve
`session_required_missing` warning'leri kapali demo modunda normaldir. Zirve
export sahada mustavirle test edilmeden adapter verified sayilmaz; canlı demo
`mock_header_required` modunda kaldigi surece `production_ready=false` kalir.

## Smoke Durumu

`sh deploy/scripts/fisora-prod.sh smoke` bir kez `failed_count=1` verdi. Bu
backend/frontend/nginx'in ayakta olmadigi anlamina gelmiyor; health kontrolleri
basariliydi. Redeploy sonrasi tekrar bak:

```bash
sh deploy/scripts/fisora-prod.sh smoke
```

Yine failed donerse hata detayini al:

```bash
docker compose --env-file deploy/production.env -f docker-compose.production.yml -p fisora exec postgres psql -U fisora -d fisora -c "select payload->>'status' as status, payload->>'error_message' as error_message, payload from workflow_records where record_type='processing_job' order by updated_at desc limit 5;"
```

## Guvenlik Notlari

- Groq key, GitHub token, SSH private key ve server root sifresi chat'e veya
  repoya yazilmaz.
- Server internete acik oldugu anda bot taramalari gelir; nginx logunda
  bilinmeyen 404 istekleri normaldir ama firewall/IP kisiti planlanmalidir.
- Demo kapali IP ile yapilacaksa once SSH ve HTTP erisimi kimlerle paylasilacak
  netlestirilmelidir.

## Kaldigimiz Pratik Sira

1. Tarayicida `http://<SERVER_IP>/` ac.
2. Bir sentetik olmayan pilot fatura yukleyip provider zincirinin mevcut
   muhasebe akisinda olusturdugu taslak, canonical evidence ve aciklamayi kontrol et.
3. Sonucu `workflow_records` uzerinden provider attempt/fallback iziyle
   karsilastir.
4. Muhasebe sonucu yanlissa benchmark kapisi eklemek yerine ilgili belge
   kaniti, provider attempt'i ve taslak journal birlikte incelensin.
