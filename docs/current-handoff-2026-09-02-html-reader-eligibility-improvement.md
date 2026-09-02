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
