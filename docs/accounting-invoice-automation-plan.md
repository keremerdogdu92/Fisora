# Fatura Yonu, Hesap Plani ve Musavir Gerekcesi Plani

Bu dokuman fatura yonu, hesap plani secimi ve musavir gerekcesi isini repo icinde izlemek icin eklendi. Her faz tamamlandiginda durum, uygulanan kararlar, gecen testler ve acik isler burada guncellenecek.

## Faz Takibi

| Faz | Durum | Kapsam | Not |
| --- | --- | --- | --- |
| Faz 1 | done | Dogru kimlik, yon tespiti ve musavir gerekcesi | TCKN/VKN ayrimi, fatura yonu, iade dislama, UI yon bazli panel |
| Faz 2 | done | Hesap plani, KDV ve cari onerisi | 600/391, 153 veya 7xx/191, %0/3065, yeni 120/320 cari onerisi |
| Faz 3 | in_progress | Ortak bilgi havuzu ve operasyonel gorunurluk | Pilot provider Tavily; otomatik research sadece belirsiz faturalarda calisir |

## Kararlar

- Vergi levhasi profilinde `tckn`, `vkn`, `identity_type`, `tax_identifier`, `legal_name`, `trade_name`, `display_title`, `tax_office`, `nace_code`, `activity_description`, `workplace_addresses` alanlari ayrik tutulacak.
- Eski `tax_id` alani geriye uyumluluk icin korunacak; yeni karar motoru `vkn` varsa onu, yoksa `tckn` degerini kullanacak.
- Fatura yukleme sekmesi niyet/filtredir; icerik karari kazanir.
- Iade faturasi sinyali varsa otomatik fis uretilmez, kontrol kuyrugunda kalir.
- Satis fisinde gelir hesabi ve `391`, alis fisinde gider/stok hesabi ve `191` kullanilir. Ayni panelde gelir ve gider hesabi beraber gosterilmez.
- `%0` satis KDV satiri uretmez; gelir `%0 / 3065` gelir hesabina yonlenir. Hesap bulunamazsa mustavirden kural olarak secim alinacak.
- Her alis ve satista yeni cari onerisi uretilir. Mevcut eslesme varsa mevcut cari aday olarak korunur, ama yeni cari onerisi de gorunur.

## Faz 1 Uygulama Notlari

- Baslangic: Bu plan dosyasi repoya eklendi.
- Durum: done.
- Uygulandi:
  - Vergi levhasi extraction payload'i TCKN/VKN/title/tax office/address/NACE alanlarini ayri tasiyor; eski `tax_id` korunuyor.
  - GIB kolon layout'u icin ORHAN benzeri satir duzeninden TCKN, unvan, vergi dairesi, adres ve NACE ayriliyor.
  - Fatura yonu `return_review`, `purchase`, `sales` olarak sonuc payload'ina yaziliyor.
  - Iade sinyali otomatik fis uretimini durdurup review'a aliyor.
  - Worker pipeline `direction_detected`, `direction_conflict_detected`, `vat_summary_parsed`, `accounting_explanation_ready` adimlarini kaydediyor.
  - UI fis panelinde satis ve alis hesaplari ayrildi; ustte `AI muhasebe gerekcesi` gorunur.
- Gecen hedef testler: `python -m unittest backend.tests.test_tax_certificates backend.tests.test_phase0_domain`, `python -m unittest backend.tests.test_workflow_store`, `node --test frontend/app/workspace-api.test.cjs`, `cd frontend && npm.cmd run build`.

## Faz 2 Uygulama Notlari

- Durum: done.
- Uygulandi:
  - Account selection artik `600`, `%0/3065`, `391`, `120`, `320`, `191`, `153/7xx` yonlerini ayri tasiyor.
  - Hesap plani detay hesaplari `purchase_stock`, `purchase_expense`, `purchase_vat`, `sales_revenue`, `zero_vat_revenue`, `sales_vat`, `customer`, `supplier` aday gruplariyla ve kisa gerekceyle payload'a ekleniyor.
  - Satis faturasi temel fisleri `120 + 600 + 391` ile kuruluyor.
  - `%0` satislarda `600.00.3065` gelir hesabi kullaniliyor ve KDV satiri yazilmiyor.
  - Alis faturasi temel fisleri faaliyet siniflandirmasina gore `153.*` stok veya `7xx` gider + `191` + `320` ile devam ediyor; satis alanlari bos kaliyor.
  - Her yonde yeni cari onerisi payload'a `suggested_counterparty_account` ve `counterparty_creation_suggestion` olarak giriyor.
  - UI fis panelinde hesap ve cari adaylari dropdown olarak secilebiliyor.
  - Learning rule altyapisi mevcut hesap/cari duzeltme akisi uzerinden calismaya devam ediyor.

## Faz 3 Uygulama Notlari

- Durum: partial_done.
- Uygulandi:
  - Mevcut NACE research cache'i worker tarafinda kullanilmaya devam ediyor.
  - Ortak marka cache modulu eklendi: cache hit varsa researcher cagrilmiyor; Blendax gibi genel marka icin statik profil uretilebiliyor.
  - JSON ve Postgres store marka research profilini save/get edebiliyor.
  - Pipeline teknik timeline structured payload ile yeni karar adimlarini tasiyor.
- Acik isler:
  - Tavily research provider pilotta belirsiz faturalara otomatik baglandi; canli env ve server readiness deploy oncesi ayrica dogrulanacak.
  - Marka/model ayrimini satir parser'ina baglama.
  - Mustavir geri bildirimiyle NACE/marka aciklamasi duzeltme arayuzu.
  - AI provider/model kalitesi icin ayni gercekci belge, ekstre ve research case setini model-model benchmark etme; secimi maliyet, JSON uyumu, dogruluk ve mustavir is yuku etkisine gore yapma.
  - Bilgi Havuzu benchmark ekranini netlestirme: mevcut hali research cache kalitesini olcer; bos cache veya eksik profil durumunda sonucun neden dusuk/0 gorundugunu mustavire debug dili kullanmadan anlatma.

## Sonraki Faz Notlari

- Model duzeyi marka/model ayrimi ilk uc faz disinda kalir.
- Mevcut belgeleri otomatik yeniden isleme ilk uc faz disinda kalir. Sonraki faz: secili belgeyi yeniden isle.
