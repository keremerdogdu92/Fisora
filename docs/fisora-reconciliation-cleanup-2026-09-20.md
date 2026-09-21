# Fisora repository reconciliation cleanup — 2026-09-20

## Amaç
2026-09-19 repo reconciliation sırasında Office working copy'den kurtarılan, main'e seçilerek alınan ve hâlâ davranış bazında incelenmesi gereken parçaları tek yerde takip etmek.

Ana hedef: özellik kaybetmeden temiz bir main çizgisine çıkmak; deneyleri archive/tmp altında tutmak; product davranışlarını testlerle sabitlemek; duplicate/legacy yolları kontrollü temizlemek.

Production deploy repo cleanup'tan ayrıdır. Cleanup tamamlanması deploy anlamına gelmez.

## Canonical repo durumu
- Source of truth: origin/main.
- Office ve Home normalde task sonunda local main == origin/main ve git status temiz olmalı.
- Current main before C2 cleanup patch: 7f9a070.
- Production baseline: 829c468. Yeni reconciliation/Harness commitleri deploy edilmedi.

Yakın commit zinciri:
- d6984fb — semantic learned rules Harness resolver.
- ffb6827 — validated learned-rule corrections journal'a otomatik uygulanır.
- de0a486 — 15d310c semantic boundary değişikliğinin revert'i.
- 15d310c — pre-AI semantic candidate narrowing deneyi; REVERT EDİLDİ, reapply edilmemeli.
- 2db12ed — regression contracts.
- 4d9f0b7 — Office'ten seçilerek getirilen mixed rule-learning paketi.
- f7569fa — optional Routeway provider; KALACAK.

## Office dirty-state rescue
Safety branch: archive/office-dirty-20260919, commit 39596d9.

Bu branch tarihsel/deneysel materyali korur: eski v3 Harness, XKIRO plan-fallback deneyleri, ara provider/env değişiklikleri, reconciliation öncesi rule-learning ve geçici UI/backend işleri.

Kesin karar: archive branch wholesale main'e merge edilmeyecek. Gerekirse yalnız tek dosya/hunk karşılaştırılarak gerçekten eksik product davranışı kurtarılacak.

## Deneysel dosya kuralı
Repo-level tmp/ ignored kalır. Benchmark, JSON result, one-off automation, provider deneyi ve diagnostic script burada tutulur. Bir lab sonucu ürün kararı olursa tracked code + tests + docs içine taşınır. Production runtime tmp/ dosyasına bağımlı olmayacak.

## Tekrar açılmaması gereken kararlar
1. Routeway desteği kalacak.
2. Upload contract korunacak: pdf/html/htm/xml; dosya seçilince otomatik upload; ZIP yok.
3. Fixed rule exact hesabı kilitler ve account_code saklar.
4. Semantic rule muhasebe anlamını kilitler; historical/source exact hesap saklamaz; exact current detail account runtime'da güncel chart + invoice row'dan çözülür.
5. Canonical three-stage akış: Planner -> Muhasebeci AI -> normal fiş -> Rule Harness -> rule search/open/applicability -> independent resolved_account -> host mevcut fişle karşılaştırır -> gerekirse correction.
6. Harness semantic resolver Muhasebeci AI'ın mevcut hesap kararını görmez.
7. Learned rule applies değilse Harness kendi başına account seçemez.
8. ffb6827 ve d6984fb ile bu mimari kodlandı ve regression ile doğrulandı.
9. 15d310c pre-AI semantic narrowing yaklaşımı revert edildi; canonical yol değildir.

## Doğrulanan Harness durumu
- targeted: 54 passed / 1 skipped / 0 failed.
- full backend: 1191 passed / 37 skipped / 0 failed.
- real Gemini production-Harness smoke geçti.
- 10k-rule semantic lab stress geçti.

# Kalan cleanup sırası

## C1 — Supplier-wide/general rules — TAMAMLANDI
Örnek: 'Bu firmadan gelen her şey mal alımıdır.'

Canonical kararlar:
- Rule authority client-scoped kalır; aynı mükellef + counterparty bağlamı korunur.
- Purchase/sales yönleri ayrı authority'dir.
- Ordinary supplier-wide davranış değiştirilmedi; historical ordinary broad rule key formatı korunur.
- Return invoice edge case olarak ayrı 'invoice_mode=return' authority'dir. Ordinary rule return faturaya sızmaz.
- Supplier-wide 'all_lines' semantic rule ana anlam authority'sidir; sıradan satır kelimeleri tek başına broad supplier kararını bozmaz.
- Açıkça öğretilmiş 'normalized_terms_all' line-specific rule broad supplier/service rule'dan daha dardır ve yalnız eşleşen satırda üstün gelir.
- Narrow fixed-account + broad semantic conflict'inde narrow fixed exact hesap authoritative sonuçtur; broad semantic diğer satırlarda fallback olarak kalır.
- Utility supplier istisnaları aynı specificity modeliyle ele alınır; vergi/ÖİV/ÖTV/atık su vb. line-specific authority broad utility rule'u yalnız ilgili satırda override edebilir.
- Broad supplier/service authority ile line-specific authority artık aynı rule version identity'sini paylaşmaz; birlikte aktif yaşayabilir.
- Harness aktif kuralları direction + invoice_mode ile filtreler ve host tarafı daha az spesifik rule seçimini validation error ile bloklar.
- ffb6827 + d6984fb fixed-vs-semantic mimarisi değiştirilmedi; correction application/provenance akışı aynı kaldı.

C1 doğrulama:
- targeted learning/Harness/application: 30 passed / 1 skipped / 0 failed.
- full backend: 1195 passed / 37 skipped / 0 failed.
- Deploy yapılmadı.

## C2 — Three-document evidence / repeat learning — TAMAMLANDI
Korunan fikir: aynı muhasebe kararı + 3 gerçekten farklı fatura -> learning prompt.

Canonical kararlar:
- Evidence bir upload/revision değil, distinct commercial document temsil eder.
- Evidence identity sırası kesin olarak: ETTN -> fatura no -> document_ref.
- Aynı ETTN farklı upload/revision/document_ref ile tekrar gelirse tek evidence sayılır.
- ETTN yoksa aynı fatura no farklı upload/revision/document_ref ile tekrar gelirse tek evidence sayılır.
- ETTN ve fatura no yoksa document_ref fallback identity olarak kullanılır.
- Aynı document_ref reprocess/review tekrarında sayaç şişmez.
- issue_date identity değildir; yalnız UI/display evidence tarihidir.
- Repeat-learning eşiği 3 distinct evidence document'tır.
- Müşavirin explicit rule request'i ve office utility precedent akışları 3 evidence threshold'una bağlı değildir.
- evidence_documents UI'ya son 3 distinct evidence olarak taşınmaya devam eder.
- Production three-stage ETTN'nin canonical_invoice.header altında bulunduğu şekil de desteklenir.
- Mevcut historical learning event'ler yeni identity alanları yoksa document_ref fallback ile backward-compatible kalır; data migration yapılmadı.

C2 doğrulama:
- identity targeted: 4 passed / 0 failed.
- learning + review + upload relevant regression: 355 passed / 0 failed.
- full backend: 1198 passed / 37 skipped / 0 failed.
- Deploy yapılmadı.

## C3 — Learning UI cleanup
4d9f0b7 ile gelen 'Fisora bir tekrar fark etti' kartı incelenecek.

Özellikle stale alanlar ayıklanacak: eski Harness 'Uygula / Doğru değil' anlatımı artık happy path değil; ffb6827 sonrası validated corrections otomatik uygulanıyor.

İncelenecek:
- hangi panel gerçekten gerekli?
- hangi CTA stale?
- automatic correction provenance nasıl gösteriliyor?
- repeat-learning prompt ayrı learning UI olarak kalmalı mı?
- status / promptKey / evidenceDocuments / utilityPrecedent / suggestedNote mapping'leri gerçekten kullanılıyor mu?
- duplicate UI var mı?

## C4 — Onayla ve sonraki
Learning prompt çıkınca aynı faturada mı kalmalı, sonraki faturaya mı geçmeli, yoksa yalnız bazı prompt tiplerinde mi durmalı? Karar henüz verilmedi. Önce current behavior çıkarılacak.

## C5 — office_utility_precedent
Cross-client utility knowledge ayrı incelenecek.

Sorular:
- başka client için yalnız suggestion mı?
- automatic rule authority olabilir mi?
- yalnız aynı service_profile için mi?
- counterparty/VKN eşleşmesi gerekiyor mu?
- Rule Harness candidate source'u mu?
- learning UI precedent'i mi?
- tenant/client isolation sınırı ne?

Güvenli default: açık karar verilene kadar cross-client precedent authoritative automatic account rule sayılmayacak.

## C6 — Regression contract cleanup
C6A: 2db12ed ve sonraki semantic backend testlerinde eski direct-semantic varsayımı kalmış mı kontrol et; duplicate/stale testleri ayıkla.
C6B: Learning UI mapping testlerinde status, promptKey, evidenceDocuments, utilityPrecedent, suggestedNote alanlarının gerçekten kullanılan product davranışını koruduğunu doğrula.
C6C: Upload tests learning'den bağımsızdır; korunacak.

## C7 — Legacy direct semantic constraint cleanup
Current code'daki _active_semantic_rule_constraint yolu ayrıca incelenecek.

Doğrudan silme yok. Önce:
1. hangi runtime path çağırıyor?
2. current happy path'te erişiliyor mu?
3. fallback/controlled automation için gerekli mi?
4. tests ne bekliyor?
5. kaldırılırsa feature loss olur mu?

Sonuç: keep / explicit fallback'a daralt / remove seçeneklerinden biri.

## C8 — Archive branch loss audit
En son yapılacak.

Amaç: archive/office-dirty-20260919 içinde kalmış fakat productta gerçekten gerekli olup main'e hiç taşınmamış özellik var mı?

Yöntem:
- wholesale merge yok.
- file/hunk inventory.
- production-path yeni dosyalar özellikle incelenecek.
- eski v3 Harness geri getirilmeyecek.
- XKIRO plan-fallback product kararı verilmeden taşınmayacak.
- provider/env değişiklikleri current provider architecture ile kıyaslanacak.
- UI/backend parçaları current main karşılığıyla karşılaştırılacak.

Üç bucket:
- KEEP IN ARCHIVE
- ALREADY SUPERSEDED
- MISSING PRODUCT BEHAVIOR

Yalnız MISSING PRODUCT BEHAVIOR için yeni değişiklik düşünülecek.

## Cleanup completion gate
Fisora reconciliation ancak şu şartlarda kapanır:
1. C1-C8 kararları tamamlanmış.
2. Stale docs güncellenmiş.
3. Main'de production-path untracked dosya yok.
4. git status temiz.
5. HEAD == origin/main.
6. Full backend regression geçiyor.
7. Gerekli frontend unit/e2e regression geçiyor.
8. Archive branch'ten bilinçsiz merge yapılmamış.
9. Duplicate runtime yollar kaldırılmış veya neden kaldığı dokümante edilmiş.
10. Production deploy durumu repo sync'ten ayrı raporlanmış.

## Çalışma yöntemi
Her madde: inspect -> mevcut davranışı kısa anlat -> problem/conflict göster -> karar -> gerekirse minimal patch -> targeted tests -> relevant full regression -> doc update.

Tamamlanmış Harness Adım 1-4 yeniden yapılmayacak. Kullanıcı onayı olmadan yeni product behavior icat edilmeyecek. Cleanup sırasında feature loss kabul edilmeyecek. Deploy ayrıca istenmedikçe yapılmayacak.

## İlk sonraki görev
C3 — Learning UI cleanup.

C2 three-document evidence davranışı canonical olarak kapatıldı. C3'te stale learning CTA/panel anlatımı, automatic correction provenance ve repeat-learning UI mapping'leri current happy path'e göre incelenecek.
