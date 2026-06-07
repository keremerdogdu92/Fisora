# AI Destekli Taslak ve Hazirlik Plani

## Karar

Fisora soguk baslangicta, yani gecmis yevmiye veya yeterli mustavir karari
yokken, tamamen bos bir review ekrani gostermemelidir. Sistem AI destekli
taslak modu ile faturadan muhasebe fisi adayi, kategori, gerekce, guven skoru
ve risk bayragi uretir.

Bu karar "AI kesin kayit atar" anlamina gelmez. AI ilk taslagi hazirlar;
deterministik motor tutar, KDV, borc/alacak dengesi, hesap plani ve export
kapisini kontrol eder; mustavir son karari verir.

## Calisma Modlari

| Mod | Ne zaman kullanilir? | Export davranisi |
|---|---|---|
| `conservative` | AI kapali veya guven dusuk | Tum kayitlar review ister |
| `ai_assisted_draft` | Gecmis veri az, demo/pilot veya yeni mukellef | AI taslak hazirlar, mustavir onayi olmadan export yok |
| `controlled_automation` | En az 3 tutarli onay ve mustavir politikasi var | Dusuk riskli kayitlar export adayi olabilir |

Ilk demo ve ilk canli surum icin varsayilan mod `ai_assisted_draft` olmalidir.
Bu mod satis gucunu artirir, cunku mustavir bos form doldurmak yerine hazir bir
taslagi duzeltir. Guvenlik cizgisi korunur, cunku export ve kesin kayit karari
mustavir onayi veya mustavir politikasi olmadan acilmaz.

## Hazir Olmak Icin Gerekenler

### 1. Minimum pilot veri paketi

Her pilot mukellef icin en az sunlar gerekir:

- Mukellef unvani, VKN/TCKN ve faaliyet/NACE veya faaliyet aciklamasi.
- Isyeri adresi ve varsa sube adresleri.
- Zirve hesap plani exportu.
- Mukellefe bagli portal kullanicisi.
- 20-50 fatura veya anonimlestirilmis fatura.
- 1 banka Excel/CSV ekstresi.
- Varsa cari liste, yevmiye, muavin veya fis listesi.
- Varsa Zirve'nin kabul ettigi ornek import dosyasi.

Gecmis yevmiye/muavin yoksa bu blokaj degildir. Sadece sistem daha fazla kaydi
`review_required` durumuna dusurur ve ogrenmeyi mustavir onaylarindan baslatir.

### 2. Belge ve tutar guvenligi

AI devreye girmeden once deterministic katman sunlari uretmelidir:

- Belge mukellef ve yukleyen kullanici baglantisi.
- Text PDF, XML, CSV veya XLSX parse sonucu.
- Fatura kalemleri, matrah, KDV, toplam tutar ve tarih.
- Borc/alacak dengesi.
- Karsi cari adayi veya cari bulunamadi bayragi.
- Hesap plani icinden secilebilir hesap adaylari.

Tutar, KDV ve denge AI'a birakilmaz. AI ancak siniflandirma, gerekce ve hesap
adayi seciminde yardimci olur.

### 3. AI adapter hazirligi

AI cagrisi su sozlesmeyle sinirlanmalidir:

```json
{
  "product_category": "string",
  "business_relevance": "uygun | genel_gider | supheli | is_alani_disi",
  "suggested_account_code": "existing_chart_account_or_null",
  "confidence": 0.0,
  "reason": "short explanation",
  "risk_flags": ["string"],
  "review_required": true
}
```

AI'a verilen baglam:

- Ham PDF/XML/ekstre dosyasi degil, parser'in cikardigi sinirli metin.
- Mukellef faaliyet/NACE aciklamasi veya kisa faaliyet ozeti.
- Mevcut hesap plani adaylari.
- Cari adaylari.
- Belge tipi, tutar/KDV sinyali ve risk bayraklari.
- Varsa gecmis mustavir kararlarindan turetilen ozet sinyal.

Kapali server demo env karari:

```text
FISORA_AI_PROVIDER=groq
FISORA_AI_MODEL=openai/gpt-oss-20b
FISORA_AI_COMPARISON_MODEL=openai/gpt-oss-120b
FISORA_AI_MONTHLY_CAP_USD=0.01
GROQ_API_KEY=server-env-only
```

Groq, mustavir oncesi ucretsiz/limitli test hatti olarak kullanilir. Gercek
musteri verisinde yine ham PDF/XML/ekstre gonderilmez; yalnizca parser'in
sinirladigi JSON payload gonderilir. Ucretli OpenAI kalite kiyasina gecilecekse
ayni env yapisi `FISORA_AI_PROVIDER=openai` ve `OPENAI_API_KEY` ile calisir.

AI su islemleri yapamaz:

- Yeni detay hesap kodu uyduramaz.
- Gider yazilir/yazilmaz kararini kesinlestiremez.
- Mustavir onayi olmadan export'a izin veremez.
- KDV, tevkifat, iade veya istisna gibi riskli kararlar icin son karar veremez.

### 4. Review ekrani hazirligi

Mustavire gosterilecek minimum ekran:

- Secili mukellef adi ve kart bilgisi.
- O an incelenen fatura/ekstre onizlemesi.
- Fatura kalemleri ve AI/kural kategori gerekcesi.
- AI provider, guven, hesap onerisi, cari onerisi ve "neden bu hesap/cari"
  gerekcesi.
- Onerilen muhasebe fisi.
- Borc/alacak dengesi.
- Cari ve hesap plani eslesme guveni.
- Risk bayraklari ve export gate nedeni.
- Onayla, duzelt ve onayla, export disi birak, is alani disi aksiyonlari.

Demo icin kritik mesaj: mustavir AI'in sonucunu sifirdan uretmek zorunda
kalmaz; sadece duzeltir, onaylar veya reddeder.

### 5. Export guvenligi

Soguk baslangicta AI tarafindan hazirlanan hicbir taslak tek basina export'a
girmez. Export icin en az bir kosul gerekir:

- Mustavir kaydi onaylamis olmalidir.
- Veya mustavir/ofis politikasi ilgili tekrar eden islem tipine izin vermis
  olmalidir.

Asagidaki durumlarda export kapali kalir:

- Cari bulunamadi veya dusuk guvenli.
- Hesap plani adayi yok.
- Is alani disi veya supheli kategori.
- Karma KDV, tevkifat, iade, istisna, OIV/OTV.
- Borc/alacak dengesiz.
- AI confidence dusuk.
- Belge parse sonucu eksik.

## Demo ve Pilot Stratejisi

Mali mustavire anlatilacak gercekci ifade:

```text
Baslangicta sistem AI ile size bos olmayan bir fis taslagi hazirlar.
Siz bunu onaylar veya duzeltirsiniz.
Duzelttiginiz kararlar sistemde ogrenme verisi olur.
Tekrarlayan ve dusuk riskli islemler zamanla daha az kontrol ister.
```

Gercek fatura ile demo yapilacaksa veri akisi:

1. Fatura ve mukellef bilgisi sadece lokal ortamda denenir.
2. Ham PDF/XML/ekstre repoya veya public demo ortamina eklenmez.
3. Dis AI API kullanilacaksa once mustavirden ve ilgili veri sahibi taraftan
   acik onay veya anonimlestirme karari alinir.
4. Public demo icin yalnizca sentetik veya anonimlestirilmis veri kullanilir.

## Basari Kriterleri

- Gecmis veri olmayan mukellefte bile sistem makul bir fis taslagi uretebilir.
- KDV, matrah ve toplam tutar deterministic motorla dogru tasinir.
- AI belirsiz kalemi gerekce ve riskle review'a dusurur.
- AI sadece mevcut hesap planindan hesap onerebilir.
- Mustavir duzeltmesi learning event olarak saklanir.
- Ayni karar en az 3 kez tutarli onaylaninca otomasyon adayi olur.
- Export paketine AI'in tek basina hazirladigi riskli kayit girmez.

## Hemen Yapilacak Hazirliklar

1. AI assisted draft modunu backend payload'inda acik bir durum olarak tut.
2. Review ekraninda AI/kural gerekcesini ve export gate nedenini yan yana goster.
3. AI provider benchmark setine gercekci marka/model ve genel gider ornekleri
   ekle.
4. Mustavir demo akisinda "AI taslagi hazirlar, mustavir son karari verir"
   mesajini ana anlatim yap.
5. Pilot veri alinana kadar public demoyu sentetik veriyle, gercek testi lokal
   veriyle ayri tut.
