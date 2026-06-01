# Fisora Uygulama Yol Haritasi

## Mevcut Durum

Tamamlanan ana dilimler:

- Muhasebe domain cekirdegi: hesap plani importu, fis taslagi, risk bayraklari.
- Business relevance: faaliyet/NACE baglami, marka-model kategori siniflandirma.
- Cari eslestirme: VKN/TCKN, unvan benzerligi, review fallback.
- Review ve learning modeli: mustavir karari, learning event, otomasyon adayi.
- Export gate: sadece guvenli ve dengeli kayitlar export paketine girer.
- MVP portal: belge listesi, review kuyrugu, export hazir gorunumu.
- API scaffold: onboarding, simulation, review, export, store endpointleri.
- Yerel store: `exports/phase0_store.json` ile ignored demo/pilot snapshot.
- AI adapter: statik kural once, AI sadece belirsiz kalemde, JSON schema guard.
- Sentetik pilot: 3 belgeyle uc uca store + review + export CSV kosusu.
- Learning rule uygulama: mustavir duzeltmesi sonraki benzer belgede oneriyi etkiler.
- Portal ilk UI dilimi: mukellef yukleme alani ve mustavir review calisma masasi.

## Siradaki 5 Adim

1. Portal UI dilimini API'ye baglama
   - Mukellef yukleme, belge listesi, fatura onizleme ve fis taslagi ekranlari mock veriden store/API verisine tasinir.
   - Durum: UI iskeleti baslatildi; gercek upload endpointi ve dosya saklama eksik.

2. Gercek upload ve dosya saklama
   - PDF/XML/CSV/XLSX dosyasi mukellef, yukleyen kullanici, belge turu ve isleme durumu ile kaydedilir.
   - Ham belge ile turetilmis parse/AI/export ciktisi ayrilir.

3. Workspace formatina portal uyumu
   - Portal `local-review-data.json` disinda store/workspace snapshot formatini da okuyabilir.
   - Amac: pilot runner ciktisini UI'da direkt gostermek.

4. Banka/POS parse ve matching
   - Ekstre satirlari banka aciklamasi, tutar, tarih ve cari adayiyla review/export gate'e baglanir.
   - Ilk hedef: GIB, SGK, POS bloke, banka tahsilat/odeme taslaklari.

5. Gercek AI provider adapter ve pilot benchmark
   - `FISORA_AI_PROVIDER=disabled|openai|gemini|manus` secimi.
   - Ilk entegrasyonda sadece siniflandirma/gerekce uretimi; muhasebe karari yok.
   - Iki pilot mukellefle 20-50 fatura ve 1-2 ekstre uzerinden maliyet/dogruluk olculur.

Sonraki saha kilidi: Zirve export formati gercek programda denenmeden "tamam" sayilmaz.

## Genel Kalan Is Haritasi

```mermaid
flowchart TD
    A["MVP domain cekirdegi"] --> B["Musteri onboarding ve hesap plani"]
    B --> C["Mukellef upload portali"]
    C --> D["Belge parse ve invoice line cikarma"]
    D --> E["Kategori, cari ve muhasebe taslagi"]
    E --> F["Risk gate ve mustavir review ekrani"]
    F --> G["Learning rule uygulama"]
    G --> H["Kontrollu export CSV"]
    H --> I["Portal API ve workspace baglantisi"]
    I --> J["Gercek pilot veri kosusu"]
    J --> K["Zirve saha dogrulamasi"]
    K --> L["PostgreSQL adapter ve auth"]
    L --> M["AI provider A/B benchmark"]
    M --> N["Canli MVP"]
```

## Kapanmamis Ana Basliklar

- Auth ve yetki: Serbest uyelik yok; kullanici bastan mukellefe bagli olmali.
- PostgreSQL adapter: Yerel JSON store yerine production repository.
- Dosya saklama: PDF/XML/ekstre ve turetilmis JSON/CSV ayrimi, retention politikasi.
- Banka/POS akisi: UI yukleme alani var; parse ve matching katmani genisleyecek.
- Mustavir calisma masasi: fatura gorunumu, fis taslagi ve karar paneli API'ye baglanacak.
- Zirve format kesinligi: Gercek import dosyasiyla saha testi sart.
- AI provider secimi: OpenAI/Gemini/Manus kararini pilot benchmark belirlemeli.
- Maliyet limiti: Belge basina AI cagrisi, token/karakter limiti ve aylik cap.
- Denetim izi: Kim yukledi, kim onayladi, ne degisti, hangi kurala donustu.
