# Kural Motoru ve Ogrenme Plani

## Amac

Kural motoru, AI'in tek basina muhasebe karari vermesini engelleyen ana guvenlik
katmanidir. AI belgeyi ve urun satirlarini anlamlandirir; kural motoru ise hesap
plani, cari, faaliyet uygunlugu, mustavir politikasi ve gecmis onaylarla karar
uretir.

## Kural Katmanlari

1. Genel muhasebe iskeleti
   - 120 alicilar, 320 saticilar, 191 indirilecek KDV, 391 hesaplanan KDV, 102
     banka, 360 vergi, 361 SGK, 600 gelir, 770/760/740 gider gibi ana mantik.

2. Belge risk kurallari
   - Karma KDV, tevkifat, iade, istisna, OIV/OTV, sifir tutar, eksik tarih,
     eksik belge no, eksik cari.

3. Genel gider uygunluk kurallari
   - Elektrik, su, internet, kira, e-fatura servisi, kargo, yazilim, GIB/SGK,
     banka, POS gibi sektorler arasi ortak kalemler.

4. NACE/faaliyet profili kurallari
   - Mukellefin faaliyet alaniyla dogrudan uyumlu, genel gider, supheli veya is
     alani disi kalem ayrimi.

5. Mukellef ozel kurallar
   - Zirve hesap plani, cari kodlar, isyeri adresleri, ozel tedarikci ve hesap
     tercihleri.

6. Mustavir/ofis politikasi
   - Hangi kategoriler otomatik export adayi olabilir, hangileri daima review
     ister.

7. Ogrenme kurallari
   - Mustavir onaylari, duzeltmeleri ve red kararlarindan olusan tekrar eden
     kararlar.

## Urun Kategori Normalizasyonu

Fatura satirlari cogu zaman genel kategori adiyla gelmez. Sistem bu nedenle
kelime aramasi yaparak karar vermeyecek; marka/model satirlarini normalize edip
urun kategorisine cevirecek.

Ornekler:

| Ham satir | Kategori adayi | Not |
|---|---|---|
| Urban Care ... | kisisel_bakim_kozmetik | Isitme merkezi icin supheli |
| Rexton RLi 20 | isitme_cihazi | Isitme merkezi icin uygun |
| Phonak pil ... | isitme_cihazi_pili | Isitme merkezi icin uygun |
| Kolaysoft e-fatura | e_fatura_hizmeti | Genel gider |
| AWS / hosting | bulut_yazilim_hizmeti | Yazilim sirketi icin uygun olabilir |

Siniflandirma sinyalleri:

- Ham satir metni
- Marka/model adayi
- Tedarikci unvani
- KDV orani
- Fatura adresi
- Mukellef faaliyet/NACE profili
- Gecmis mustavir kararlari
- Genel urun sozlugu
- Gerekiyorsa AI siniflandirmasi

## Business Relevance Ciktisi

Her belge veya kalem icin su sonuc uretilir:

```json
{
  "status": "uygun | genel_gider | supheli | is_alani_disi",
  "confidence": 0,
  "reason": "kisa gerekce",
  "evidence": ["NACE", "urun kategorisi", "tedarikci", "gecmis onay"]
}
```

AI'in gorevi bu ciktinin siniflandirma ve gerekce kismini desteklemektir. AI
nihai vergi/hukuk karari vermez.

## AI Destekli Taslak Modu

Gecmis yevmiye veya mustavir karari olmayan yeni mukelleflerde sistem
`ai_assisted_draft` moduyla calisabilir. Bu modda AI fatura metni, marka/model
satirlari, mukellef faaliyet bilgisi ve mevcut hesap plani adaylarindan ilk fis
taslagini hazirlamaya yardim eder.

Bu modun kurallari:

- AI mevcut hesap plani disinda hesap kodu uyduramaz.
- AI'in hesaba yazma onerisi deterministic fis motoru tarafindan dengelenir.
- AI confidence dusukse kayit otomatik olarak `review_required` kalir.
- AI'in hazirladigi soguk baslangic taslagi mustavir onayi olmadan export'a
  girmez.
- Mustavir duzeltmesi sonraki benzer belgede kural/ogrenme sinyali olarak
  kullanilir.

## Fis ve Export Karari

- `uygun`: fis taslagi normal uretilir, risk yoksa export adayi olabilir.
- `genel_gider`: mustavir politikasina gore export adayi veya review olur.
- `supheli`: fis taslagi uretilir, export'a alinmaz, review gerekir.
- `is_alani_disi`: fis taslagi uretilir, export'a alinmaz, mustavir onayi olmadan
  kapatilir.

Supheli kayitlar icin guvenli varsayim:

```text
fis taslagi var
export yok
mustavir kontrolu zorunlu
```

## Ogrenme Modeli

Ilk urun asamasinda ogrenme iki kanaldan gelir:

- Mustavirin fatura uzerinde yaptigi duzeltmeler sistem icin ogrenme sinyalidir.
- Mustavir, fatura uzerindeki `kural karar notu` alanina dogal dilde kararini yazar; sistem bu notu AI ile yapilandirilmis kurala cevirir. Bu aksiyon kural olusturmanin ana yoludur.

Kural yalnizca tek bir hesap koduna baglanmak zorunda degildir. Muhasebe niyetini veya belge sinifini da kilitleyebilir. Ornegin belirli mukellef + belirli tedarikci icin `bu firmadan gelen her sey mal alistir` karari verildiginde, satir aciklamasi `bakim/onarim` olsa bile ana muhasebe yonu mal alis olarak kalir; uygun alt hesap belge icerigine gore secilebilir.

Utility/genel gider tedarikcileri ayri ele alinir. Su, elektrik, telefon, internet ve dogalgaz gibi firmalarda tedarikci sinifi sabittir; fatura icindeki belirli vergi veya bedel satirlari icin ek kurallar calisabilir. Ornegin atiksu bedeli veya OIV gibi kalemler kendi ozel muhasebe davranisina sahip olabilir. Ayni tedarikci hem utility hem mal alim firmasi olarak kullanilmaz.

Kural ilk kez bir mukellefte ogretildiginde o mukellef icin kesinlesir. Ayni tedarikci veya ayni utility davranisi baska bir mukellefte goruldugunde sistem onceki kurali hazir onerir ancak otomatik uygulamaz. Mustavir her mukellef icin ayri onay verir. Boylece ofis genelinde standardizasyon hizlanir fakat denetim korunur.

Egitimin ana arayuzu fatura inceleme ekranidir. Ayri kural/egitim ekrani varsa aktif kurallari gorme, duzenleme veya devre disi birakma gibi ikincil yonetim icin kullanilir.

Ayni mukellefte ayni kural niteligindeki duzeltme 3 farkli faturada ayni sekilde yapilip onaylanirsa sistem bunu otomatik olarak kural adayi haline getirir ve mustavire onerir. Bu tekrar sinyali kurali kendiliginden aktif etmez; mustavir onayi gerekir.

> PIN / ACIK KONU: 3-fatura tekrar eslestirmesi productiona gecmeden once kural fingerprint mantigiyla yeniden netlestirilecek. Hesap kodu tek basina eslesme anahtari olmayacak; tedarikci/utility kimligi + semantik karar + kapsam esas alinacak. Bu konu simdilik beklemede.

Normal kural olusturma akisi mustavirin fatura uzerinde karar notu yazmasiyla baslar. Sistem her tekil duzeltmeye mudahale etmez; utility tedarikcilerinde onceki mukellef kurallarinin yeniden kullanimi ve ayni mukellefte 3 farkli faturada tekrarlanan kararlar icin proaktif onay onerisi gosterebilir.

Uzun vadede yeterli veri ve ekonomik kaynak olustugunda, bu birikmis onayli kararlar gercek model egitimi/fine-tune icin degerlendirilebilir; ilk urun asamasinda ana mekanizma kural ogrenmesi ve mustavir onayidir.

## Yeni Mustavirlerde Kullanim

Yeni mustavir sifirdan baslamaz. Genel kural kutuphanesi, NACE/faaliyet profili
ve urun kategori sozlugu hazir gelir. Gecmis yevmiye yoksa ilk kayitlar daha cok
review kuyruguna duser; mustavir onayladikca ofis ve mukellef kurallari olusur.

## Test Senaryolari

- Marka/model iceren uygun kalemler: Rexton, Phonak, Oticon gibi isitme cihazi
  ornekleri.
- Marka/model iceren supheli kalemler: Urban Care gibi kisisel bakim ornekleri.
- Genel giderler: elektrik, internet, kira, e-fatura servisi.
- Adres sinyali: isyeri adresiyle eslesen veya eslesmeyen elektrik/internet.
- Karsi cari bulunamadi senaryosu.
- Mustavir duzeltmesinin sonraki benzer belgede oneriyi degistirmesi.
