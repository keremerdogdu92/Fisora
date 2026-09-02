# Fisora HTML Reader / Accounting Eligibility Improvement Handoff — 2026-09-02

## Amaç
HTML Source Reader'ı ve source-to-accounting adapter'ı, production'da fiş üretmeyen 11 gerçek HTML örneği üzerinden daha kapsayıcı hale getirmek.

Temel ilke değişmiyor:
- Reader kaynak-faithful ve deterministik kalır.
- Reader muhasebe hesabı, cari hesabı, KDV hesabı veya posting kararı vermez.
- Muhasebe yorumu Planner + Final Accountant işidir.
- Eksik kaynak kanıtında fail-closed davranış korunur.
- PDF pipeline davranışına dokunulmaz.

## Önce okunacak mevcut source-of-truth
HTML lab:
`C:\Users\kerem\Documents\Fisora-HTML-Lab`

Özellikle:
- `docs\current-handoff-2026-08-27-new-html-holdout.md`
- `docs\integration-contract-v1.md`
- `docs\validation-runbook.md`
- `policy\holdout-acceptance.v1.json`
- `freeze\html-source-reader-v1.0.0-20260827.json`

Frozen v1.0.0 geriye dönük baseline olarak korunmalı; değişiklikler önce lab/v-next olarak denenmeli.
## Mevcut production sonucu
Toplam demo belge: 180.
- 168 belge muhasebe taslağı üretti.
- 11 HTML belge Reader'dan geçti fakat accounting eligibility alamadı.
- 1 Mehmet belgesinde Reader + Planner başarılı, XKIRO Final Accountant 27.2 sn sonra failed; bu HTML Reader problemi değildir.

11 belge için kritik ayrım:
- Reader belgeyi tamamen boş okumadı.
- `source_review_rows` içinde gerçek metin/satır benzeri içerik mevcut.
- Fakat accounting adapter'ın istediği frozen `invoice_table_rows` ve/veya explicit current-invoice total evidence oluşmadı.
- Bu nedenle 11/11'de Planner ve Final Accountant hiç çağrılmadı.

Dağılım:
- yalnız `no_frozen_table_rows`: 7
- yalnız `no_explicit_posting_basis`: 2
- ikisi birden: 2

`html_accounting_eligibility()` şu anda iki şart arıyor:
1. `invoice_table_rows` boş olmamalı.
2. `printed_summary_lines` içinde açık current-invoice total label bulunmalı (`ODENECEK`, `FATURA TOPLAMI`, `GENEL TOPLAM`, vb.).

`build_html_accounting_source_package()` yalnız snapshot section `kind == "table"` ise accounting row üretiyor; serbest/fragmented text sections source review'da görünse bile accounting row'a dönüşmüyor.
## 11 gerçek failure örneği
APEX:
- `1750331214_01S2026000837039.html` — `no_frozen_table_rows`
- `1750331214_01S2026001190430.html` — `no_frozen_table_rows`
- `8770013406_0012026117599963.html` — `no_frozen_table_rows`

Arif:
- `1790617537_BEF2026002324731.html` — `no_explicit_posting_basis`
- `9250353261_N3F2026000679218.html` — `no_frozen_table_rows`
- `1790617537_BEF2026002228532.html` — iki neden birden
- `1750331214_01S2026001006191.html` — `no_frozen_table_rows`
- `9250353261_N3F2026000523334.html` — `no_frozen_table_rows`
- `1790617537_BEF2026002228563.html` — iki neden birden
- `1790617537_BEF2026001512182.html` — `no_explicit_posting_basis`

Rana:
- `4810577635_AS02026001117428.html` — `no_frozen_table_rows`

Telekom örneklerinde Reader metin olarak tarife, KDV, ÖİV, telsiz ücreti ve fatura/ödenecek tutarı görebiliyor; sorun bunların frozen structural table/label-value contract'a güvenli taşınmaması.
Elektrik örneklerinde gerçek enerji satırları bazen table olarak mevcut; fakat açık toplam label-value evidence eksik kalabiliyor.
## Çalışma planı
1. Bu 11 HTML'nin orijinal source DOM/HTML yapısını ve frozen v1.0.0 snapshot'ını yan yana incele.
2. Sorunları vendor adıyla değil structural family olarak grupla.
3. `no_frozen_table_rows` için hangi HTML yapısının gerçek satırları table dışına düşürdüğünü belirle.
4. `no_explicit_posting_basis` için literal toplam label/value bilgisinin DOM'da nerede bulunduğunu ve evidence katmanında neden kaybolduğunu belirle.
5. Çözümü Reader/source projection seviyesinde genelleştir; muhasebe semantiği ekleme.
6. Önce bu 11 örnekte A/B çalıştır ve source-faithfulness audit yap.
7. Sonra eski frozen corpus ve holdout regresyonlarını çalıştır.
8. Yeni davranış gerçekten genellenebilir ise v-next release/freeze adayı üret; production'a doğrudan hot-patch yapma.

## Kabul kriterleri
- 11 örneğin mümkün olanlarında literal kaynak satırları kayıpsız structural contract'a taşınmalı.
- Yanlış tablo/satır icat edilmemeli.
- Toplam evidence yalnız kaynakta açıkça bulunan label/value üzerinden gelmeli; toplam hesaplama veya muhasebe çıkarımı yapılmamalı.
- 1,327 eski corpus parse/regression başarısı bozulmamalı.
- Son 598 genuine-new holdout'ta crash/contract regression oluşmamalı.
- Security/edge/robustness testleri tekrar geçmeli.
- PDF pipeline'da davranış değişmemeli.

## UI kararı
Reader karşılaştırması normal Fatura İşleme ekranına eklenmeyecek.
Ayrı müşavir-demo sayfası olacak: `Okuma Ajanı Karşılaştırması`.
Orada ileride orijinal belge / frozen Reader snapshot / Fisora source rows ve mümkünse aynı faturanın PDF-vs-HTML karşılaştırması gösterilecek.
Normal günlük muhasebe ekranı bu diagnostic içerikle değiştirilmemeli.
## Yeni sohbet başlangıç mesajı

```text
Fisora HTML Source Reader / accounting eligibility iyileştirmesine kaldığımız yerden devam ediyoruz.

ÖNCE şu handoff'u oku ve source-of-truth kabul et:
docs/current-handoff-2026-09-02-html-reader-eligibility-improvement.md

Ayrıca HTML lab'daki frozen source-of-truth dosyalarını oku:
C:\Users\kerem\Documents\Fisora-HTML-Lab\docs\current-handoff-2026-08-27-new-html-holdout.md
ve handoff'ta listelenen integration contract / validation / policy / freeze dosyaları.

Production'da 11 HTML belge Reader tarafından okunuyor ama accounting eligibility alamıyor. Bunlar muhasebe AI hatası değil; 11/11'de Planner ve Final hiç çağrılmadı. Dağılım: 7 yalnız `no_frozen_table_rows`, 2 yalnız `no_explicit_posting_basis`, 2 ikisi birden.

Önce bu 11 orijinal HTML'yi ve mevcut frozen snapshot'larını source-level incele. Vendor-specific hack yazma. Sorunları structural family olarak grupla ve Reader/source projection'ı kaynak-faithful biçimde genelleştir.

Reader'a muhasebe mantığı, hesap seçimi, cari kararı, KDV hesabı veya posting yorumu ekleme. Explicit total yalnız kaynakta literal label/value varsa evidence olsun. PDF pipeline'a dokunma.

Önce 11 örnekte A/B ve source audit yap; sonra 1,327 frozen baseline + 598 new holdout + regression/security/edge/robustness testlerini çalıştır. Production'a ancak sonuçları gösterip v-next davranışını netleştirdikten sonra geçelim.

Normal Fatura İşleme UI'ını Reader karşılaştırması için değiştirme; bu iş ileride ayrı `Okuma Ajanı Karşılaştırması` müşavir-demo sayfasında gösterilecek.
```

## 2026-09-03 v-next doğrulama güncellemesi
Bu bölüm önceki handoff'un üzerine authoritative durum güncellemesidir.

Çalışma izolasyonu:
- Worktree: `C:\Users\kerem\Documents\Fisero-html-eligibility-vnext`
- Branch: `html-eligibility-vnext-20260902`
- Production'a deploy/hot-patch yapılmadı.
- Frozen HTML Source Reader v1.0.0 değiştirilmedi.
- PDF pipeline dosyaları değiştirilmedi.

Kök nedenler source-level olarak doğrulandı:
1. Frozen Reader `key_value` ve `fragmented` source rows'u koruyordu; eski accounting adapter yalnız `kind == "table"` satırlarını `invoice_table_rows` içine projekte ediyordu.
2. Literal current-invoice totals bazı HTML'lerde aynı hücrede, bazı HTML'lerde komşu tablo hücrelerinde, bazı HTML'lerde ise komşu DOM text parçalarında basılıydı; semantic evidence yalnız exact 2-cell label/value satırlarını kabul ettiği için bu totals kayboluyordu.
3. Machine/QR facts kaynak kimlik evidence olarak yararlı olsa da literal posting-basis label yerine sentetik `ODENECEK TUTAR` üretmek source-faithful kabul edilmedi ve kaldırıldı.

v-next davranışı:
- Bütün frozen section rows accounting source package'a sıra/provenance korunarak taşınır.
- `table` rows `posting_candidate`, `key_value`/`fragmented` rows `informational` olarak source-structure seviyesinde işaretlenir.
- Final Accountant bütün frozen rows'u sequential `SATIR N: [SOURCE section:row] ...` biçiminde görür.
- Literal totals yalnız source'taki label/value yapısından çıkarılır; arithmetic/reconciliation/inference yoktur.
Ek structural hardening:
- Paralel `<br>` label/value listeleri yalnız iki hücrede segment sayıları eşitse hizalanır; corpus'ta 11 dosyada 22 literal total pair üretti.
- Aynı table cell içindeki `label -> ':' -> value` DOM chunk adjacency ayrı kanal olarak korunur; corpus'ta 17 dosyada 34 literal total pair üretti.
- Global table-içi chunk adjacency kullanılmaz; farklı hücreler arası yanlış label/value çapraz eşleşmesi kapatıldı.
- Rana enerji örneğinde yanlış `FATURA TUTARI = 226,50` eşleşmesi kaldırıldı; yalnız gerçek `FATURA TUTARI = 279,10` ve `ÖDENECEK TUTAR = 280,00` evidence kaldı.
- HTML Final Accountant source text'i, `row_decisions.source_position` için yalnız sequential `SATIR N` ordinalinin kullanılacağını; `[SOURCE section:row]` değerinin provenance olduğunu açıkça belirtir. PDF/Final global prompt değiştirilmedi.

Final corpus doğrulaması:
- Toplam corpus: 2.120 HTML = 1.327 frozen baseline + 598 genuine holdout + Downloads'tan SHA-256 dedupe sonrası 195 gerçekten yeni blind HTML.
- Accounting eligibility: 2.120/2.120.
- Source missing: 0.
- Extraction error: 0.
- Lossless row count: 2.120/2.120.
- Exact frozen source-text projection: 2.120/2.120, mismatch 0.
- Yeni 195 blind corpus Reader sonucu: 195/195 parse; 0 crash, 0 contract-invalid, 0 zero-row, 0 low-confidence, 0 suspicious.
- Yeni blind corpus 14 yeni generalized structural family getirdi.

Reader/frozen kapıları:
- regression 59/59
- security 7/7
- edge 10/10
- robustness 8/8
- mutation 500/500
- public API 7/7
- freeze verify 20/20
- `npm run release:gate`: PASS
Gerçek Planner -> Final Accountant kapısı:
- Test grubu: 11 eski production failure + Downloads'taki 14 yeni structural-family temsilcisi = 25 vaka.
- Provider chain: Gemini Planner + XKIRO Final.
- Provider completed: 25/25.
- Final row coverage: 25/25 valid.
- Balanced journal result: 25/25.
- Posting-basis amount doğrudan literal printed summary değerine eşleşen: 24/25.
- Tek non-literal vaka `family14::0111.html`: 173,09 = basılı 173,25 cari toplam - basılı 0,16 önceki ay devreden; bu Final Accountant kontratında izin verilen source-grounded arithmetic'tir.
- Eski 11 gerçek kalite grubunda provider completed 11/11, coverage valid 11/11, balanced 11/11 ve kullanılan chart code'larda invalid case 0.
- Eski 11 kalite grubunun posting-basis amount'larının 11/11'i kaynakta literal bir printed summary değerine eşleşti.
- Rana stacked-energy vakası sequential 3/3 ve parallel 3/3 tekrar testinde coverage valid + balanced kaldı; posting basis üç tekrarda da 279,10 seçildi.
- `family14::0111.html` SATIR/provenance açıklamasından sonra 3/3 tekrar testinde `source_position` tam `1..13` oldu; 3/3 coverage valid ve balanced.

Backend kapısı:
- Full backend suite: 1.130 PASS / 34 SKIP / 0 FAIL.
- İlk worktree test koşularındaki XML/tax failure'ları yalnız eksik `private_samples/real_pilot` test mount'undan kaynaklandı; doğru junction ile suite tamamen yeşil geçti.
- Test junction'ı doğrulama sonrası kaldırıldı; ana `Fisero/private_samples/real_pilot` kaynağı korunuyor.
- Product diff yalnız HTML semantic evidence, HTML source/accounting adapter ve ilgili HTML testleri + bu handoff ile sınırlıdır.
- PDF pipeline dosyaları değiştirilmedi.
- Normal Invoice Processing UI değiştirilmedi.
- Production'a deploy/hot-patch yapılmadı.

Release durumu:
- HTML source/eligibility değişikliği local v-next release candidate seviyesindedir.
- Frozen Reader v1.0.0 baseline olarak aynen korunur.
- Production'a geçiş ayrı deploy kararıdır; bu handoff production deploy yapıldığı anlamına gelmez.
Ek AI stabilite notu:
- `9250353261_N3F2026000523334.html` üç bağımsız tekrar testinde 3/3 `Ara Toplam = 433,65` current-invoice basis seçti; 3/3 coverage valid ve balanced.
- Bu vaka `FATURA TUTARI = 433,75`, `Ara Toplam = 433,65` ve `Önceki Aydan Devreden = 0,13` değerlerini birlikte basar; Final üç tekrarda da basılı `Ara Toplam`ı cari dönem basis olarak kullandı.
