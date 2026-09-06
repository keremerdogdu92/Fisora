# Fisora UX/UI — Multi-Agent Review Register — 2026-09-06

**Sources:** ChatGPT accountant acceptance audit + Codex UX/QA audit + Antigravity UX/UI audit.
**Purpose:** Denetimlerde açılan konuları kaybetmeden tek tek görüşmek. Bu dosya otomatik bug/backlog listesi değildir.

## Source documents

- [CG — ChatGPT Accountant Acceptance Audit](./fisora-chatgpt-accountant-acceptance-audit-2026-09-05.md)
- [CX — Codex UX/QA Audit](./fisora-codex-ux-qa-audit-2026-09-05.md)
- [AG — Antigravity UX/UI Audit](./fisora-antigravity-ux-ui-audit-2026-09-05.md)

## Status meanings

- `KONTROL EDİLECEK`: Audit gözlemi; henüz ürün eksiği kabul edilmedi.
- `TEKRAR TEST`: Kaynaklar çelişiyor veya build/state farkı olabilir.
- `ÜRÜN KARARI`: Teknik bug olmak zorunda değil; beklenen davranış kararı gerekir.
- `STRATEJİ KARARI`: Gelecek kapsamı / entegrasyon / feature adayı.
- `TEST SINIRLAMASI`: Audit aracına ait; ürün bug'ı sayılmaz.
- `KABUL EDİLDİ`: Yalnız açık ürün kararı sonrası.
- `REDDEDİLDİ`: Yalnız açık ürün kararı sonrası.

## Decision note — 2026-09-06 — Document-context integrity

**KABUL EDİLEN PRENSİP:** Kullanıcının çalıştığı belgenin kimliği hiçbir anda şüphe yaratmamalı. `activeDocumentId`, source preview, journal/draft ve mutation target aynı canonical belge bağlamına ait olmalı.

**REDDEDİLEN UX YAKLAŞIMI:** State uyuşmazlığında ekranı boşaltıp kullanıcıyı kalıcı biçimde duvara çarptırmak veya `disable everything` davranışını normal ürün akışı yapmak.

**NORMAL BUSINESS FAILURE:** Bir belge gerçekten işlenemiyorsa belge context'ten atılmaz. Kaynak belge mümkünse görünür kalır; neden, hangi aşamanın başarısız olduğu ve sonraki yol (`Tekrar dene`, `Kontrolde tut`, gerekli veriyi tamamla, manuel karar vb.) açıkça gösterilir.

**INTERNAL INTEGRITY FAILURE:** Belge ID / preview / journal / mutation target uyuşmazlığı normal UX state'i değildir. Sistem önce otomatik reconcile/refetch/self-heal denemeli; root cause telemetry/debug ile yakalanmalı. Tehlikeli mutation yalnız bu exceptional durumda geçici olarak engellenir. Amaç kullanıcıyı burada bırakmak değil, bu state'in oluşmasını önlemektir.

---

# A — Belge kimliği, selection ve context bütünlüğü

## REV-A01 — Boş filtrede eski belge/fiş görünmesi
**Status:** KONTROL EDİLECEK — root cause araştırılacak.
**Audit refs:** [CG-01](./fisora-chatgpt-accountant-acceptance-audit-2026-09-05.md#cg-01--empty-filter-leaves-stale-document-context) · [CX UXR-001](./fisora-codex-ux-qa-audit-2026-09-05.md#uxr-001--p0--boş-filtrede-eski-belge-ve-karar-eylemleri-kalıyor)
**Observed:** `Onaya hazır 0`, `Evrak 0/0` iken eski belge/fiş/action context'i yaşayabiliyor.
**Root-cause inspection:** `portal-workspace-view.tsx::applyWorkQueueFilter()` yalnız yeni filtrede en az bir belge varsa ve mevcut seçim listede değilse `selectedDocumentId` değiştiriyor. `nextDocuments.length === 0` olduğunda eski selection yaşamaya devam ediyor.
**Discussion:** Neden canonical selection filtre sonucu ile transactionally uzlaşmıyor? Blank screen normal çözüm olarak kabul edilmeyecek.

## REV-A02 — Kuyruk araması ile sağ panel farklı belge gösterebiliyor
**Status:** KONTROL EDİLECEK — root cause araştırılacak.
**Audit refs:** [CX UXR-002](./fisora-codex-ux-qa-audit-2026-09-05.md#uxr-002--p1--kuyruk-araması-seçimi-senkronize-etmiyor)
**Observed:** `1500` aramasında liste 1.500 TL kayda düşerken sağ panel eski 238,69 TL kaydı göstermeye devam etti.
**Root-cause inspection:** `documentQuery` yalnız `filteredSegmentDocuments` listesini değiştiriyor; query sonucu mevcut selection'ı dışarı attığında `selectedDocumentId` için reconcile eden bir effect/transition yok.

## REV-A03 — Canonical active-document invariant
**Status:** KABUL EDİLEN PRENSİP; implementation henüz kararlaştırılmadı.
**Derived from:** CG-01 + CX UXR-001/002 + 2026-09-06 product discussion.
**Rule:** `activeDocumentId == previewDocumentId == journalDocumentId == mutationTargetDocumentId` olmalı. Mismatch debug edilmesi gereken integrity fault'tur; normal kullanıcı state'i değildir.
**Current architecture note:** `useDocumentWorkflow()` içindeki `selectedDocumentFromState()` seçili belgeyi görünür review/query listesinden değil, `clientDocuments + selectedDocumentSegment` kaynağından çözüyor. Bu yüzden queue visibility ile active document identity iki ayrı eksende yaşayabiliyor.
**Harness note:** `document-workflow-model.test.cjs` içindeki `selected document is found from the segment source even when the visible review filter changes` testi bu davranışı açıkça koruyor. Sorun yalnız rastgele race değildir; mevcut test contract'ının da yeniden değerlendirilmesi gerekir. Safety harness yanlış state'i kalıcı UX olarak meşrulaştırmamalı.

## REV-A04 — İşlenemeyen belge UX'i ile integrity fault ayrımı
**Status:** ÜRÜN KARARI.
**Audit refs:** [CX UXR-003](./fisora-codex-ux-qa-audit-2026-09-05.md#uxr-003--p1--eksik-hesap-seçimi-varken-onay-aktif) · [CG-10](./fisora-chatgpt-accountant-acceptance-audit-2026-09-05.md#cg-10--zero-value-document-still-follows-normal-posting-ux)
**Decision direction:** Gerçekten işlenemeyen/eksik belge görünür kalmalı ve recovery yolu sunmalı. Internal selection mismatch ile aynı empty/disabled UX'e indirgenmemeli.

## REV-A05 — Active document ile queue görünümünü ayırma
**Status:** ÜRÜN KARARI — önerilen model, henüz kabul edilmedi.
**Motivation:** Mevcut kod ve test contract'ı aktif belgeyi filtre değişiminde kaybetmemeyi hedefliyor; sorun bu devamlılığın UI'da first-class bir kavram olmaması.
**Candidate behavior:** Filtre/arama `queue`yu değiştirir; mevcut `active document` kendiliğinden kaybolmaz. Aktif belge yeni queue dışında kalıyorsa UI bunu açıkça `Aktif belge — filtre dışında` gibi işaretler veya queue üstünde pinned olarak gösterir. Kullanıcı başka belge seçtiğinde tüm canonical context atomik değişir.
**When processing fails:** Aktif belge görünür kalır; kaynak, başarısız aşama, neden ve recovery seçenekleri gösterilir. Kullanıcı boş duvara bırakılmaz.
**When integrity fails:** Önce automatic reconcile/refetch; düzelmezse mutation geçici durur, telemetry/debug kaydı oluşur ve recovery UI gösterilir. Bu exceptional safety path normal belge state'i değildir.
**Current code refs:** `frontend/app/portal-workspace-view.tsx:266,285,304,334`; `frontend/app/features/documents/use-document-workflow.ts:52`; `frontend/app/features/documents/document-workflow-model.js:74`; `frontend/app/features/documents/document-workflow-model.test.cjs:39`.
# B — Onay, undo, kontrolde tut, hariç tut

## REV-B01 — Ctrl+Z geri alma görünür sonuç üretmedi
**Status:** KABUL EDİLDİ / UYGULANDI — production UI doğrulaması bekliyor.
**Audit refs:** [CG-02](./fisora-chatgpt-accountant-acceptance-audit-2026-09-05.md#cg-02--ctrlz-undo-did-not-visibly-work) · [CX Post-authorization validation](./fisora-codex-ux-qa-audit-2026-09-05.md#post-authorization-demo-state-validation)
**Kerem kararı (2026-09-06):** Ctrl+Z süre bazlı değil işlem bazlı olacak; son geri alınabilir müşavir işlemini geri alacak. Eski bir belge ayrıca açık `Kontrole geri al` aksiyonuyla yeniden açılabilecek.
**Implementation refs:** `frontend/app/features/review/use-review-commands.ts`, `frontend/app/portal-next/portal-next-workspace-controls.tsx`, `frontend/app/portal-review-performance.test.cjs`, `frontend/app/portal-next.test.cjs`.

## REV-B02 — Hariç tut görünür state transition üretmedi
**Status:** KABUL EDİLDİ / UYGULANDI — production UI doğrulaması bekliyor.
**Audit refs:** [CG-09](./fisora-chatgpt-accountant-acceptance-audit-2026-09-05.md#cg-09--hariç-tut-showed-no-visible-transition) · [CX UXR-011](./fisora-codex-ux-qa-audit-2026-09-05.md#uxr-011--p1--hariç-tut-aksiyonu-görünür-sonuç-üretmiyor)
**Kerem kararı (2026-09-06):** `Hariç tut` = bu belgeyi işlemeyeceğiz; hard delete değildir. Belge ve geçmişi korunur ve tekrar kontrole alınabilir.
**Root cause:** Backend `rejected` üretse de frontend bunu `review_required`a normalize ediyordu; normalized persistence da exclusion kararını bazı akışlarda review state'ine eziyordu.
**Implementation refs:** `backend/app/persistence/normalized_accounting_repository.py`, `backend/app/persistence/postgres_workflow_store.py`, `frontend/app/portal-normalization.js`, `frontend/app/portal-document-actions.ts`, `frontend/app/portal-review-panels.tsx`, `frontend/app/features/documents/document-workflow-model.js`.

## REV-B03 — Hariç tutulanlar görünümü / geri getir
**Status:** KISMEN KABUL EDİLDİ / UYGULANDI — ayrı `Hariç tutulanlar` filtresi henüz kararlaştırılmadı.
**Source context:** CG recommendation derived from CG-09; CX UXR-011 confirms current ambiguity.
**Kerem kararı (2026-09-06):** Hariç tutma geri alınabilir olacak. Uygulamada belge `Hariç tutuldu` state'inde korunuyor ve `Kontrole geri al` aksiyonu sunuluyor; ayrıca özel bir filtre gerekip gerekmediğine sonra karar verilecek.

## REV-B04 — Kontrolde tut state'i geri döndürürken provenance eski kalabiliyor
**Status:** KONTROL EDİLECEK.
**Audit refs:** [CG-06](./fisora-chatgpt-accountant-acceptance-audit-2026-09-05.md#cg-06--returning-to-control-did-not-restore-provenance) · [CX validation](./fisora-codex-ux-qa-audit-2026-09-05.md#post-authorization-demo-state-validation)

## REV-B05 — Onay başarı feedback'i yeterli mi?
**Status:** KABUL EDİLDİ / UYGULANDI — production UI doğrulaması bekliyor.
**Audit refs:** [AG FINDING-04](./fisora-antigravity-ux-ui-audit-2026-09-05.md#finding-04-onayla-ve-sonraki-işleminde-kuyruk-rozetinin-güncellenmemesi) · [CX validation](./fisora-codex-ux-qa-audit-2026-09-05.md#post-authorization-demo-state-validation) · [CG-04](./fisora-chatgpt-accountant-acceptance-audit-2026-09-05.md#cg-04--contradictory-workflow-labels)
**Conflict note:** State değişimi CG/CX tarafından görüldü; AG feedback'in kullanıcıya yeterince kesin ulaşmadığını gördü. `Hiç state değişmiyor` şeklinde kabul edilmedi.
**Kerem kararı (2026-09-06):** Yeni toast/modal eklenmeden mevcut alt kısayol barı içinde son işlem açıkça gösterilecek; geri alınabiliyorsa `Geri al / Ctrl+Z` aynı yerde görünecek.
**Implementation refs:** `frontend/app/portal-next/portal-next-workspace-controls.tsx`, `frontend/app/portal-next/portal-next.css`, `frontend/app/features/review/use-review-commands.ts`.

## REV-B06 — `Kontrolde tut` semantiği
**Status:** KABUL EDİLDİ / UYGULANDI — production UI doğrulaması bekliyor.
**Decision source:** 2026-09-06 multi-agent audit review discussion.
**Kerem kararı:** `Kontrolde tut` = bu belge sonradan işlenecek. Hata/terminal state değildir; eksik veya yarım fiş yüzünden bu aksiyonun kendisi bloklanmamalıdır. Onaylanmış belge için aynı geri dönüş davranışı `Kontrole geri al` adıyla sunulur.
**Implementation refs:** `frontend/app/portal-review-panels.tsx`, `backend/app/persistence/normalized_accounting_repository.py`, `frontend/app/features/review/use-review-commands.ts`.

# C — Muhasebe güvenlik kapıları

## REV-C01 — Eksik hesap seçimi varken onay aktif
**Status:** KONTROL EDİLECEK / ÜRÜN KARARI.
**Audit refs:** [CX UXR-003](./fisora-codex-ux-qa-audit-2026-09-05.md#uxr-003--p1--eksik-hesap-seçimi-varken-onay-aktif)
**Question:** Eksik hesap gerçek bir block mu, yoksa müşavir bilinçli şekilde tamamlanmamış kaydı başka state'e taşıyabilmeli mi? `Disable and leave stuck` varsayılan çözüm değildir; recovery/workflow kararı ayrıca verilecek.

## REV-C02 — `Dengeli` etiketi semantik tamamlanmışlık gibi algılanabilir
**Status:** ÜRÜN KARARI.
**Audit refs:** [CX UXR-003](./fisora-codex-ux-qa-audit-2026-09-05.md#uxr-003--p1--eksik-hesap-seçimi-varken-onay-aktif)
**Question:** `Borç/alacak dengeli` ile `Muhasebe kararı tamamlandı` ayrı göstergeler mi olmalı?

## REV-C03 — Tüm fiş satırları görünmeden onay erişilebilir
**Status:** KONTROL EDİLECEK.
**Audit refs:** [CG-08](./fisora-chatgpt-accountant-acceptance-audit-2026-09-05.md#cg-08--not-all-journal-rows-visible-before-approval)

## REV-C04 — 0 TL belge normal posting UX'i izliyor
**Status:** KONTROL EDİLECEK; son deploy sonrası yeniden üretilecek.
**Audit refs:** [CG-10](./fisora-chatgpt-accountant-acceptance-audit-2026-09-05.md#cg-10--zero-value-document-still-follows-normal-posting-ux)

# D — Workflow state dili ve provenance

## REV-D01 — Çelişkili state etiketleri
**Status:** KONTROL EDİLECEK.
**Audit refs:** [CG-04](./fisora-chatgpt-accountant-acceptance-audit-2026-09-05.md#cg-04--contradictory-workflow-labels) · [CX validation](./fisora-codex-ux-qa-audit-2026-09-05.md#post-authorization-demo-state-validation)

## REV-D02 — Sistem taslağını yalnız onaylamak `Manuel fiş girildi` sonucuna dönüşüyor
**Status:** KONTROL EDİLECEK.
**Audit refs:** [CG-05](./fisora-chatgpt-accountant-acceptance-audit-2026-09-05.md#cg-05--approval-changes-provenance-to-manuel-fiş-girildi)

## REV-D03 — Workflow state ve provenance birlikte geri dönmüyor
**Status:** KONTROL EDİLECEK.
**Audit refs:** [CG-06](./fisora-chatgpt-accountant-acceptance-audit-2026-09-05.md#cg-06--returning-to-control-did-not-restore-provenance)

## REV-D04 — Canonical kullanıcı state modeli
**Status:** ÜRÜN KARARI.
**Derived from:** CG-04/05/06 + CX validation + AG FINDING-04.
**Candidate language only:** İşleniyor / Kontrol gerekli / Kontrolde / Onaylandı / Çıktıya hazır / Hariç / Kayıt gerekmiyor / İşlenemedi. Bu liste henüz kabul edilmiş state modeli değildir.

# E — Dönem, mükellef ve ofis scope

## REV-E01 — Ana dönem ile resume dönemi farklı
**Status:** KONTROL EDİLECEK.
**Audit refs:** [CG-07](./fisora-chatgpt-accountant-acceptance-audit-2026-09-05.md#cg-07--period-context-is-ambiguous)

## REV-E02 — Ağustos context'inde Mayıs tarihli belge/fişler
**Status:** KONTROL EDİLECEK / ÜRÜN KARARI.
**Audit refs:** [CG-07](./fisora-chatgpt-accountant-acceptance-audit-2026-09-05.md#cg-07--period-context-is-ambiguous)

## REV-E03 — Yeni Yükleme dönemi üst context ile farklı
**Status:** KONTROL EDİLECEK.
**Audit refs:** [CX UXR-007](./fisora-codex-ux-qa-audit-2026-09-05.md#uxr-007--p1--yeni-yükleme-dönemi-üst-bağlamla-uyuşmuyor) · CG live audit observation.

## REV-E04 — Kontrol/sayaç değerleri ekranlar arasında açıklamasız farklı
**Status:** KONTROL EDİLECEK.
**Audit refs:** [CX UXR-006](./fisora-codex-ux-qa-audit-2026-09-05.md#uxr-006--p1--kontrol-sayıları-bağlamlar-arasında-açıklamasız-çelişiyor) · [AG FINDING-07](./fisora-antigravity-ux-ui-audit-2026-09-05.md#finding-07-üst-bar-ile-gösterge-paneli-arasındaki-metrik-çelişkisi)
**Note:** Farklı scope'lar meşru olabilir; önce hangi sayının hangi scope'u anlattığı doğrulanacak.

## REV-E05 — Mükellef listesi/detail belge sayısı farklı
**Status:** KONTROL EDİLECEK.
**Audit refs:** [CX UXR-008](./fisora-codex-ux-qa-audit-2026-09-05.md#uxr-008--p1--mükellef-liste-ve-detay-sayıları-açıklamasız-farklı)

## REV-E06 — Scope etiketleme modeli
**Status:** ÜRÜN KARARI.
**Derived from:** CX UXR-006/008 + AG FINDING-07 + CG-07.
**Question:** Sayaç yanında mükellef/dönem/ofis scope'u nasıl görünmeli?

## REV-E07 — Dönem kilidi
**Status:** STRATEJİ KARARI.
**Source:** CG audit feature candidate; doğrudan audit bug'ı değildir.

# F — Preview, source anchor ve provenance kanıtı

## REV-F01 — Onay sonrası preview bozulabiliyor
**Status:** KONTROL EDİLECEK.
**Audit refs:** [CG-03](./fisora-chatgpt-accountant-acceptance-audit-2026-09-05.md#cg-03--preview-can-break-after-approval)

## REV-F02 — Kaynak metin görünürken anchor bulunamadı sonucu
**Status:** KONTROL EDİLECEK.
**Audit refs:** [CX UXR-004](./fisora-codex-ux-qa-audit-2026-09-05.md#uxr-004--p1--kaynak-bağlantısı-görünen-belgeyi-bulamıyor)

## REV-F03 — Kaynak detayında eksik/şüpheli metadata
**Status:** KONTROL EDİLECEK.
**Audit refs:** [CX UXR-004](./fisora-codex-ux-qa-audit-2026-09-05.md#uxr-004--p1--kaynak-bağlantısı-görünen-belgeyi-bulamıyor)

## REV-F04 — Canonical source-anchor modeli
**Status:** ÜRÜN KARARI.
**Derived from:** CX UXR-004 + CG-24.
**Question:** Kaynak satırı HTML/PDF reader ve workbench arasında hangi kalıcı kimlikle taşınmalı?

## REV-F05 — Source/provenance UI yaklaşımı
**Status:** ÜRÜN KARARI — güçlü bulunan mevcut yaklaşım korunacak mı?
**Audit refs:** [CG-24](./fisora-chatgpt-accountant-acceptance-audit-2026-09-05.md#cg-24--sourceprovenance-interaction-is-a-strong-product-pattern) · [CX Strongest parts](./fisora-codex-ux-qa-audit-2026-09-05.md#strongest-parts-of-the-product)

# G — Klavye ve seri kullanım

## REV-G01 — F10 / ↑↓ konusunda çelişkili audit sonucu
**Status:** TEKRAR TEST.
**Audit refs:** [AG FINDING-02](./fisora-antigravity-ux-ui-audit-2026-09-05.md#finding-02-f10-ve-yön-tuşları-klavye-kısayollarının-işlevsiz-olması) · [CG-22](./fisora-chatgpt-accountant-acceptance-audit-2026-09-05.md#cg-22--shortcut-behavior-is-focus-sensitive) · [CX Strongest parts](./fisora-codex-ux-qa-audit-2026-09-05.md#strongest-parts-of-the-product)
**Conflict:** CG canlı turunda F10 ve ↑↓ çalıştı; AG çalışmadığını raporladı. Doğrudan bug kabul edilmeyecek.

## REV-G02 — Shortcut focus güvenliği
**Status:** KONTROL EDİLECEK.
**Audit refs:** [CG-22](./fisora-chatgpt-accountant-acceptance-audit-2026-09-05.md#cg-22--shortcut-behavior-is-focus-sensitive)
**Observed:** Dönem select focus'tayken `↓` evrak yerine dönemi değiştirdi.

## REV-G03 — Keyboard focus policy
**Status:** ÜRÜN KARARI.
**Derived from:** CG-22 + AG FINDING-02.

# H — Yeni Yükleme, duplicate ve upload sonucu

## REV-H01 — Duplicate upload kullanıcıya açık sonuç vermiyor
**Status:** KONTROL EDİLECEK.
**Audit refs:** [CG-13](./fisora-chatgpt-accountant-acceptance-audit-2026-09-05.md#cg-13--duplicate-upload-result-is-not-explained-to-the-user)

## REV-H02 — `backend kuyruğu` müşavir dili değil
**Status:** ÜRÜN KARARI.
**Source:** CG-13.

## REV-H03 — Upload sonuç özeti
**Status:** ÜRÜN KARARI.
**Source:** CG feature candidate derived from CG-13.
**Candidate only:** `5 dosya: 3 eklendi · 1 duplicate · 1 hata`.

## REV-H04 — Upload geçmişi raw ISO timestamp
**Status:** KONTROL EDİLECEK.
**Audit refs:** [CG-20](./fisora-chatgpt-accountant-acceptance-audit-2026-09-05.md#cg-20--upload-history-uses-raw-iso-timestamp) · [AG FINDING-07](./fisora-antigravity-ux-ui-audit-2026-09-05.md#finding-07-üst-bar-ile-gösterge-paneli-arasındaki-metrik-çelişkisi) (AG Top-10 ISSUE-07 / timestamp observation)

## REV-H05 — Upload dönemi görünürlüğü/değiştirilebilirliği
**Status:** ÜRÜN KARARI.
**Audit refs:** [CX UXR-007](./fisora-codex-ux-qa-audit-2026-09-05.md#uxr-007--p1--yeni-yükleme-dönemi-üst-bağlamla-uyuşmuyor) · AG Upload workflow scorecard note.

## REV-H06 — Codex file chooser `Not allowed`
**Status:** TEST SINIRLAMASI.
**Audit refs:** [CX Evidence and limitations](./fisora-codex-ux-qa-audit-2026-09-05.md#evidence-and-limitations)
**Decision:** Ürün bug'ı olarak kaydedilmeyecek; CG Windows file picker ile gerçek dosya yükledi.

# I — Hata yönetimi ve teknik metin sızıntısı

## REV-I01 — Öğrenilen Kurallar raw 500
**Status:** KONTROL EDİLECEK.
**Audit refs:** [CG-11](./fisora-chatgpt-accountant-acceptance-audit-2026-09-05.md#cg-11--learned-rules-leaks-raw-backend-error) · [CX UXR-005](./fisora-codex-ux-qa-audit-2026-09-05.md#uxr-005--p1--öğrenilen-kurallar-ekranı-500-hatasını-kullanıcıya-sızdırıyor)

## REV-I02 — Öğrenilen Kurallar raw JSON
**Status:** TEKRAR TEST.
**Audit refs:** [AG FINDING-01](./fisora-antigravity-ux-ui-audit-2026-09-05.md#finding-01-öğrenilen-kurallar-ekranında-ham-json-hatası-render-edilmesi)
**Note:** Exact hata CG/CX build'inde 500 idi; aynı error-mapping ailesi olabilir.

## REV-I03 — QNB endpoint/500 kullanıcıya çıkıyor
**Status:** KONTROL EDİLECEK.
**Audit refs:** [CG-12](./fisora-chatgpt-accountant-acceptance-audit-2026-09-05.md#cg-12--qnb-settings-leak-implementationconfiguration-details)

## REV-I04 — QNB production config key kullanıcıya çıkıyor
**Status:** KONTROL EDİLECEK.
**Audit refs:** CG-12.

## REV-I05 — QNB `active connection is required` kullanıcıya çıkıyor
**Status:** KONTROL EDİLECEK.
**Audit refs:** CG-12.

## REV-I06 — Yanlış şifre feedback'i yok iddiası
**Status:** TEKRAR TEST.
**Audit refs:** [AG FINDING-03](./fisora-antigravity-ux-ui-audit-2026-09-05.md#finding-03-giriş-ekranında-yanlış-şifre-girildiğinde-geri-bildirim-verilmemesi)
**Note:** CG temiz incognito login/reset'i test etti; aynı yanlış-şifre senaryosunu bağımsız doğrulamadı.

## REV-I07 — Ortak user-safe error mapping katmanı
**Status:** ÜRÜN KARARI.
**Derived from:** CG-11/12 + CX UXR-005 + AG FINDING-01/03.

# J — Onay & Çıktılar

## REV-J01 — `Çıktıya hazır 0` iken bazı export butonları aktif
**Status:** KONTROL EDİLECEK.
**Audit refs:** [CX UXR-009](./fisora-codex-ux-qa-audit-2026-09-05.md#uxr-009--p1--çıktı-kontrollerinin-hazır-olma-durumu-birbiriyle-çelişiyor) · [CG-25](./fisora-chatgpt-accountant-acceptance-audit-2026-09-05.md#cg-25--output-readinessprerequisite-ux-is-incomplete)

## REV-J02 — CSV/Kontrol Paketi aktif ama prerequisite mesajında duruyor
**Status:** KONTROL EDİLECEK.
**Audit refs:** CX UXR-009 · CG-25.

## REV-J03 — XLSX bazı durumda disabled
**Status:** KONTROL EDİLECEK.
**Audit refs:** CX UXR-009 · CG-25.

## REV-J04 — Export readiness için canonical gate
**Status:** ÜRÜN KARARI.
**Derived from:** CX UXR-009 + CG-25.

## REV-J05 — Pilot export kapsamı
**Status:** STRATEJİ KARARI.
**Source context:** CG Output assessment + AG Missing Product Capabilities.
**Question:** Pilot için XLSX, CSV, Zirve veya başka bir aktarımın hangisi gerçekten vaat edilecek?

## REV-J06 — Geçmiş çıktı / paket arşivi
**Status:** STRATEJİ KARARI.
**Audit ref:** [AG Missing Product Capabilities](./fisora-antigravity-ux-ui-audit-2026-09-05.md#5-missing-product-capabilities-eksik-ürün-yetenekleri--mali-müşavir-gözüyle)

# K — Muhasebe okunabilirliği ve responsive

## REV-K01 — Türk muhasebe sayı formatı
**Status:** KONTROL EDİLECEK / ÜRÜN KARARI.
**Audit refs:** [AG FINDING-05](./fisora-antigravity-ux-ui-audit-2026-09-05.md#finding-05-türk-muhasebe-standardına-uymayan-rakam-formatı) · CG canlı ekranlarında `238.69`, `1034.33`, `1500.00` doğrulandı.
**Question:** `12.000,00`, `12.000,00 TL` veya `₺12.000,00` standardı hangisi?

## REV-K02 — `12K TL` kısaltması iddiası
**Status:** TEKRAR TEST.
**Audit ref:** AG Top 10 ISSUE-10 / P2 fixes section.

## REV-K03 — Kritik hesap adlarının truncation'ı
**Status:** KONTROL EDİLECEK.
**Audit refs:** [CG-19](./fisora-chatgpt-accountant-acceptance-audit-2026-09-05.md#cg-19--critical-account-text-truncates) · [AG FINDING-06](./fisora-antigravity-ux-ui-audit-2026-09-05.md#finding-06-1366768-laptop-çözünürlüğünde-hesap-adlarının-kesilmesi)

## REV-K04 — 1366×768 account readability
**Status:** KONTROL EDİLECEK.
**Audit refs:** AG FINDING-06 · CG-14.
**Conflict:** CG genel layout'u 100% zoom'da kullanılabilir buldu; AG hesap adı kırpılması gördü.

## REV-K05 — %125 zoom + açık sidebar sıkışması
**Status:** KONTROL EDİLECEK.
**Audit refs:** [CG-14](./fisora-chatgpt-accountant-acceptance-audit-2026-09-05.md#cg-14--125-browser-zoom-with-expanded-sidebar-compresses-accounting-pane)

## REV-K06 — Muhasebe satırı iki satırlı responsive layout
**Status:** ÜRÜN KARARI.
**Source:** AG FINDING-06 recommendation; henüz kabul edilmiş tasarım değildir.

# L — Workbench mikro UX

## REV-L01 — Preview toolbar yoğunluğu
**Status:** ÜRÜN KARARI.
**Audit refs:** [CG-23](./fisora-chatgpt-accountant-acceptance-audit-2026-09-05.md#cg-23--preview-controls-work-but-toolbar-is-dense)

## REV-L02 — `Evrak 12/25` ile `1/3` sayaçlarının anlamı
**Status:** KONTROL EDİLECEK.
**Audit refs:** [CG-18](./fisora-chatgpt-accountant-acceptance-audit-2026-09-05.md#cg-18--queuepage-counters-are-easy-to-confuse)

## REV-L03 — Kuyruk tekrar açılınca selected item'a scroll etmiyor
**Status:** KONTROL EDİLECEK.
**Audit refs:** [CG-17](./fisora-chatgpt-accountant-acceptance-audit-2026-09-05.md#cg-17--reopening-queue-does-not-reveal-current-item)

## REV-L04 — Teknik ID/UUID ağırlığı
**Status:** ÜRÜN KARARI.
**Audit refs:** [CX Working but poor UX](./fisora-codex-ux-qa-audit-2026-09-05.md#working-but-poor-ux) · AG accounting-office observations.

## REV-L05 — Tarih formatlarının tutarsızlığı
**Status:** KONTROL EDİLECEK.
**Audit refs:** CX Working but poor UX · AG Top 10 ISSUE-07 · CG-20.

# M — Mükellefler

## REV-M01 — Türkçe karakter toleranslı arama
**Status:** KONTROL EDİLECEK.
**Audit refs:** [CG-15](./fisora-chatgpt-accountant-acceptance-audit-2026-09-05.md#cg-15--turkish-insensitive-client-search-missing)

## REV-M02 — 0 arama sonucunda `Henüz mükellef yok`
**Status:** KONTROL EDİLECEK.
**Audit refs:** CG-15.

## REV-M03 — Liste/detail scope farkı
**Status:** KONTROL EDİLECEK.
**Audit refs:** CX UXR-008.

## REV-M04 — Hızlı mükellef geçişi / Ctrl+K
**Status:** STRATEJİ KARARI.
**Audit refs:** AG Missing Product Capabilities.

# N — Login / auth

## REV-N01 — Mobil login hero-first
**Status:** ÜRÜN KARARI.
**Audit refs:** [CG-21](./fisora-chatgpt-accountant-acceptance-audit-2026-09-05.md#cg-21--mobile-login-is-hero-first)

## REV-N02 — `Beni hatırla` checkbox görsel problemi
**Status:** TEKRAR TEST.
**Audit refs:** [AG FINDING-08](./fisora-antigravity-ux-ui-audit-2026-09-05.md#finding-08-giriş-ekranındaki-beni-hatırla-hizalama-faciası)

## REV-N03 — Login kırpık logo iddiası
**Status:** TEKRAR TEST.
**Audit refs:** AG FINDING-08.

## REV-N04 — Default login usernames
**Status:** ÜRÜN KARARI.
**Audit refs:** CG clean-incognito login observation; kullanıcı adları `mali-musavir` / `mukellef-user` hazır görünüyordu.

# O — Banka / Diğer Belgeler

## REV-O01 — Boş modüllerin prominence'i
**Status:** ÜRÜN KARARI.
**Audit refs:** [CG-26](./fisora-chatgpt-accountant-acceptance-audit-2026-09-05.md#cg-26--banka--diğer-belgeler-currently-carry-empty-scope)

## REV-O02 — Banka/Diğer Belgeler boşken `İncelenecek Faturalar`
**Status:** KONTROL EDİLECEK.
**Audit refs:** CX Working but poor UX.

## REV-O03 — Banka/Diğer Belgeler'de Alış/Satış kontrolleri
**Status:** KONTROL EDİLECEK.
**Audit refs:** CX Working but poor UX.

# P — AI Ajanları / Okuma Kalitesi / Öğrenme

## REV-P01 — Okuma Kalitesi `Fisora UI satırı oluşmamış`
**Status:** KONTROL EDİLECEK.
**Audit refs:** [CX UXR-010](./fisora-codex-ux-qa-audit-2026-09-05.md#uxr-010--p1--okuma-kalitesi-karşılaştırması-fisora-satırı-üretmiyor)

## REV-P02 — Reader/Fisora satır eşleştirmesi için ortak kimlik
**Status:** ÜRÜN KARARI.
**Derived from:** CX UXR-010 + source/provenance findings.

## REV-P03 — Kalite ölçümü çalışıyor ama bazı belgelerde içerik boş
**Status:** KONTROL EDİLECEK.
**Audit refs:** CX UXR-010 · CG Verified strong areas (`Kalite ölçümünü çalıştır` başarı mesajı görüldü).

# Q — Navigasyon / route / sidebar

## REV-Q01 — Legacy `/portal` ile `/portal-next` sıçraması iddiası
**Status:** TEKRAR TEST.
**Audit refs:** [AG Bilgi Mimarisi ve Rota Sorunu](./fisora-antigravity-ux-ui-audit-2026-09-05.md#bilgi-mimarisi-ve-rota-sorunu)
**Conflict:** CG ana alanları yeni shell içinde kullandı; CX bunu ana kritik olarak bağımsız doğrulamadı. Şimdilik ürün eksiği kabul edilmeyecek.

## REV-Q02 — Route geçişinde sidebar state tutarlılığı
**Status:** KONTROL EDİLECEK.
**Audit refs:** CX Working but poor UX · AG navigation observations.

## REV-Q03 — Dar sidebar tooltip/label yeterliliği
**Status:** ÜRÜN KARARI.
**Audit refs:** CX P2 recommendations.

# R — Feature / strategy candidates — audit bug'ı değildir

## REV-R01 — Tam audit trail
**Status:** STRATEJİ KARARI.
**Source:** CG product capability candidate.

## REV-R02 — Onaylanmış kaydı yeniden açma
**Status:** STRATEJİ KARARI.
**Sources:** CG + AG Missing Product Capabilities.

## REV-R03 — Müşavir notu
**Status:** STRATEJİ KARARI.
**Source:** CG.

## REV-R04 — Multi-user assignment / handoff
**Status:** STRATEJİ KARARI.
**Source:** CG.

## REV-R05 — Gelişmiş belge araması
**Status:** STRATEJİ KARARI.
**Source:** CG.

## REV-R06 — Toplu onay / kontrollü bulk actions
**Status:** STRATEJİ KARARI.
**Sources:** CG + AG Missing Product Capabilities.

## REV-R07 — Hesap planı autocomplete/search
**Status:** TEKRAR TEST / ÜRÜN KARARI.
**Audit refs:** AG Missing Product Capabilities · CG Verified strong areas.
**Conflict:** AG bunu ihtiyaç adayı saydı; CG F2 ile hesap autocomplete'in açıldığını doğruladı. Önce mevcut kapsam ölçülecek.

## REV-R08 — Luca entegrasyonu
**Status:** STRATEJİ KARARI.
**Audit refs:** AG Missing Product Capabilities.
**Note:** AG raporundaki pazar payı iddiası audit içinde kaynaklandırılmadı; `pilot öncesi zorunlu eksik` olarak otomatik kabul edilmeyecek.

## REV-R09 — Zirve doğrudan aktarım
**Status:** STRATEJİ KARARI.
**Source context:** Mevcut UI + CG/AG output değerlendirmeleri.

## REV-R10 — Çıktı paket geçmişi / arşiv
**Status:** STRATEJİ KARARI.
**Audit refs:** AG Missing Product Capabilities.

## REV-R11 — Dönem kilidi
**Status:** STRATEJİ KARARI.
**Source:** CG.

## REV-R12 — Upload progress/final summary
**Status:** STRATEJİ KARARI.
**Source:** CG, duplicate/upload auditinden türetilen feature adayı.

# S — Özel tekrar-test matrisi

| ID | Konu | Audit sonucu |
|---|---|---|
| S01 | F10 | CG/CX çalıştı; AG çalışmadı dedi |
| S02 | ↑↓ evrak geçişi | CG çalıştı; AG çalışmadı dedi; CG focus edge case buldu |
| S03 | Legacy portal | AG var dedi; CG/CX normal ana akışta doğrulamadı |
| S04 | Learned Rules exact hata | CG/CX raw 500; AG raw JSON |
| S05 | Yanlış şifre feedback | AG problem; bağımsız tekrar test gerekli |
| S06 | Approval feedback | State değişimi var; yeterli feedback ürün kararı |
| S07 | 1366 readability | CG genel kullanılabilir; AG account truncation gördü |
| S08 | Account autocomplete | CG mevcut davranış gördü; AG daha güçlü feature istedi |

# T — Görüşme ve karar şablonu

Her konu tek tek şu sırayla kapatılacak:

1. Audit'te tam olarak ne görüldü?
2. Güncel production/demo build'de yeniden üretilebiliyor mu?
3. Bu bir business state mi, integrity bug mı, yalnızca UX tercihi mi?
4. Neden bu state oluşuyor? Root cause nedir?
5. İdeal normal akış ne olmalı?
6. Exceptional safety fallback ne olmalı?
7. Kerem kararı.
8. Kabul edilirse implementation ve acceptance test.

### Decision record template

**REV-ID:**
**Live reproduction:**
**Root-cause finding:**
**Normal product behavior:**
**Exceptional safety behavior:**
**Decision:** KABUL EDİLDİ / REDDEDİLDİ / İYİLEŞTİRME / SONRA / TEKRAR TEST
**Implementation note:**
**Acceptance test:**

## Next discussion

İlk konu `REV-A01/A02/A03/A04`: canonical active-document context ve işlenemeyen belge UX'inin internal integrity failure'dan ayrılması.


---

## Decision note — 2026-09-06 — Review action semantics

Bu not B bölümündeki önceki `KONTROL EDİLECEK / ÜRÜN KARARI` statülerini ürün yönü açısından günceller; implementasyon yapılmış sayılmaz.

**B01 / Undo — KABUL EDİLEN YÖN:** Ctrl+Z zaman penceresine bağlı olmayacak. `Son geri alınabilir review işlemi` işlem bazında tutulacak. İlk öneri: keyboard undo yalnız en son reversible workflow mutation'ını geri alır; bir süre sınırı yoktur. Daha eski bir kaydı değiştirmek için ilgili belge üzerinden açık `Kontrole geri al / Yeniden aç` işlemi kullanılır. Audit geçmişi silinmez; original action + undo/reopen ayrı event olarak saklanır.

**B01 kapsam sınırı:** Ctrl+Z bir input/hesap alanında focus varken metin düzenleme undo'sunu bozmamalı. Global review undo yalnız editable focus dışında devreye girmeli. Upload, export, hard-delete benzeri farklı risk sınıfları review undo stack'ine otomatik sokulmayacak.

**B02 / Onay — KABUL EDİLDİ:** Onaylanmış belge sonradan yeniden kontrol durumuna alınabilir. Onay terminal/geri dönüşsüz state değildir.

**B03 / Kontrolde tut — KABUL EDİLDİ:** `Şimdi karar vermiyorum; sonradan işlenecek` anlamına gelen normal business state'tir. Hata veya dead-end değildir.

**B04 / Hariç tut — KABUL EDİLDİ:** `Bu belgeyi muhasebeleştirmeyeceğiz` anlamına gelir; hard delete değildir. Belge ve geçmiş korunur, gerektiğinde geri getirilebilir. Hariç tutma nedeni isteyip istememe gibi mikro UX kararı ayrıca verilecek.

**B05 / Audit trail — KABUL EDİLDİ:** Onay, undo, yeniden açma, kontrolde tutma, hariç tutma ve geri getirme kim/zaman/belge/eski-yeni state ile audit trail'e yazılacak.

**B06 / Onay feedback — ÖNERİ, HENÜZ KARAR DEĞİL:** Yeni toast/card eklemek yerine mevcut alt kısayol/aksiyon barında tek satırlık `✓ Turkcell · 1.034,33 TL onaylandı · Geri al  Ctrl+Z` son-işlem göstergesi kullanılması öneriliyor. Süreyle kaybolmaz; bir sonraki reversible review işlemiyle yerini yeni son işleme bırakır. Queue görünürse önceki satırın state rozeti de eşzamanlı güncellenir. Ses/modal/pop-up önerilmiyor.

**Undo sonrası önerilen davranış:** Ctrl+Z son onayı geri aldığında o belge yeniden aktif belgeye döner; kullanıcı düzeltme yapabilsin. Bu davranış henüz nihai UI kararı değildir.
