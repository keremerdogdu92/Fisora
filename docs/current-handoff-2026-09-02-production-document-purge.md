# Fisora Production Document-Only Purge Handoff — 2026-09-02

## Amaç
Production demo verisini belge seviyesinde sıfırlamak; mükellefleri ve onboarding desteğini korumak.

Hedef son durum:
- 5 mükellef kalsın.
- Vergi levhaları kalsın.
- Hesap planları kalsın.
- Admin / müşavir erişimleri kalsın.
- Yalnız mevcut 180 faturaya bağlı tüm operasyonel belge verisi silinsin.

Korunacak 5 client:
- `mehmet-aydogan-30628755006` — 60 belge
- `apex-isitme-cihazlari-ltd-sti` — 30 belge
- `arif-san-29021276942` — 30 belge
- `omer-yagci-45661316282` — 30 belge
- `rana-isitme-cihazlari-ltd-sti` — 30 belge

## Kritik production durumu
Otomatik belge retention şu anda KAPALI.
- Commit: `aaf2cf5 Add retention disable switch for document worker`
- Production env: `FISORA_WORKER_RETENTION_ENABLED=false`
- Worker restart sonrası `document_retention` çalışmadığı doğrulandı.
- Kullanıcı tekrar açıkça isteyene kadar retention açılmamalı.
## Yapılmış dry-run / doğrulama
Production DB preview mevcut 180 workflow ref'inin normalized kimliklerle birebir eşleştiğini doğruladı:
- workflow refs: 180
- normalized documents: 180
- unique document ids: 180
- unmatched refs: 0
- source_files: 180
- document_sources: 180
- document_source_snapshots: 180
- processing_jobs: 180
- ai_attempts: 507
- invoice_lines: 326
- journal_revisions: 40
- workflow_events: 349
- retention_batch_sources: 150
- document_ai_artifacts: 0

Bu nedenle purge tenant-geneli değil, bu 180 `document_ref` / normalized `document_id` graph'ına scoped olmalı.

## Kullanılmaması gereken yollar
- `reinitialize_pilot_data()` kullanılmamalı: taxpayers, chart accounts, client users ve protected corpus/rules dahil fazla geniş veri siliyor.
- `delete_client_documents()` tek başına kullanılmamalı: workflow katmanını temizliyor fakat normalized graph'ın tamamını temizlediği garanti değil.
- UI boş göründü diye başarılı kabul edilmemeli.

## Purge kapsamı
Belgeye bağlı aşağıdaki kayıtlar gerektiği sırayla temizlenmeli:
workflow `uploaded_document/document/processing_job/document_pipeline_event`, normalized processing attempts/jobs, AI attempts, source snapshots, invoice lines, journal graph, workflow events, retention links, document_sources, source_files ve documents.
## Henüz tamamlanmayan güvenlik kontrolü
Protected corpus bağlantı kontrolü başlatıldı fakat ilk read-only probe `reference_outcome_versions.source_document_id` diye var olmayan bir kolon kullandığı için durdu.
Doğru şema:
- `protected_corpus_items.document_id` -> `documents.id` (`ON DELETE SET NULL`)
- `protected_corpus_items.source_file_id` -> `source_files.id` (`ON DELETE SET NULL`)
- `reference_outcome_versions.source_journal_revision_id` -> `journal_revisions.id` (`ON DELETE SET NULL`)
- `reference_outcome_versions.source_review_decision_id` -> `review_decisions.id` (`ON DELETE SET NULL`)

Purge'dan ÖNCE bu 180 belgeye bağlı protected corpus item/reference/rule olup olmadığı doğru kolonlarla read-only sayılmalı. Varsa otomatik silme yapılmamalı; protected veri korunarak detach stratejisi belirlenmeli.

## Güvenli uygulama sırası
1. Production HEAD/env/worker durumunu read-only doğrula.
2. Retention'ın hâlâ `false` olduğunu doğrula.
3. 180 ref -> 180 normalized document eşleşmesini yeniden doğrula.
4. Protected reference sayımlarını doğru şemayla tamamla.
5. Purge planını transaction/dry-run olarak tablo bazında say.
6. Raw source path'lerini 180 belgeyle sınırlandır ve storage root dışına çıkmadığını doğrula.
7. Transaction içinde relational graph'ı FK sırasıyla temizle.
8. Transaction commit sonrası yalnız doğrulanmış 180 raw source dosyasını sil.
9. Post-check: 5 client/chart/tax onboarding korunmuş, belge graph'ı 0 olmalı.
10. Production UI'da her client'ın belge listesi boş görünmeli.

Docker compose çalıştırılacaksa project adı açıkça `-p fisora` kullanılmalı. Yanlışlıkla oluşmuş `app-*` stack daha önce tamamen temizlendi; mevcut `fisora-*` stack sağlıklı kaldı.
## Yeni sohbet başlangıç mesajı

```text
Fisora production demo belge temizliğine kaldığımız yerden devam ediyoruz.

ÖNCE şu dokümanı oku ve source-of-truth kabul et:
docs/current-handoff-2026-09-02-production-document-purge.md

Hedef: production'daki mevcut 180 faturayı ve yalnız bu faturaya bağlı bütün workflow + normalized + source/snapshot + AI/job + journal kayıtlarını tamamen temizlemek.

KESİNLİKLE KORU:
- 5 mevcut mükellef
- vergi levhaları / onboarding attachment'ları
- hesap planları
- admin ve müşavir erişimleri
- protected accountant reference/rule verileri

Retention production'da `FISORA_WORKER_RETENTION_ENABLED=false`; ben tekrar aç diyene kadar açma.

Önce read-only kontrolleri tamamla. Özellikle unfinished protected corpus/reference bağlantı kontrolünü doğru DB kolonlarıyla yap. 180 workflow ref = 180 normalized document birebir eşleşme tekrar doğrulanmadan DELETE yapma.

Sonra güvenli document-only purge'u uygula, raw source dosyalarını yalnız doğrulanmış path'lerden sil ve post-check'te 5 client/support korunurken bütün belge graph'ının 0 olduğunu göster. Tenant genel reset kullanma. Gereksiz accounting davranışı değiştirme.
```

## Tamamlanma kaydı — 2026-09-02
Production document-only purge tamamlandı.

Uygulanan scope:
- target tenant: `36b0dedc-67f2-5d4a-8c67-355fcb8bea97`
- 5 client / 180 workflow ref / 180 normalized document / 180 source file
- protected corpus/reference/rule bağlantıları purge öncesi doğru kolonlarla `0` doğrulandı
- 180/180 processing job `completed` durumundaydı

Silinen ana graph:
- 180 documents, 180 source_files, 180 document_sources, 180 source snapshots
- 180 processing_jobs, 180 processing_attempts, 507 ai_attempts
- 326 invoice_lines, 40 journal_entries, 40 journal_revisions, 135 journal_revision_lines
- 349 document-linked workflow_events, 150 retention_batch_sources
- workflow: 180 uploaded_document, 180 document, 180 processing_job, 1731 document_pipeline_event
- 180 document-linked operation_event

Raw source:
- 180 path güvenli root altında ve benzersizdi
- 88 source daha önce fiziksel olarak silinmiş ve normalized `deleted` durumundaydı
- kalan 92 doğrulanmış exact path commit sonrasında silindi; `92 deleted / 0 remaining`
Post-check:
- document graph tabloları target tenant için `0`
- document-linked workflow event: `0`
- review/document AI/identity/provider/status/safety/edit/allocation/export-item bağlantıları: `0`
- 5 client, 5 taxpayer, 3385 chart account korundu
- 5 onboarding attachment DB kaydı ve 5/5 fiziksel attachment korundu
- portal user `1`, auth credential `1`, auth session `3`, auth token `3` korundu
- protected corpus `1` korundu; protected item/reference/rule sayıları mevcut haliyle `0`
- diğer tenantlardaki 3 workflow document / 3 normalized document / 3 source file korunmuş durumda

Bilinçli olarak korunan document dışı kayıtlar:
- 7 `workflow_events`: tamamı `raw_sources_deleted_for_period`, `document_id = NULL`
- 6 `operation_event`: 5 onboarding attachment upload + 1 document retention preview
- 169 `ai_usage_event`: document ref/id taşımayan client/tenant seviyesinde usage kayıtları; document-only purge kapsamında silinmedi

Retention hâlâ kapalı:
- production env: `FISORA_WORKER_RETENTION_ENABLED=false`
- worker env: `false`
- kullanıcı yeniden açıkça isteyene kadar açılmamalı.
