# Medikososyal Canli Veri Kararlari ve Supabase Cikis Notlari

Bu dokuman Medikososyal icin canli veri modeline gecmeden once netlesmesi
gereken urun, yetki, veri saklama ve tasima kararlarini toplar. Amac, once
Supabase ile baslansa bile ileride Radore uzerindeki kendi backend/PostgreSQL
mimarisine kontrollu sekilde gecis yapabilmektir.

## Production PRD'den Netlesen Kararlar

Medikososyal repo'sundaki `docs/prd/production-prd.md` canli urun icin ana
kaynak kabul edilmelidir. README, demo kodu ve Supabase demo dosyalari ikincil
sinyaldir; canli karar olarak tek basina alinmamalidir.

PRD'ye gore netlesen ana kararlar:

- Urun tek production sistem uzerinde cok kiracili SaaS olarak tasarlanacak.
- Her musteri icin ayri Supabase projesi kurulmayacak.
- Ilk hedef olcek 5-10 musteri firma.
- Frontend buyuk olasilikla Vercel uzerinde kalacak.
- Backend icin tercih edilen platform Supabase.
- Auth icin Supabase Auth.
- Auth e-postalari icin Brevo gibi custom SMTP kullanilacak.
- Dosya icerikleri icin varsayilan storage Cloudflare R2 private bucket.
- Supabase dosya metadata, firma/sube/hasta/siparis iliskileri ve yetki
  kontrolu icin kullanilacak.
- SQL/migration dosyalari repoda source-of-truth olacak.
- Production data guvenligi UI seviyesinde birakilmayacak; RLS, RPC veya
  server-side data layer ile enforce edilecek.
- Firma izolasyonu `company_id`, sube izolasyonu uygun tablolarda sube alaniyla
  uygulanacak.
- Baslangic rolleri `Owner`, `Admin`, `Personel`; sonraki rol `Muhasebe`.
- Permission modeli modul, aksiyon, sube ve hassas veri seviyesinde
  configurable tasarlanacak.
- Normal UI'da permanent delete olmayacak; soft delete/archive ana davranis.
- Hasta kaydi KVKK/aydinlatma onayi ve isleme dayanagi olmadan tamamlanmayacak.
- TC kimlik no varsayilan opsiyonel, girilirse maskeli ve tam goruntuleme
  yetkiye bagli olacak.
- Dosya public URL ile acilmayacak; kisa sureli signed URL modeli kullanilacak.
- Hasta, siparis, odeme, stok, fatura, dosya, referans, rapor ve audit log
  production kapsaminda yer alacak.
- E-fatura/e-arsiv production icin gerekli; gercek entegrasyon saglayici
  secimi netlesmeden baslatilmayacak.

## Demo Kodundan Cikarilabilen Ikincil Sinyaller

- Mevcut UI demo/prototip olarak begenilmis; production UI bu yonu koruyarak
  gelismeli.
- Mock/local state, demo auth, demo izinler ve demo RLS production karari
  sayilmayacak.
- Mevcut demo akislari hasta, siparis, odeme, stok, olcu, fatura, referans,
  dashboard, rapor, ayar ve fotograf ihtiyacini gosteriyor.
- Hasta fotografi ve siparis fotografi demo tarafinda mevcut; PRD'ye gore canli
  dosya modeli hasta agirlikli ama siparis baglantisini da desteklemeli.
- Siparis fotografi icin `before` / `after` slot mantigi demo sinyalidir;
  canli modelde urun ihtiyacina gore kesinlestirilecek.

## Netlesmesi Gereken Urun Kararlari

Asagidaki maddelerin bir kismi PRD'de varsayilan olarak cevaplanmis durumda.
Burada amac PRD kararlarini teyit etmek, istisnalari yazmak ve hala acik kalan
alanlari netlestirmek. Kesin degilsen "v1 icin boyle olsun" diye gecici karar
yazmak yeterli.

### Firma ve Klinik Modeli

- Ilk canli kullanim tek firma/tek klinik mi olacak?
- Ayni sistemde birden fazla firma/klinik olacak mi?
- Bir firma icinde sube/bolum ayrimi gerekiyor mu?
- Kullanici birden fazla firmaya baglanabilir mi?
- Firma ayarlari kim tarafindan degistirilebilir?

Karar:

```text

```

### Kullanici, Rol ve Yetki

- Roller sadece `admin` ve `personel` olarak mi kalacak?
- Doktor, teknisyen, muhasebe, yonetici gibi ek roller olacak mi?
- Personel hasta finansini gorebilir mi?
- Personel odeme ekleyebilir/duzenleyebilir mi?
- Personel stok hareketi yapabilir mi?
- Personel rapor/export alabilir mi?
- Kullanici daveti ve sifre sifirlama nasil olacak?
- 2FA ilk canli surumde zorunlu mu, opsiyonel mi?

Karar:

```text

```

### Hasta Kaydi

- Hasta kaydinda zorunlu alanlar neler olacak?
- TC kimlik no zorunlu mu, opsiyonel mi?
- Dogum tarihi zorunlu mu?
- Telefon zorunlu mu?
- Adres zorunlu mu?
- Tani/anamnez zorunlu mu?
- Hasta numarasi otomatik mi uretilsin?
- Hasta tamamen silinebilir mi, yoksa sadece arsiv mi?
- Arsivlenen hasta raporlarda gorunecek mi?

Karar:

```text

```

### Islem / Siparis Akisi

- Mevcut durumlar yeterli mi?
  - `yeni`
  - `olcu_alindi`
  - `uretimde`
  - `teslime_hazir`
  - `teslim_edildi`
  - `iptal`
- Iptal edilen siparis finans/stok tarafinda nasil davranmali?
- Teslim tarihi gecen siparisler otomatik uyari uretsin mi?
- Siparis bir teknisyene atanmak zorunda mi?
- Siparis bir referans verene baglanmak zorunda mi?
- Siparis net ucreti sifir olabilir mi?
- Siparis tamamen silinebilir mi, yoksa arsiv mi?

Karar:

```text

```

### Fotograf ve Dosya Modeli

- Fotograf hastaya mi, siparise mi, yoksa ikisine de mi baglanacak?
- Siparis fotografinda `before` / `after` slotlari kesin mi?
- Ayni slot icin yeni fotograf yuklenince eski fotograf:
  - arsivlensin mi?
  - fiziksel olarak silinsin mi?
  - ikisi birden mi?
- PDF dosyasi da desteklenecek mi?
- Tek dosya maksimum boyutu ne olsun?
- Fotograf saklama suresi "silinene kadar" mi?
- Silinen/arsivlenen fotograf geri alinabilsin mi?
- Fotograflara disaridan public URL verilecek mi, yoksa sadece yetkili API
  uzerinden mi gorulecek?

Karar:

```text

```

### Odeme, Stok ve Fatura

- Odeme kaydi ilk canli surumde aktif kullanilacak mi?
- Kismi odeme/depozito mantigi kesin mi?
- Odeme silinebilir mi, yoksa iptal kaydi mi tutulmali?
- Stok takibi ilk canli surumde aktif mi?
- Barkod ve paket carpani gercek operasyon icin gerekli mi?
- Stok satisi hasta ile iliskili olmak zorunda mi?
- Gelen fatura ve e-fatura entegrasyonu ilk canli surumde olacak mi?
- E-fatura entegrasyonu sadece ayar ekraninda mi kalacak, yoksa gercek API
  baglantisi planlaniyor mu?

Karar:

```text

```

### Audit, Log ve Veri Saklama

- Hangi islemler audit log'a yazilmali?
  - login/logout
  - hasta olusturma/duzenleme/arsivleme
  - siparis olusturma/duzenleme/arsivleme
  - odeme ekleme/duzenleme/iptal
  - fotograf yukleme/silme
  - stok hareketleri
  - ayar degisiklikleri
- Audit kayitlari ne kadar saklanacak?
- Hasta kaydi KVKK talebiyle tamamen silinebilmeli mi?
- Tam silme olursa finans/fatura/stok kayitlari nasil korunacak?
- Yedeklerdeki hasta/fotograf verisi ne kadar saklanacak?

Karar:

```text

```

## Supabase Ile Baslayip Sonra Kendi Backend'imize Gecis

Supabase ile baslamak ileride cikisi imkansiz yapmaz. Supabase'in veritabani
PostgreSQL oldugu icin, dogru baslanirsa Radore uzerindeki PostgreSQL'e veri
tasimak yonetilebilir bir is olur.

### Bastan Alinacak Onlemler

- Supabase semasi GitHub'da migration mantigiyla tutulmali.
- Demo RLS politikalari canli veride kullanilmamali.
- Her tabloda `company_id` veya esdeger tenant alani olmali.
- Public client koduna `service_role` veya secret key konmamali.
- Dosya kayitlari DB'de metadata olarak tutulmali; fiziksel dosya yolu ayrica
  saklanmali.
- ID'ler UUID kalmali; sonradan tasima icin id degistirme yapilmamali.
- Uygulama kodu dogrudan her yerde Supabase client'a baglanmak yerine veri
  erisim katmani uzerinden ilerlemeli. Boylece sonraki hedef API/PostgreSQL
  oldugunda ekranlar komple yeniden yazilmaz.

### Firma Bazli Tasima Stratejisi

Canli firmalar varken tasima "tum sistemi bir anda kapat-tasi-ac" seklinde
yapilmamali. Daha guvenli model firma bazli tasimadir.

1. Yeni Radore backend ve PostgreSQL hazirlanir.
2. Supabase'den schema ve data dump alinir.
3. Veriler staging PostgreSQL'e restore edilir.
4. Her firma icin kayit sayilari ve referans butunlugu kontrol edilir.
5. Storage dosyalari/gorseller bucket'tan indirilir veya yeni
   `medical-storage` servisine kopyalanir.
6. Dosya metadata'sindaki path/URL alanlari yeni storage path'lerine map edilir.
7. Secilen pilot firma icin Vercel env veya firma routing ayari yeni backend'e
   cevrilir.
8. Pilot firma read/write test edilir.
9. Kisa bakim penceresinde ilgili firma Supabase tarafinda read-only kabul
   edilir.
10. Son delta export/import yapilir.
11. Firma yeni backend uzerinden acilir.
12. Eski Supabase verisi belirlenen sure boyunca read-only yedek olarak tutulur.

### Dogrulama Checklist'i

Her firma tasimasindan sonra su kontroller yapilmali:

- Firma kaydi sayisi dogru mu?
- Kullanici sayisi ve rolleri dogru mu?
- Hasta sayisi dogru mu?
- Siparis sayisi dogru mu?
- Odeme toplam tutarlari Supabase ile ayni mi?
- Stok miktarlari ayni mi?
- Aktif/arsivli kayit sayilari ayni mi?
- Fotograf/file record sayisi ayni mi?
- Rastgele secilen 10 hasta detayinda tum iliskili siparis, odeme ve dosyalar
  gorunuyor mu?
- Yeni backend'de yeni hasta, siparis, odeme ve fotograf ekleme calisiyor mu?
- Eski Supabase projesinde yanlislikla yeni veri yazilmiyor mu?

### Geri Donus Plani

- Tasima tamamlanmadan Supabase verisi silinmeyecek.
- Pilot firmada kritik hata cikarsa Vercel env/routing eski Supabase backend'e
  geri alinacak.
- Yeni backend'e yazilan test verileri ayri isaretlenecek veya geri alinabilir
  sekilde tutulacak.
- Tam cikis karari verilene kadar Supabase en az bir backup/arsiv donemi
  read-only kalacak.

## Su Anki Onerilen Karar

- Ilk asamada Supabase DB/Auth kullanilabilir.
- Radore'da yalnizca `medical-storage` gorsel servisi kurulabilir.
- Medikososyal veri erisim katmani simdiden soyutlanmali; ekranlar dogrudan
  Supabase'e baglanacak sekilde dagitilmamali.
- Canli kullanim kurallari bu dokumandaki kararlarla netlestikten sonra
  `medical-api + PostgreSQL` gecisi ayrica planlanmali.
