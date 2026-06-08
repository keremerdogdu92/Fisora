# MVP Portal Plani

## Amac

Fisora MVP, mustavirin mevcut tanitim sitesinden erisilecek uyelikli bir belge
yukleme ve review portali olarak baslar. Ilk gosterim halka acik demo degildir;
gercek veya pilot veriler Git disi local snapshot ile ya da yetisirse private
login arkasindaki server uzerinden mustavire gosterilir. Portal kendi basina
"kesin kayit atan AI" degildir; mukellef belgelerini toplar, fis taslagi uretir,
riskleri gosterir ve mustavir kontrollu Zirve export paketi hazirlar.

Tanitim sitesi ayni domain altinda iki sabit path'e link verir:

- `https://siteadi.com/portal/mukellef` -> mukellef girisi.
- `https://siteadi.com/portal/musavir` -> musavir girisi.

Bu path'ler public demo degil, uyelikli/private pilot portal girisleridir.

## Roller

- Ofis yoneticisi: mustavir/ofis ayarlarini, kullanicilari ve mukellefleri
  yonetir.
- Mustavir: fis taslaklarini onaylar, duzeltir, reddeder ve otomasyon
  politikalarini belirler.
- Mukellef kullanicisi: sadece kendisine atanmis mukellef adina belge yukler ve
  belge durumunu izler.
- Sistem/worker: belgeyi parse eder, siniflandirir, fis taslagi ve risk sonucu
  uretir.

## Uyelik Karari

Serbest uyelik olmayacak. Kullanici hesabi mustavir/ofis tarafindan acilir ve
bastan bir mukellefe baglanir. Mukellef eslesmesi olmayan kullanici fatura veya
ekstre yukleyemez.

Bir kullanici birden fazla mukellefe yetkili olabilir; belge yukleme ekraninda
sadece yetkili oldugu mukellefleri gorur. Tek mukellefe yetkili kullanicida
mukellef secimi otomatik gelir.

## Minimum Mukellef Onboarding

Canli belge isleme icin zorunlu paket:

- Mukellef unvani
- VKN/TCKN
- Zirve'deki firma veya ofis takip karsiligi
- Faaliyet/NACE kodu veya faaliyet aciklamasi
- Isyeri adresleri ve varsa subeler
- Zirve hesap plani exportu

Opsiyonel hizlandiricilar:

- Cari liste exportu
- Gecmis yevmiye exportu
- Muavin veya fis listesi exportu
- Zirve'nin kabul ettigi ornek import dosyasi

Opsiyonel dosyalar alinmazsa sistem calismayi durdurmaz; daha fazla kaydi review
kuyruguna dusurur ve ogrenmeyi mustavir onaylarindan baslatir.

## Belge Yukleme Akisi

```text
kullanici giris yapar
  -> yetkili mukellef secilir veya otomatik atanir
  -> fatura, e-fatura XML/PDF, banka ekstresi veya POS ekstresi yuklenir
  -> belge otomatik kuyruga duser ve "isleniyor" durumuna gecer
  -> worker parse ve siniflandirma yapar
  -> fis taslagi ve risk sonucu uretilir
  -> sonuc mustavir review ekranina duser
```

Yuklenen belge asla bosta kalmaz; her belge bir mukellef, yukleyen kullanici,
kaynak dosya ve isleme durumu ile saklanir.

## Portal Ekranlari

Ilk MVP arayuzu halka acik demo gibi degil, private pilot calisma alani olarak
ayrilir:

- Mukellef portali: mukellef adi sabit gorunur, kullanici ay bazinda belge
  sayilarini, sade belge listesini ve iptal/duzeltme talebini gorur. Muhasebe
  fisi, AI gerekcesi ve export paketi mukellefe gosterilmez.
- Mustavir masasi: mustavir mukellef arar/secer, secili mukellefi sabit
  gorur, belgeleri inceler, belge gorunumu ile uretilen muhasebe fisini ayni
  calisma alaninda gormeden karar vermez.
- Cikti listesi: mustavir tamamladigi mukellefleri listeye ekler; en son toplu
  veya mukellef bazli cikti almayi secer.
- Operasyon ekrani: private/local veri kaynagi ve sistem durumu gibi teknik
  bilgiler ana review akisini kalabaliklastirmadan ayrica gosterilir.

Mustavir ekraninda ayni anda gorunmesi gereken ana alanlar:

- Sol panel: mukellef karti, belge/review/export kuyrugu ve hesap plani secimi.
- Orta panel: o an incelenen fatura veya ekstre onizlemesi, tedarikci, tutar,
  KDV ve kalem/kategori bilgisi.
- Sag panel: onerilen muhasebe fisi, cari/hesap eslesmeleri, AI/kural
  gerekcesi, export gate nedeni ve onay/duzeltme aksiyonlari.

Bu ekran Git disi private/local snapshot ile calisabilir; ancak UI davranisi
production API sozlesmesine hazir tutulur. Mevcut private portal arayuzu
acilista backend `store/clients` ve
`store/workspace/{client_id}` endpointlerini dener; backend bos veya kapaliysa
Git disi local snapshot/fallback verisine duser.

## AI Destekli Taslak Davranisi

Yeni mukellefte gecmis karar yoksa portal bos sonuc gostermemelidir. Sistem
`ai_assisted_draft` modunda AI/kural destekli ilk fis taslagini hazirlar ve
mustavire su ayrimi net gosterir:

- AI'in tahmini kategori ve hesap onerisi.
- Deterministik motorun dogruladigi tutar, KDV ve denge.
- Export'a neden girip girmedigi.
- Mustavirin hangi alani duzelttigi ve bunun ogrenmeye nasil yansiyacagi.

Bu modda export varsayilan olarak kapali kalir. Kayit ancak mustavir onayi veya
daha once tanimlanmis mustavir/ofis politikasi varsa export adayi olur.

## Mustavir Review Akisi

Review ekraninda her kayit icin su bilgiler gosterilir:

- Belge ve yukleyen mukellef
- Tedarikci/alici bilgisi ve cari eslesme sonucu
- Fatura kalemleri, marka/model adaylari ve urun kategorileri
- NACE/faaliyet uygunluk sonucu
- Onerilen fis satirlari
- Borc/alacak dengesi
- Risk bayraklari
- AI/kural gerekcesi
- Export'a girip girmeyecegi

Mustavir aksiyonlari:

- Onayla
- Duzelt ve onayla
- Export disi birak
- Is alani disi/reddet
- Kontrol kuyrugunda tut
- Iptal/duzeltme talebini kabul et
- Iptal/duzeltme talebini reddet
- Cikti listesine ekle
- Bu karari sonraki benzer belgelerde oner

## Export Politikasi

- `export_ready`: dengeli, cari/hesap eslesmesi net, risk bayragi yok veya
  mustavir politikasiyla izinli.
- `review_required`: fis taslagi var ama mustavir kontrolu gerekir.
- `blocked`: eksik mukellef, eksik hesap plani, okunamayan belge veya kritik
  parse hatasi.
- `rejected`: mustavir tarafindan is alani disi veya islenmeyecek belge olarak
  isaretlenmis.

Ilk MVP'de dogrudan Zirve'ye gonderim yoktur. Sistem, gercek Zirve testinde
calistigi kanitlanmis formatta export paketi uretir.

## Otomasyona Gecis

Ilk canli kullanimda sistem otomatik taslak uretir ama export kontrolludur. Ayni
mukellef, tedarikci, urun kategorisi, cari ve hesap karari en az 3 kez tutarli
onaylanirsa otomasyon adayi olur.

Otomasyon adayi olmak tek basina yeterli degildir; mustavir/ofis politikasi bu
kategoriye izin vermelidir. Supheli, is alani disi, karma KDV, tevkifat, iade,
istisna veya eksik cari iceren kayitlar otomatik export'a girmez.

## MVP Basari Olcutleri

- Mukellef eslesmesi olmadan belge yuklenemez.
- Belge yukleyen kisi ve mukellef denetim izinde gorunur.
- 20-50 fatura ve 1-2 ekstre ile pilot calisir.
- Fis taslaklari dengelidir.
- Supheli belgeler export'a girmez.
- Mustavir duzeltmeleri sonraki benzer belgelerde oneriyi degistirir.
- Zirve export formati sahada dogrulanir.
