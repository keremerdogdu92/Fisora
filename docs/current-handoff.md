# Current Handoff

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
- Son dogrulanan runtime kod release'i: `39f1b39`; kod release scripti
  `before_commit=240a0f9`, `after_commit=39f1b39`, `smoke=ok`, `/health`
  200, readiness 200, root route 200, `ready=true`, `pilot_sellable=true`
  dondu.
- Son deploy smoke: 2026-07-21, `/health` 200, readiness `ready=true`,
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
- Demo provider: Groq
- AI fallback kodu: `FISORA_AI_PROVIDER_CHAIN=groq,openrouter,cerebras`
  destekli. Keyler sadece serverdaki ignored `deploy/production.env` dosyasinda
  tutulur.
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
FISORA_AI_PROVIDER=groq
FISORA_AI_PROVIDER_CHAIN=groq,openrouter,cerebras
FISORA_AI_MODEL=openai/gpt-oss-20b
FISORA_GROQ_MODEL=openai/gpt-oss-20b
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
OPENROUTER_API_KEY=<rotated-openrouter-key>
CEREBRAS_API_KEY=<cerebras-key>
OPENAI_API_KEY=
TAVILY_API_KEY=<tavily-key>
```

Key'i gostermeden kontrol:

```bash
grep -E 'FISORA_AUTH_MODE|FISORA_AI_PROVIDER|FISORA_AI_PROVIDER_CHAIN|FISORA_AI_MODEL|FISORA_(GROQ|OPENROUTER|CEREBRAS)_MODEL|FISORA_AI_COMPARISON_MODEL' deploy/production.env
grep -q '^GROQ_API_KEY=.' deploy/production.env && echo "GROQ key var" || echo "GROQ key eksik"
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
ai_provider: groq
ai_model: openai/gpt-oss-20b
ai_groq_key_present: true
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

1. Serverda `git checkout main && git pull --ff-only origin main` ile son commit'i cek.
2. `sh deploy/scripts/fisora-prod.sh check && sh deploy/scripts/fisora-prod.sh deploy && sh deploy/scripts/fisora-prod.sh smoke` calistir.
3. Auth status `mock_header_required` donuyor mu kontrol et.
4. Readiness icinde `pilot_sellable=true`, `production_ready=false`,
   `zirve_mapping_adapter_available=true`, `rate_limit_configured=true`,
   `ai_groq_key_present=true` ve `ai_provider_configured=true` mi kontrol et.
5. Tarayicida `http://<SERVER_IP>/` ac.
6. Fatura ve banka upload akisini Groq AI acik halde dene.
7. Smoke failed kalirsa yukaridaki SQL komutuyla job error detayini al.
