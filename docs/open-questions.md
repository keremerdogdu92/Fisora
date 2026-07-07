# Acik Kararlar ve Takip Planlari

Bu dosya 2026-07-07 karar temizligi sonrasi tek okuma noktasi olarak tutulur.
Eski ham soru listesi asagida karar, durum ve takip planina cevrildi.

Durumlar:

- `kapandi`: Urun karari verildi; uygulama veya dokuman guncellemesi takip edebilir.
- `planlandi`: Karar verildi, ama ayri uygulama/operasyon plani gerekiyor.
- `saha testi`: Urun yonu belli, mustavir/Zirve/canli ortam dogrulamasi bekliyor.

## Kalan Gercek Acik Isler

1. **Zirve saha import testi** (`saha testi`)
   - Fisora CSV/XLSX ciktisi uretecek; Zirve'de sabit kolon kontrati yok.
   - Mustavir Zirve import ekraninda kolonlari tek tek eslestirecek.
   - Basarili import gorulmeden `verified_in_zirve=false` kalir.
   - Teknik hazirlik tamamlandi: `zirve_mapping_csv` kontrati testle kilitlendi,
     `docs/zirve-field-test-runbook.md` eklendi ve adapter hala
     `field_test_pending`.
   - Portal cikti ekraninda `zirve_mapping_csv` secilerek backend'de
     indirilebilir saha test paketi uretilebiliyor.

2. **Auth ve mail uygulama plani** (`planlandi`)
   - Ilk MVP yolu custom session + email davet/reset olacak.
   - `trusted_header` simdilik ana yol degil; ancak guvenilir gateway/JWT/OIDC
     katmani kurulursa tekrar degerlendirilir.
   - Free-tier mail servisi secilecek ve davet/sifre sifirlama akisi baglanacak.

3. **Manuel backup plani** (`kapandi`)
   - Alinan ilk sunucu: 4 Core 2.70 GHz, 4 GB DDR4 RAM, 100 GB NVMe SSD.
   - DB dump, export dosyalari, belge metadata manifesti ve gerekli dosya
     yedekleri icin manuel/yari otomatik backup plani runbook'a yazildi.
   - Backup hedefi `FISORA_BACKUP_COPY_DIR` ile ayni makine disina alinacak.
   - Uygulama: `deploy/backup/backup.sh`, `deploy/production.env.example`,
     `docs/production-ops-runbook.md`.

4. **Belge saklama ve silme onayi** (`kapandi`)
   - Ham belgeler 90 gun sonunda otomatik sessizce silinmeyecek.
   - Musavire operasyon ekraninda saklama onizlemesi, silme onayi ve 90 gun
     uzatma secenegi sunulacak.
   - Musteriye geri indirme acilmadi; musteri sadece onizleyebilir.
   - Uygulama: `/store/document-retention/preview`,
     `/store/document-retention/action`, operasyon paneli.

5. **Fatura/ekstre OCR politikasi** (`kapandi`, uygulama kontrolu gerekebilir)
   - Bu fazda fatura/ekstre akisi taranmis belge beklemiyor.
   - XML/UBL, CSV/Excel ve text layer'i okunabilen PDF ana kaynaktir.
   - Text PDF'den ayrica OCR dondurulmez; cunku iki farkli kaynagi uzlastirma
     katmani bu fazda yok.
   - Text cikmayan/taranmis fatura veya ekstre otomatik islenmez; review veya
     unsupported/scanned belge gerekcesiyle ayrilir.
   - Vergi levhasi OCR'i ayri onboarding kanali olarak kalabilir.

## Kapanan Kararlar

### Zirve ve Export

1. **Aktarim rotasi**
   - Sabit hazir Zirve formatina guvenilmeyecek.
   - Fisora, fis satirlari iceren CSV/XLSX uretir; Zirve'de kolonlar mustavir
     tarafindan eslestirilir.

2. **Fis/seri fis/fis listesi yeterliligi**
   - Urun hedefi fatura ekini Zirve'ye tasimak degil, muhasebe fis satirlarini
     aktarilabilir ciktida vermektir.

3. **Zirve kolonlari**
   - Sabit kolon listesi yok. Ciktida kolon anlamlari acik olacak; Zirve'de
     hangi kolonun ne oldugu import ekraninda tanitilir.

4. **Gecmis yevmiye/muavin**
   - Gecmis veriyi Zirve'den almak ilk fazdan cikarildi.
   - Gecmis veri aktarimi blokaj degil; bu yoldan vazgecildi.

5. **Belge PDF/XML ekleme**
   - Belgenin kendisi Zirve'ye yuklenmeyecek.

6. **Export paketleme**
   - Opsiyonel olacak. Musavir isterse tamamlanan mukellefleri cikarir, isterse
     tum donemin tamamlanmasini bekler.

7. **Dogrudan Zirve entegrasyonu**
   - Ilk fazda yok. Saha testi olmayan adapter verified sayilmaz.

### Mukellef Onboarding

8. **Minimum kart**
   - Mukellef karti, VKN/TCKN, NACE, NACE'den uretilen faaliyet aciklamasi,
     isyeri adresi ve Zirve hesap plani gerekir.

9. **NACE/faaliyet**
   - NACE zorunlu. Faaliyet aciklamasi NACE'den uretilir ve profil alani olarak
     zorunlu kabul edilir; musavir gerekirse duzeltir.

10. **Isyeri adresi**
   - Adres, elektrik/internet/kira gibi lokasyon bagli giderlerde ve faaliyet
     uygunlugu yorumunda kanit sinyali olarak kullanilir.
   - Her faturada otomatik blokaj degil, risk/review sinyalidir.

11. **Hesap plani yenileme**
   - Duzenli otomatik yenileme yok. Musavir ozellikle yeniden yuklerse hesap
     plani guncellenir.

12. **Cari bulunamazsa**
   - Sistem yeni 120/320 cari onerisi uretir; otomatik acilis ve export mustavir
     politikasina/review'a baglidir.

### Risk, Uygunluk ve Otomasyon

13. **Yuksek tutar limiti**
   - Varsayilan yuksek tutar limiti olmayacak.

14. **Iade, tevkifat, istisna**
   - Kural ogrenilene kadar review'da kalir.
   - Musavir sonra farkli politika verirse bu karar kural olarak guncellenir.

15. **OIV/OTV, karma KDV, eksik belge no**
   - Bunlar her zaman review olmak zorunda degil.
   - Yeterli guven, kanit ve hesap plani eslesmesi varsa export-ready olabilir.
   - Guven dusukse veya kanuni yorum riski varsa review'a duser.

16. **Musavir karar secenekleri**
   - Urun dili: `Onayla`, `Duzelt ve onayla`, `Kontrolde kalsin`,
     `Export disi birak`, `Faaliyet disi/kisisel gider`.

17. **Genel gider adres/plaka**
   - Elektrik, internet ve kira gibi giderlerde adres kanit sinyali olsun.
   - Akaryakit/arac giderleri dogru hesap planina onerilsin ama review/onay
     istesin.

18. **AI guven esigi**
   - `<70`: review/research.
   - `70-84`: taslak uygulanabilir, mustavir onayi gerekir.
   - `>=85`: kesin kanuni/KDV kurala aykiri degilse taslaga uygulanabilir.

19. **Otomasyon adayi tekrar sayisi**
   - Ayni veya cok benzer karar 3 kez tutarli onaylanirsa otomasyon adayi olur.

20. **Ogrenme kapsami**
   - Genel aday, mustavir/ofis politikasi ve mukellef ozel kural ayrimi urunde
     ogrenme sinyali/kural adayi olarak gosterilir.

21. **Manuel fis satiri duzeltmesi**
   - `draft_lines` ana taslak degisikligini tasir.
   - Sistem eski kod alanlarini kaybetmemek icin secilen fis satirlarindan
     hesap/cari kodlarini turetebilir.

22. **Karar notu**
   - `accountant_note` ve `rule_instruction` UI'da ayri alan olmayacak.
   - Tek alan adi: `Karar notu`.
   - Sistem bu notu hem mevcut karar gerekcesi hem de ogrenme/kural adayi
     sinyali olarak kullanir.

### Operasyon ve Veri

23. **Ham belge saklama**
   - Ham belge 90 gun aktif kalir.
   - 90 gun sonunda musavire operasyon panelinde saklama onizlemesi +
     silme/uzatma onayi sunulur.
   - Musteri geri indiremez; sadece onizleme akisi korunur.
   - Metadata, fis taslagi, mustavir karari, learning event ve export izi
     denetim icin kalir.

24. **AI cagrisi atlama**
   - Guvenilir statik kural, bilinen tedarikci/kategori, ogrenilmis kural,
     semantic map veya cache yeterliyse AI/research tekrar cagirilmaz.

25. **OCR fallback**
   - Fatura/ekstre akisi icin bu fazda kapali; text kaynagi yoksa otomatik
     islenmez.
   - Vergi levhasi OCR'i onboarding icin ayri tutulur.

26. **Iptal/duzeltme**
   - Sureye degil, musavir isleme durumuna bagli.
   - Musavir belgeyi islemediyse mukellef iptal/duzeltme istegi baslatabilir.
   - Musavir islediyse mukellef tek basina iptal edemez; musavir review gerekir.

27. **Denetim izi suresi**
   - Denetim izi musavir kendi islemini bitirene kadar kalir; ham belge silme
     sureci ayridir.

### Sunucu ve AI API

28. **Ilk sunucu**
   - Alinan kaynak: 4 Core 2.70 GHz, 4 GB DDR4 RAM, 100 GB NVMe SSD.
   - Bu kaynak icin hafif pilot, worker sayisi, backup ve disk kullanim plani
     ayrica uygulanacak.

29. **Backup**
   - Manuel/periyodik backup plani runbook'a yazildi.
   - Ayni makine disi hedef `FISORA_BACKUP_COPY_DIR` ile tanimlanacak.
   - Lokal `bash -n` kontrolu bu Windows ortaminda bash olmadigi icin
     calismadi; serverda deploy oncesi calistirilacak.

30. **AI API kapsami**
   - AI kategori/gerekce, fis taslagi, karar aciklamasi ve musavir politika
     sablonu hazirlamaya yardim eder.
   - Nihai politika ve export karari musavir/onayli kural tarafindan verilir.

31. **Dusuk guven**
   - Ana esik 70. Dusuk guven review/research sebebidir.

32. **AI maliyet cap**
   - Ofis/mukellef bazinda cagrilar ve tahmini maliyet izlenir.
   - Kesin cap degeri provider ve pilot hacmine gore uygulama planinda
     belirlenecek.

33. **Gercek fatura metni dis AI**
   - Gercek fatura metni dis API'ye gidecekse musavir/veri sahibi onayi veya
     anonimlestirme gerekir.

34. **AI assisted draft basari esigi**
   - Ana hedef `draft_success`: gerekli fis taslagini uretmek.
   - `automation_success`: mustavir politikasiyla dogrudan export-ready olabilen
     islem oranidir ve ayri metrik olarak izlenir.

35. **AI hesap onerisi**
   - AI yalniz mevcut hesap plani/cari adaylari icinden secer.
   - Aday yoksa hesap uydurmaz; aciklama + review uretir.

36. **Soguk baslangic basarisi**
   - AI ile gerekli fisleri uretmek ana basari kriteridir.
   - Mustavir onaysiz otomasyon bundan ayri, daha ileri bir metriktir.

37. **Eski OpenAI/Gemini/Manus benchmark**
   - Silindi. AI hatti degisti; eski provider karsilastirma sorusu artik urun
     acik karari degil.

### Auth ve Canli Portal

38. **Gercek login**
   - Ilk MVP custom session ile ilerler.
   - Provider veya `trusted_header` sonraki opsiyon.

39. **Trusted header**
   - Simdilik ana yol degil.
   - Ancak gateway tarayici header'ini silip session/JWT/OIDC dogrular ve
     backend'e guvenilir user id enjekte ederse kullanilabilir.

40. **Davet, sifre reset, mail**
   - Free-tier mail servisiyle davet, ilk sifre belirleme ve sifre sifirlama
     akisi kurulacak.
   - 2FA ilk uygulama kapsami disinda kalabilir; politika daha sonra eklenir.

41. **Mukellef belge erisimi**
   - Mukellef yukledigi belgeyi geri indiremez, sadece onizleyebilir.
   - Ileride musavir isterse indirme yetkisi ofis/mukellef politikasi olarak
     acilabilecek sekilde tasarlanir; bugunku varsayilan kapali.

## Uygulama Planlari

### Plan 1 - Karar Notu ve Ogrenme Alani

Amac: Review UI ve backend payload'inda iki ayri not mantigini sade hale
getirmek.

1. UI'da `accountant_note` ve `rule_instruction` yerine tek `Karar notu` alani
   goster.
2. Backend'e geriye uyumluluk icin eski alanlari kabul ettir, ama yeni akista
   tek nottan karar gerekcesi ve kural adayi uret.
3. Learning event'te bu notu hem denetim gerekcesi hem de kural sinyali olarak
   sakla.
4. Testlerde eski iki alan beklentilerini yeni tek alan kontratina gore guncelle.
5. Uygulama basladi: `decision_note` backend tarafinda kabul ediliyor; UI tek
   `Karar notu` alani gosteriyor.

### Plan 2 - Auth, Mail ve Session

Amac: Kapali pilotu mock header'dan gercek custom session + mail davet akina
tasimak.

1. Auth modunu ilk MVP icin `session_required` olarak hedefle.
2. Free-tier mail servisi sec: Resend, Brevo veya SMTP2GO kisa liste.
3. Davet linki, sifre belirleme ve sifre sifirlama mail sablonlarini ekle.
4. Token rate limit, expiry ve yeniden gonderme kurallarini ekle.
5. `trusted_header` dokumanini gateway bagimli sonraki opsiyon olarak tut.
6. Uygulama basladi: invite/reset endpointleri `email_delivery` sonucu
   donduruyor; `disabled`, `dry_run`, `resend` ve `smtp` mail modlari eklendi.

### Plan 3 - Backup ve Saklama Operasyonu

Amac: 4 GB RAM / 100 GB diskli sunucuda veri kaybi ve disk sismesini onlemek.

1. Tamamlandi: DB dump + belge metadata manifesti backup scriptinde korunuyor;
   ops runbook'a deploy oncesi backup kontrolu eklendi.
2. Tamamlandi: Ayni makine disi kopya hedefi `FISORA_BACKUP_COPY_DIR` olarak
   env'e eklendi.
3. Tamamlandi: 90 gun sonunda sessiz silme yerine retention preview + secili
   `delete` veya `extend_90_days` aksiyonu eklendi.
4. Kismen tamamlandi: Operasyon ekranina belge saklama paneli baglandi; disk
   kullanim ve backup sonuc loglari readiness tarafinda izlenmeye devam ediyor.

### Plan 4 - Zirve Saha Testi

Amac: Kolon eslestirme esasli Zirve importunu gercek mustavir ekraninda
dogrulamak.

1. Tamamlandi: `zirve_mapping_csv` kolon kontrati BOM + `;` + header testiyle
   kilitlendi.
2. Tamamlandi: `docs/zirve-field-test-runbook.md` olusturuldu ve lokal sentetik
   export ornegi `exports/generated/zirve-field-test/` altinda uretildi.
3. Tamamlandi: Portal cikti ekranina `zirve_mapping_csv`, `zirve_universal_csv`
   ve `zirve_trial_csv` secimi baglandi; paket backend export route'undan
   uretiliyor.
4. Saha bekliyor: Mustavir Zirve import ekraninda kolonlari eslestirecek.
5. Saha bekliyor: Basarili fis olusumu, hata mesaji, zorunlu alan ve ekran adi
   `docs/zirve-validation-matrix.md` dosyasina islenecek.
6. Basarili test olmadan adapter'i verified sayma.

### Plan 5 - Fatura/Ekstre OCR Kapisi

Amac: Text PDF'de iki kaynak carpismasini engellemek.

1. Fatura/ekstre isleme hattinda OCR'i varsayilan kapali tut.
2. Text extraction bos veya taranmis belge tespit edilirse belgeyi otomatik
   isleme sokma; review/unsupported gerekcesiyle ayir.
3. Vergi levhasi OCR akisini onboarding icin ayri tut.
4. Ileride OCR eklenecekse once parser-vs-OCR uzlastirma tasarimi yap.
5. Uygulama basladi: textless fatura PDF'i `scanned_pdf_unsupported` notuyla
   review hattina ayriliyor; fatura workflow'u OCR basari olayi uretmiyor.
