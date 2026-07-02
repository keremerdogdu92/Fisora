# Fatura Yonu, Hesap Plani ve Musavir Gerekcesi Plani

Bu dokuman fatura yonu, hesap plani secimi ve musavir gerekcesi isini repo icinde izlemek icin eklendi. Her faz tamamlandiginda durum, uygulanan kararlar, gecen testler ve acik isler burada guncellenecek.

## Faz Takibi

| Faz | Durum | Kapsam | Not |
| --- | --- | --- | --- |
| Faz 1 | done | Dogru kimlik, yon tespiti ve musavir gerekcesi | TCKN/VKN ayrimi, fatura yonu, iade dislama, UI yon bazli panel |
| Faz 2 | done | Hesap plani, KDV ve cari onerisi | 600/391, 153 veya 7xx/191, %0/3065, yeni 120/320 cari onerisi |
| Faz 3 | done | Ortak bilgi havuzu ve operasyonel gorunurluk | AI research query, global cache ve Tavily siniri baglandi |
| Faz 4 | done | Research sonucu ile fis kararini yeniden kurma | Dusuk guven export'u acmaz, ama dengeli review taslagi korunur |
| Faz 5 | done | Karisik KDV satir ayrimi | Cihaz %0/3065 kalir, aksesuar/pil satiri KDV'li kalabilir |
| Faz 6 | done | Dogal dil musavir kural adayi | Not ve kural talimati review payload'ina baglandi |
| Faz 7 | done | Portal karar zinciri gorunurlugu | Fis satirlari onde, karar/gerekce ve duzeltme notu alt akis oldu |
| Faz 8 | next | Cok mukellefli gercek belge matrisi | Canli deneme ve private sample matrix ile genisletilecek |

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

- Durum: done.
- Uygulandi:
  - Mevcut NACE research cache'i worker tarafinda kullanilmaya devam ediyor.
  - Ortak marka cache modulu eklendi: cache hit varsa researcher cagrilmiyor; Blendax gibi genel marka icin statik profil uretilebiliyor.
  - JSON ve Postgres store marka research profilini save/get edebiliyor.
  - Pipeline teknik timeline structured payload ile yeni karar adimlarini tasiyor.
  - AI once marka/model icin soruluyor; AI `needs_research` derse Tavily/global research katmani devreye giriyor.
  - Research bir belge icin sinirli calisir ve ayni marka/model/global ifade tekrar geldiyse cache sonucu kullanilir.
  - Research profili muhasebe etkisi guvenini de tasir; dusuk guven export'u acmaz.

## AI-First Muhasebe Motoru Stratejisi

- Urun hedefi AI'i kismak degil, soguk baslangicta muhasebe motorunu
  hizlandirmaktir:
  - AI fatura satirini, mukellef NACE/faaliyet baglamini, hesap plani
    adlarini, cari adaylarini ve gerekirse research sonucunu birlikte okuyup
    export-ready kalitesine yakin fis taslagi hazirlamalidir.
  - Baslangicta review kapisi, mustavire isi yeniden yaptirmak icin degil,
    AI/motor onerilerini hizlica gormesi, duzeltmesi ve guveni artirmasi icin
    vardir.
  - Onaylanan veya duzeltilen fisler learning event olur; tekrar eden benzer
    kalemlerde motor ayni yorumu AI/research'e tekrar sormadan kullanmaya
    calisir.
  - Maliyet ve hiz hedefi: AI/research ilk anlamlandirma ve belirsiz/karmasik
    kalemler icin kullanilir; guvenilir ogrenilmis kural, chart semantic map
    veya cache olustuktan sonra ayni soruyu tekrar sormaz.
- AI'in gorevi sadece "belirsizse sor" degildir:
  - Yeni mukellef veya zayif gecmis veride AI aktif yardimci katman olarak
    calisir.
  - Fatura satirindan urun/hizmet anlami cikarmak, NACE/faaliyet ile
    iliskisini yorumlamak, hesap planindaki uygun adaylari siralamak ve
    cari/hizmet/stock niyetini aciklamak AI'in ana isidir.
  - Deterministik motor tutar, KDV, borc/alacak dengesi, hesap ailesi
    guardrail'i ve export kapisini kontrol eder; AI bu kesin kontrolleri
    ezemez.
- Beklenen kullanici deneyimi:
  - Mustavir bos form doldurmaz; mumkun oldugunca dolu fis taslagi gorur.
  - Review ekraninda "bu neden 153/600/191/320 oldu" aciklamasi gorunur.
  - Mustavir onayladikca ayni tip kararlar daha guvenli ve daha az AI
    maliyetli hale gelir.

## 2026-06-29 Hesap Plani ve AI Karar Kapisi

- Kesin muhasebe kurallari AI tarafindan ezilmeyecek:
  - Isitme cihazi satisi her zaman `%0 / 3065` kabul edilir.
  - Isitme cihazi satisi KDV'li gelirse otomatik duzeltilmis kabul edilmez; `hearing_device_vat_should_be_zero` gerekcesiyle mustavir incelemesine duser.
  - Yeni cari acilacaksa kod sira numarasi yerine `120.<VKN/TCKN>` veya `320.<VKN/TCKN>` olarak onerilir.
- Satir bazli hesap plani secimi firma hesap planina gore yapilacak:
  - Pil, kalip ve montaj kit alislari stok tarafinda kalir ve `153` alt hesap adaylari icinden en uygun detay hesaba iner.
  - Kargo/nakliye satirlari stok maliyetine yazilmaz; `760/770/740` icindeki kargo gideri detay hesabi aranir.
  - Arac kiralama, HGS ve benzeri arac giderleri genel kira hesabina sapmadan ilgili `760` alt hesabina inmeye calisir.
- AI ve motorun devreye girme sirasi:
  - Once kanuni/kesin kural.
  - Sonra cari eslesme ve VKN/TCKN kurali.
  - Sonra satir siniflandirma ve hesap plani aday skoru.
  - Yeni mukellef, yeni urun ailesi, zayif gecmis veri, NACE/faaliyet
    belirsizligi, birden fazla makul hesap adayi veya aciklamasi zayif satirda
    AI aktif olarak anlamlandirma yapar.
  - Daha once onaylanmis kural, chart semantic map veya research cache yeterli
    guven veriyorsa AI/research tekrar cagrilmaz.
  - AI dusuk guven verirse veya hesap ailesiyle celisirse taslak yine
    uretilir; export kapisi review'de kalir ve mustavir kararindan ogrenilir.
- AI sonucunun sinirlari:
  - AI yeni hesap kodu uydurmayacak; sadece mevcut hesap/cari adaylari icinden sececek.
  - AI stok/gider/KKEG gibi hesap ailesi korumasini ezemeyecek. Ornegin stok olmasi gereken pil/kalip icin `770` onerirse onerisi reddedilecek.
  - `>=85` guven: kesin kurallara ve hesap ailesine aykirilik yoksa taslaga uygulanabilir.
  - `70-84` guven: ekranda onerilir, mustavir onayi gerekir.
  - `<70` guven: otomatik uygulanmaz, inceleme gerekir.
- Marka/model, NACE ve internet arastirmasi karari:
  - Fatura satirinda marka/model, teknik urun, sektor terimi veya zayif aciklama
    varsa AI once urun/hizmet anlamini cikarmaya calisir.
  - Mukellefin NACE/faaliyet aciklamasi eksik veya genel kaldiginda research
    katmani faaliyet baglamini zenginlestirir.
  - AI urunu tanimlayamazsa, muhasebe etkisini dusuk guvenle aciklarsa veya
    yeni bir kategori gorurse research katmani devreye girer.
  - Pilot research provider Tavily'dir; OpenAI web research sonraki iterasyon olarak kodda korunur.
  - Research sadece ayni bilgi daha once guvenle cache'lenmemisse calisir;
    bilinen/yuksek guvenli satirlar tekrar internet arastirmasi yapmaz.
  - Research ciktisi `marka`, `urun kategorisi`, `muhasebe etkisi`, `research_confidence` ve `accounting_impact_confidence` olarak ayrilacak.
  - Research sonucu da kanuni kurallari ve hesap ailesi korumasini ezemez; dusuk kaynak veya dusuk muhasebe etkisi guveni review sebebidir.
- NACE arastirmasi karari:
  - Mükellef profilinde NACE var ama faaliyet etiketi yoksa NACE research cache'i profilin faaliyet etiketlerini zenginlestirmek icin kullanilir.
  - NACE research tek basina fise export izni vermez; sadece faaliyet baglami ve uygunluk kararini guclendirir.
  - Mustavir geri bildirimiyle NACE/marka aciklamasi duzeltme arayuzu acik is olarak kalir.

## Sonraki Faz Notlari

- Canli denemeden sonra Faz 8 icin cok mukellefli matrix genisletilecek: isitme cihazi, genel perakende, hizmet, gida, insaat ve medikal benzeri profiller.
- Mevcut belgeleri otomatik yeniden isleme henuz kapali. Sonraki faz: secili belgeyi yeniden isle.
- Bilgi Havuzu benchmark ekranini netlestirme acik kalir: bos cache veya eksik profil durumunda sonucun neden dusuk/0 gorundugunu mustavire debug dili kullanmadan anlatmaliyiz.

## 2026-06-29 Release Ozeti

- Hard rule sirasi netlesti: kanuni/KDV kural, cari eslesme, hesap plani adaylari, AI, research, musavir ogrenmesi.
- AI kapi mantigi eklendi: kesin kurali ezmez, hesap kodu uydurmaz, dusuk guvende research veya review ister.
- Hesap ailesi guardrail eklendi: stok olmasi gereken satir gider hesabina, satis geliri gider hesabina kayamaz.
- Review required olsa bile temel tutarlar ve yon varsa dengeli muhasebe fis taslagi olusturulur.
- Tavily/global research sadece belirsiz marka/model veya zayif siniflandirma durumunda calisir; sonuc cache'e yazilir.
- Karisik KDV icin cihaz satiri %0/3065 kalabilirken pil, aksesuar veya sarj aleti KDV'li satir olarak ayrilabilir.
- Musavir duzeltmesi artik fis satirlari, hesap/cari secimi, duzeltme notu ve kural talimatini ayni karar payload'inda tasir.
- Portalda muhasebe fisi birinci siraya alindi; karar zinciri ve nedenler fis dogruysa bakilmasi gerekmeyen ikincil bolume indi.
