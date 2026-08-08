# AI-first mukellef ve fatura isleme akisi

Durum: Taslak, 2026-07-03

Bu dokuman mukellef olusturmadan fatura taslaginin onaya gelmesine kadar sistemin nasil calismasi gerektigini netlestirir. Ana hedef, musavirin isini azaltan AI-first bir akis kurmak; ama kanitli ogrenme, yasal kurallar ve ihrac/aktarim guvenligi varken bunlari AI'in onune dogru sirayla koymaktir.

## Temel kararlar

1. Vergi levhasi alanlari pilot icin zorunlu kabul edilir.
   Parser TCKN/VKN, unvan, NACE/faaliyet ve adres alanlarini okumaya calisir. Okuyamazsa bu "normal kabul edilen eksik veri" degil, onboarding eksigi olarak gorulur ve musavir ekranda tamamlar. AI-first fatura isleme icin en az vergi kimligi, unvan/gorunen ad, NACE/faaliyet ve hesap plani tamamlanmis olmalidir.

2. NACE/faaliyet contexte zorunlu girer.
   NACE bir kere normalize edilip arastirildiktan sonra sonuc yerel bilgi havuzunda saklanir. Ayni NACE baska mukellefte gelirse tekrar internet arastirmasi yapmadan kayitli profil kullanilir. Yeniden arastirma sadece manuel refresh, cache boslugu veya dusuk kaliteli eski kayit varsa calismalidir.

3. AI-first varsayimdir.
   Yeterince guvenilir ogrenilmis kural veya birebir eslesen yuksek guvenli gecmis karar yoksa sistem statik motor dusuk guven verdi diye durmamalidir. AI'a yon, faaliyet, NACE ozeti, hesap plani adaylari, fatura satirlari ve cari adaylari verilerek cozum istenir. Gerekirse arastirma AI'i devreye girer.

4. Yasal/muhasebesel sert kurallar onde gelir.
   KDV ayrimi, belge yonu, ihrac/aktarim hazirligi, borc-alacak dengesi, indirilemez gider gibi sert riskler AI sonucu ne olursa olsun kontrol edilir. Guven yoksa taslak olusur ama review gate acik kalir.

5. Ogrenme AI'i azaltir, denetimi kaldirmaz.
   Musavirin onaylari ve duzeltmeleri ayni cari, ayni urun/hizmet, ayni hesap mantigi icin sonraki onerileri guclendirir. Tek bir karar kalici otomasyon icin yeterli sayilmamalidir; tekrarli ve tutarli onaylar yuksek guvenli ogrenme haline gelince AI/research maliyeti azaltilabilir.

## PDF extraction redesign: kabul edilen kararlar (2026-08-05)

> **Tarihsel not / superseded (2026-08-07):** Bu bolumdeki eski
> `pdfplumber-only` prompt, kapali ilk schema ve onceki benchmark modeli artik
> guncel test sozlesmesi degildir. Guncel A/B/C giris modlari, prompt, schema,
> dogruluk katmanlari ve yeni corpus kararlari
> [`pdf-ai-extraction-benchmark-contract.md`](pdf-ai-extraction-benchmark-contract.md)
> belgesinde kanoniktir. Asagidaki metin yalniz karar gecmisini korur.

Durum: Tasarim kararlari kabul edildi; runtime koduna henuz uygulanmadi. Gercek
fatura benchmark sonuclari yeni kanit getirirse bu kararlar yeniden incelenebilir.
Bu bolum, uygulandiginda asagidaki `7. Parse sonucu` bolumunun PDF extraction
kismini ayrintilandiracak ve o kisim icin oncelikli tasarim karari olacaktir.

### Kabul edilen veri akisi

```text
PDF
-> pdfplumber
-> pdfplumber'in urettigi ham giris paketi
-> AI
-> normalize edilmis UBL-core JSON cikti
-> cikti kontrolu
```

AI'dan once yalniz teknik JSON paketlemesi yapilir. Pdfplumber'in cikardigi
icerik duzeltilmez, normalize edilmez, filtrelenmez veya kayipli bicimde
birleştirilmez. AI'a su temsiller birlikte verilir:

- `plain_text`
- `layout_text`
- `words`
- word koordinatlari
- `table_candidates`

Metin, satir, sutun, paragraf ve tablo yapisi icin ek bir deterministik yorum
katmani AI'in onune konmaz. `table_candidates` yalniz yerlesim onerisi olarak
sunulur. Okunabilen icerik atilmaz. AI normalizasyonu yalniz cikti JSON'unu
uretirken yapar.

### Kabul edilen provider promptu - Turkce

```text
ROL VE TEMEL GÖREV

Sen bir fatura belge çıkarım motorusun.

Yalnızca kullanıcı mesajında sağlanan, PDF'den önceden çıkarılmış metin, kelime, koordinat ve tablo adayı verilerini kullanarak faturada gözlemlenen bilgileri çıkar; bu giriş verilerinin dışında bilgi kullanma.

Amaç, muhasebe kararı vermeden, faturanın yeniden oluşturulmasına yetecek en iyi yapısal belge verisini üretmektir.

Girişteki plain_text, layout_text, words, coordinates ve table_candidates aynı PDF'nin farklı temsilleridir. Aynı bilgi birden fazla temsilde tekrar edebilir; tekrarları ayrı fatura verileri olarak değerlendirme.

Metin parçalarının içerikleri belge gözlemidir. Bunların satır, sütun, paragraf ve tablo halinde gruplanması ile koordinat ilişkileri hatalı veya eksik olabilir. Bu yapısal bilgileri birlikte değerlendir, ancak kesin gerçek olarak kabul etme.

table_candidates yalnızca muhtemel satır ve sütun ilişkilerini gösteren bir yerleşim önerisidir; tek başına doğruluk kaynağı değildir.

TARAF TANIMA VE ROL BAĞLAMA

supplier_party, faturayı düzenleyen ve mal veya hizmeti sağlayan taraftır.

customer_party, faturanın adına düzenlendiği ve mal veya hizmeti alan taraftır.

"SAYIN", "ALICI", "MÜŞTERİ", "Müş V.D.", "Fatura Edilen" ve eşdeğer alıcı başlıkları customer party için güçlü kanıttır.

Fatura numarası, vergi dairesi, ticaret sicili veya MERSİS bilgisi, iletişim bilgileri, ödeme bilgileri ya da düzenleyen başlığı kendi şirket bilgisi olarak bulunan işletme normalde supplier party'dir.

Gözlemlenen her tarafı ayrı bir belge bloğu olarak değerlendir.

Bir tarafın unvanı ile vergi kimliklerini yalnızca belgenin bunların aynı taraf bloğuna ait olduğunu desteklediği durumda bağla. Bu ilişkilendirme için etiketleri, yakın metni, hizalamayı, koordinatları, vergi dairesini, adresi, ticaret sicili veya MERSİS bağlamını birlikte değerlendir.

Bir vergi kimliğini yalnızca en açık veya açıkça "VKN", "TCKN" ya da "Vergi No" etiketi taşıyan değer olduğu için supplier_party altına yerleştirme. Önce kimliğin gözlemlenen hangi taraf bloğuna ait olduğunu belirle.

Şirket ve vergi dairesi bloğunda bulunan 10 haneli bir sayı, ayrı bir "VKN" etiketi bulunmasa bile o şirketin VKN'si olabilir. Açıkça gözlemlenen 11 haneli TCKN, içinde bulunduğu kişi veya taraf bloğuyla ilişkilendirilmelidir.

Bir taraf bloğundaki unvanı başka bir taraf bloğundaki vergi kimliğiyle birleştirme.

Hem supplier hem customer kimlikleri bulunuyorsa her kimliği en iyi desteklenen taraf bloğuna yerleştir. Başka bir kimliğin etiketi daha açık olduğu için daha az belirgin etiketli kimliği göz ardı etme.

Aynı vergi kimliğini yalnızca plain_text, layout_text, words veya table_candidates içinde tekrarlandığı için hem supplier_party hem customer_party altına yerleştirme. Bunlar aynı belge gözleminin tekrarlanan temsilleridir.

İlişkilendirme tamamen kesin değilse yine en iyi desteklenen taraf bağlamasını döndür ve belirsizliği warnings içinde açıkla. Etiketi daha açık olduğu için kimliği diğer tarafa taşıma.

Belgede açıkça bulunmayan bir değeri dış bilgiden tahmin etme, uydurma veya başka alanlardan hesaplayarak doldurma.

Kullanılabilir kaynak gözlemleri bulunduğunda, işi tamamlamak yerine null, review_required veya başarısız bir heuristic'i kolay bir kaçış yolu olarak kullanma.

Bir alan için yalnızca kullanılabilir hiçbir kaynak gözlemi bulunmuyorsa null kullan.

Çözümlenemeyen bir alan, ilgisiz alanların çıkarılmasını veya taslak hazırlanmasını durdurmamalıdır.

Bir alanla ilişkili bir veya daha fazla olası değer giriş verisinde bulunuyorsa, yalnızca yerleşim, okuma sırası veya tablo ilişkisindeki belirsizlik nedeniyle null döndürme. Mevcut temsilleri birlikte değerlendirerek belge içindeki en iyi desteklenen değeri çıkar.

Seçilen değer tamamen kesin değilse yine en iyi desteklenen değeri döndür ve belirsizliği çıktıdaki warning yapısında açıkla.
```

### Accepted provider prompt - English

```text
ROLE AND PRIMARY TASK

You are an invoice document extraction engine.

Use only the text, word, coordinate, and table-candidate data previously extracted from the PDF and provided in the user message to extract the information observed in the invoice. Do not use information outside this input data.

The objective is to produce the best structured document data sufficient to reconstruct the invoice, without making accounting decisions.

The plain_text, layout_text, words, coordinates, and table_candidates in the input are different representations of the same PDF. The same information may appear in multiple representations; do not treat these repetitions as separate invoice data.

The contents of the text fragments are document observations. Their grouping into lines, columns, paragraphs, and tables, as well as their coordinate relationships, may be incorrect or incomplete. Evaluate this structural information together, but do not treat it as definitive truth.

table_candidates only suggests possible row and column relationships; it is not an independent source of truth.

PARTY IDENTIFICATION AND ROLE BINDING

supplier_party is the party that issued the invoice and supplied the goods or services.

customer_party is the party to whom the invoice was issued and who received or purchased the goods or services.

Turkish labels such as "SAYIN", "ALICI", "MÜŞTERİ", "Müş V.D.", "Fatura Edilen" and equivalent recipient headings are strong evidence for the customer party.

The business whose invoice number, tax office, trade registry or MERSIS information, contact information, payment details, or issuer header appears as its own company information is normally the supplier party.

Treat each observed party as a separate document block.

Bind a party name and its tax identifiers only when the document supports that they belong to the same party block. Use labels, nearby text, alignment, coordinates, tax office, address, trade registry or MERSIS context together for this association.

Do not attach a tax identifier to supplier_party merely because it is the clearest or the only value explicitly labelled "VKN", "TCKN" or "Vergi No". First determine which observed party block the identifier belongs to.

A 10-digit number located in a company and tax-office block may be that company's VKN even when the separate "VKN" label is absent. A clearly observed 11-digit TCKN must be associated with the person or party block in which it appears.

Do not combine the name from one party block with a tax identifier from another party block.

When both supplier and customer identifiers are present, assign each identifier to the best-supported party block. Do not discard the less prominently labelled identifier solely because another identifier has a clearer label.

Do not place the same tax identifier under both supplier_party and customer_party merely because it is repeated in plain_text, layout_text, words or table_candidates. These are repeated representations of the same document observation.

If the association is not completely certain, still return the best-supported party binding and describe the uncertainty in warnings. Do not move an identifier to the other party merely because its label is more explicit.

Do not estimate or invent a value that is not explicitly present in the document, and do not fill it by calculating it from other fields.

When usable source observations exist, do not use null, review_required, or a failed heuristic as an easy fallback instead of completing the work.

Use null only when no usable source observation exists for that field.

An unresolved field should not stop unrelated extraction or draft preparation.

If the input contains one or more possible values related to a field, do not return null solely because of uncertainty in layout, reading order, or table relationships. Evaluate the available representations together and extract the best-supported value from the document.

If the selected value is not completely certain, still return the best-supported value and describe the uncertainty in the output warning structure.
```

### Kabul edilen cikti omurgasi: UBL-core projection

UBL, alan isimlendirme kaynagi, hiyerarsi omurgasi ve yeni alan ekleme kontrol
listesi olarak kullanilir. AI'dan tam UBL XML veya UBL'nin butun opsiyonel
alanlari istenmez. PDF ve XML ciktilarinin ayni semantik yapida bulusabilecegi,
AI icin sadelestirilmis JSON hedeflenir.

```json
{
  "invoice": {
    "header": {
      "invoice_number": null,
      "uuid": null,
      "issue_date": null,
      "issue_time": null,
      "due_date": null,
      "invoice_type_code": null,
      "profile_id": null,
      "tax_point_date": null,
      "document_currency_code": null,
      "tax_currency_code": null,
      "buyer_reference": null,
      "notes": []
    },
    "invoice_periods": [],
    "document_references": {
      "order_reference": null,
      "billing_references": [],
      "despatch_document_references": [],
      "receipt_document_references": [],
      "contract_document_references": [],
      "additional_document_references": []
    },
    "supplier_party": {
      "name": null,
      "tax_identifiers": []
    },
    "customer_party": {
      "name": null,
      "tax_identifiers": []
    },
    "payee_party": null,
    "delivery": [],
    "payment_means": [],
    "payment_terms": [],
    "exchange_rates": [],
    "allowance_charges": [],
    "vat_breakdown": [],
    "withholding_tax_totals": [],
    "totals": {
      "tax_exclusive_amount": null,
      "vat_amount": null,
      "tax_inclusive_amount": null,
      "payable_amount": null
    },
    "invoice_lines": []
  },
  "warnings": []
}
```

Serbest `additional_fields` veya modelin kendi anahtarlarini uretebildigi bir
nesne acilmaz. Yeni bir alan ihtiyaci gercek corpus veya benchmark kanitiyla
ciktiginda once UBL karsiligi aranir. `Note`, `InvoicePeriod`,
`BillingReference`, `ContractDocumentReference` veya
`AdditionalDocumentReference` gibi tanimli yapiya oturuyorsa oraya eklenir.
Oturmuyorsa adi ve anlami belirli yeni nullable alan schema'ya bilincli olarak
eklenir. Ham pdfplumber girdisi korundugu icin eski belgeler yeni schema ile
yeniden islenebilir.

### Kabul edilen ortak JSON deger kurallari

```text
Metinler          -> string | null
Tarihler          -> YYYY-MM-DD biciminde string | null
Saatler           -> HH:MM:SS biciminde string | null
Parasal degerler  -> decimal string | null
Miktarlar         -> decimal string | null
Oranlar           -> decimal string | null
Boolean alanlar   -> true | false | null
Tekil nesneler    -> object | null
Coklu alanlar     -> array; deger yoksa []
```

- Bos string `""` kullanilmaz.
- Binlik ayirici kullanilmaz; ondalik ayirici noktadir.
- Para simgesi parasal degerin icine yazilmaz.
- `1.250,50 TL` cikti JSON'unda tutar olarak `"1250.50"`, para birimi olarak
  `"TRY"` olur.
- `%20` oran olarak `"20"` olur.
- Belgede gercekten sifir olan deger sifir olarak doner; eksik deger `null`
  olur.
- Schema anahtarlari cevapta bulunur. Eksik tekil deger `null`, eksik coklu
  deger `[]` olur.
- Raw pdfplumber girdisi normalize edilmis JSON'un yerine gecmez ve ayrica
  korunur.

### Kabul edilen yon belirleme sozlesmesi

QNB’den gelen belgelerde fatura yönünün kesin kaynağı QNB gelen/giden kanalıdır. UBL taraf kimlikleri yalnızca tutarlılık amacıyla değerlendirilebilir ve QNB’nin bildirdiği yönü değiştirmez.

QNB dışındaki PDF ve doğrudan yüklenen UBL belgelerinde yön, mükellefin VKN veya TCKN’sinin `supplier_party` ve `customer_party` ile tam eşleştirilmesiyle deterministik olarak belirlenir. Mükellef satıcıyla eşleşirse satış, alıcıyla eşleşirse alış yönü seçilir. Yalnızca mükellefin tek tarafta eşleşmesi yeterlidir; karşı tarafın ayrıca doğrulanması gerekmez.

PDF’de AI yön seçmez. AI yalnızca belgede gözlemlediği satıcı, alıcı ve bunların VKN/TCKN bilgilerini JSON alanlarına yerleştirir. Yön kararı bu JSON üzerinden program tarafından verilir.

QNB dışındaki yüklemelerde kullanıcının seçtiği alış/satış bölümü destekleyici yön bilgisidir. VKN/TCKN eşleşmesiyle çelişirse tam kimlik eşleşmesi esas alınır ve çelişki belirtilir. Hiçbir taraf eşleşmezse veya iki taraf birden eşleşirse yükleme bölümündeki yön kullanılır ve kimlik eşleşmesinin çözülemediği belirtilir.

Yön belirlemek için bulanık unvan, adres, vergi dairesi veya çok alanlı puanlama kullanılmaz. Önce gerçek fatura testlerinde tam VKN/TCKN eşleşmesinin başarısı ölçülür; ihtiyaç ancak test kanıtıyla ortaya çıkarsa yöntem genişletilir.

### Kabul edilen minimum supplier/customer Party yapisi

`supplier_party` ve `customer_party` ayni yapidadir:

```json
{
  "name": "Örnek Teknoloji A.Ş.",
  "tax_identifiers": [
    {
      "scheme_id": "VKN",
      "value": "1234567890"
    }
  ]
}
```

- `name`, belgede bulunan en uygun tam şirket unvanı veya kişi adıdır.
- `tax_identifiers` yalnızca gözlemlenen VKN/TCKN değerlerini içerir.
- `scheme_id`, `"VKN"`, `"TCKN"` veya tür belirlenemiyorsa `null` olur.
- `value`, baştaki sıfırlar korunarak, boşluk ve ayraçları kaldırılmış rakam dizisidir.
- Aynı kimlik belgede tekrarlanıyorsa JSON'da bir kez bulunur.
- Kimlik bulunmuyorsa `tax_identifiers: []`; isim bulunmuyorsa `name: null` olur.
- Yön için unvan kullanılmaz; yalnız tam `value` eşleşmesi kullanılır.
- Birden fazla vergi kimliği gözlemi varsa değerler kaybedilmez. Yön eşleştirmesi puanlama yapmadan mükellef VKN/TCKN'sini `tax_identifiers[].value` içinde tam olarak arar.
- Adres, vergi dairesi, MERSİS ve iletişim bilgileri bu minimum yön çekirdeğine dahil edilmez. Gerçek testler ihtiyaç gösterirse Party şeması genişletilir.

### Kabul edilen minimum satir, KDV dagilimi ve toplam yapisi

```json
{
  "supplier_party": {
    "name": "Satıcı Firma A.Ş.",
    "tax_identifiers": [
      {
        "scheme_id": "VKN",
        "value": "1111111111"
      }
    ]
  },
  "customer_party": {
    "name": "Alıcı Firma Ltd. Şti.",
    "tax_identifiers": [
      {
        "scheme_id": "VKN",
        "value": "2222222222"
      }
    ]
  },
  "invoice_lines": [
    {
      "description": "Yazılım hizmet bedeli",
      "quantity": "2",
      "unit": "Adet",
      "unit_price": "500.00",
      "tax_exclusive_amount": "1000.00",
      "vat_rate": "20",
      "vat_amount": "200.00",
      "tax_inclusive_amount": "1200.00"
    }
  ],
  "vat_breakdown": [
    {
      "vat_rate": "20",
      "tax_exclusive_amount": "1000.00",
      "vat_amount": "200.00",
      "tax_inclusive_amount": "1200.00"
    }
  ],
  "totals": {
    "tax_exclusive_amount": "1000.00",
    "vat_amount": "200.00",
    "tax_inclusive_amount": "1200.00",
    "payable_amount": "1200.00"
  }
}
```

- `invoice_lines`, her ürün veya hizmet satırını ve satırın kendi KDV bilgisini ayrı tutar.
- `vat_breakdown`, her KDV oranının KDV hariç tutarını, KDV tutarını ve KDV dahil tutarını ayrı kayıt olarak tutar.
- `totals.tax_exclusive_amount`, faturanın toplam KDV hariç tutarıdır.
- `totals.vat_amount`, faturadaki toplam KDV'dir.
- `totals.tax_inclusive_amount`, faturanın toplam KDV dahil tutarıdır.
- `totals.payable_amount`, gerçek ödenecek tutardır. Tevkifat, iskonto, yuvarlama veya önceki ödeme nedeniyle `tax_inclusive_amount` değerinden farklı olabilir.
- Faturadaki satırlar birleştirilmez veya toplulaştırılmaz. Aynı açıklamaya sahip iki satır iki ayrı JSON satırı olarak kalır.
- Bir satırdaki bazı alanlar eksikse satır atılmaz; bulunan alanlar doldurulur, bulunmayanlar `null` olur.
- AI yalnızca belgede açıkça bulunan değerleri doldurur. Belgede KDV dahil satır veya oran grubu toplamı yazmıyorsa AI bunu diğer alanlardan hesaplamaz; ilgili alan `null` olur. Hesaplama ve karşılaştırma AI sonrası kontrol aşamasında ayrıca kararlaştırılır.

### Kabul edilen pdfplumber giris paketi

```json
{
  "pdfplumber_package": {
    "page_count": 1,
    "pages": [
      {
        "page_number": 1,
        "width": 595.28,
        "height": 841.89,
        "plain_text": "FATURA\nSatıcı Firma A.Ş.\nVKN: 1111111111...",
        "layout_text": "FATURA\n\nSatıcı Firma A.Ş.              Alıcı Firma Ltd...\nVKN: 1111111111                VKN: 2222222222...",
        "words": [
          {
            "word_id": "p1_w0001",
            "text": "FATURA",
            "x0": 245.12,
            "top": 35.4,
            "x1": 298.7,
            "bottom": 47.2,
            "doctop": 35.4
          }
        ],
        "table_candidates": [
          {
            "table_id": "p1_t0001",
            "bbox": [40.2, 260.1, 555.4, 520.8],
            "rows": [
              ["Açıklama", "Miktar", "Birim Fiyat", "KDV", "Tutar"],
              ["Yazılım hizmeti", "2 Adet", "500,00", "%20", "1.000,00"]
            ]
          }
        ]
      }
    ]
  }
}
```

- Her sayfa kendi `plain_text`, `layout_text`, `words` ve `table_candidates` verisini taşır.
- Sayfa ve kelime sırası pdfplumber'ın verdiği haliyle korunur.
- Metin düzeltilmez, birleştirilmez, filtrelenmez veya normalize edilmez.
- Koordinatlar pdfplumber'ın verdiği değerlerdir.
- `word_id` yalnızca teknik paketleme kimliğidir. Şimdilik AI çıktısından bu kimliği geri istemiyoruz.
- `table_candidates.rows` yalnızca pdfplumber'ın bulduğu muhtemel tablo düzenidir; doğruluk kaynağı değildir.
- Tablo bulunamazsa `table_candidates: []` olur; sayfanın diğer içeriği yine gönderilir.
- PDF dosyasının kendisi veya sayfa görseli AI'a gönderilmez.
- Herhangi bir temsilde tekrar eden metin silinmez; AI bunların aynı belgenin farklı temsilleri olduğunu prompttan bilir.

### Kabul edilen ilk benchmark modeli ve inference ayarlari

İlk benchmark, mevcut sistemdeki provider/model seçenekleri kullanılarak yapılır. İlk koşu NVIDIA üzerindeki `openai/gpt-oss-120b` modeliyle başlar. Bu seçim kalıcı üretim modeli kararı değildir; aynı pdfplumber paketi, prompt ve JSON şeması içerideki diğer modellerle de karşılaştırılabilir.

```text
model               = openai/gpt-oss-120b
provider            = NVIDIA
temperature         = 0
top_p               = 1
max_output_tokens   = 8192
timeout_seconds     = 120
response_format     = json_object
stream              = false
retry                = 0
```

- JSON şeması ve kabul edilen prompt isteğin içinde aynen gönderilir.
- İlk koşuda retry yapılmaz; provider'ın gerçek hata ve süre oranı ölçülür.
- Hız, doğruluk veya JSON uyumu yetersizse aynı giriş ve çıktı sözleşmesi değiştirilmeden mevcut diğer model/provider seçenekleri karşılaştırılır.

### Henuz karara baglanmayanlar

- `payee_party` alt alanlari ve benchmark sonucuna gore gerekebilecek ek Party alanlari
- `allowance_charges` ve `withholding_tax_totals` ayrintilari
- `delivery`, `payment_means`, `payment_terms` ve `exchange_rates` ayrintilari
- `warnings` nesnesinin tam schema'si
- evidence/word-ref stratejisinin benchmark sonrasi secimi
- yetkili gercek PDF corpus'u, ground truth ve benchmark metrikleri
- AI ciktisindan sonraki kontrol mantigi
- en son incelenecek gorsel insan kontrolu

## Uctan uca akis

### 1. Mukellef olusturma

Musavir mukellef olusturma ekranina gelir ve vergi levhasini yukler. Sistem vergi levhasi dosyasini saklar, metin/OCR katmanindan parser calistirir ve su alanlari doldurmaya calisir:

- TCKN/VKN veya normalize vergi kimligi
- Unvan, ticari unvan veya gorunen ad
- Vergi dairesi
- NACE kodu ve faaliyet aciklamasi
- Isyeri adresleri

Bu alanlar eksikse musavir ayni ekranda tamamlar. Dokumanin ham hali de parse sonucu da mukellef onboarding kaydinin parcasi olarak kalmalidir.

### 2. NACE/faaliyet arastirmasi

Buradaki NACE bizim mukellefin faaliyetidir, karsi firmanin NACE'i degildir.

Sistem normalize NACE kodu ve faaliyet aciklamasini arastirma ajanina verir. Ajanin gorevi sadece guzel bir metin yazmak degil; faaliyeti muhasebe diliyle anlasilir hale getirmek, faaliyet tagleri uretmek, hangi belge/urun tiplerinin normal veya supheli olduguna dair context olusturmaktir.

Beklenen cikti:

- Musavir ve ofis calisani icin sade Turkce faaliyet ozeti
- Faaliyet tagleri
- Sektor/alt sektor sinyali
- Fatura satiri yorumlamada kullanilacak faaliyet contexti
- Belge siniflandirmada review sebebi uretebilecek risk notlari

NACE arastirmasi fatura tarafinda yeniden ayni NACE icin internete cikmamalidir. Fatura islemede bu profil context olarak kullanilir.

### 3. Hesap plani yukleme

Vergi levhasi isi tamamlandiktan sonra hesap plani yuklenir. Ham hesap plani dosyasi saklanir, parser hesap kodlarini ve yardimci bilgileri normalize eder:

- Hesap kodu ve hesap adi
- Detay hesap olup olmadigi
- Cari hesaba ait olabilecek VKN/TCKN, IBAN, vergi dairesi gibi ipuclari
- Hesabin semantik rolu: stok, gider, satis geliri, KDV, musteri, satici vb.
- KDV orani veya kullanim tagleri gibi yardimci sinyaller

Hesap plani sadece dosya olarak saklanmaz; fatura islemede AI'a verilecek aday havuzunun ana kaynagi haline gelir.

### 4. Dosyalari mukellef ayarlarinda gosterme

Yapilacak is: Mukellefe tiklaninca mukellef ayarlari icinde vergi levhasi ve hesap plani gorulebilmeli/indirilebilmeli. Bu acil degil ama onboarding guveni icin backlog'a girmelidir.

### 5. Belge yukleme yetkisi

Fatura yukleme iki yoldan olur:

- Mukellef kendi sifresiyle kendi ekranina girer ve belge yukler.
- Musavir mukellef listesinden mukellefi secer, "bu mukellefe git" ile delegated client session acar ve o mukellef adina belge yukler.

Bu iki akis ayni belge isleme motorunu kullanir. Kritik fark audit bilgisidir. Belge kaydinda sunlar net tutulmalidir:

- Belge hangi mukellef workspace'ine yuklendi
- Etkin kullanici kimdi
- Yukleyen gercek aktor mukellef mi, musavir mi
- Musavir delegated session ile girdiyse `delegated_by_user_id`
- `delegated_client_id`
- Yukleme zamani ve kaynak ekrani/intake category

Mevcut auth akisi delegated session bilgisini tasiyor; dokuman metadata tarafinda bunun acik ve sorgulanabilir sekilde kalici hale getirilmesi gereksinimdir. Sonradan "bu belgeyi kim yukledi" sorusu tartismasiz cevaplanmalidir.

### 6. Fatura yukleme ve yon secimi

Faturalar yon secilerek yuklenir:

- Alis faturasi alis ekranindan
- Satis faturasi satis ekranindan

Bu secim ilk intake sinyalidir. Sistem yine de faturanin iceriginden yon kontrolu yapar. Belgedeki duzenleyen/alici vergi kimligi, mukellef unvani, fatura tipi ve intake category birlikte degerlendirilir. Secilen yon ile icerik catismasi varsa taslak uretilse bile review gate acilir.

### 7. Parse sonucu

Fatura PDF, text PDF, XML veya benzeri formatla gelebilir. Parse adimi su bilgileri cikarmaya calisir:

- Duzenleyen/satici bilgileri
- Alici bilgileri
- Vergi kimlikleri
- Fatura tarihi, numarasi, senaryo/tip bilgisi
- Satir aciklamalari, miktar, birim, tutar
- KDV oranlari ve KDV tutarlari
- Genel toplamlar
- Metin kaynaklari ve parse guven sinyalleri

Yani amac sadece birkac alana bakmak degildir; muhasebe onerisi icin yeterli bir yapisal fatura modeli olusturmaktir. Ancak her faturada tum alanlar ayni kalitede gelmez. Elektrik, dogal gaz, internet, telefon ve su faturalarinda satir/ozet alanlari genel e-fatura tiplerinden farkli olabilir. Bu belgelerde sistem satir aciklamasi, saglayici adi, belge tipi ve tutar/KDV yapisini birlikte kullanmali; format farki dusuk guven veya review sebebi olarak gorulebilmelidir.

### 8. Yon kontrolu ve hesap adayi daraltma

Parse sonrasinda sistem fatura yonunu tekrar kontrol eder. AI'a hesap plani tum karmasik haliyle verilmemelidir; yon ve belge tipiyle daraltilmis adaylar verilmelidir.

Ornek:

- Satis tarafinda: 600 satis gelirleri, 391 hesaplanan KDV, 120 musteri hesaplari ve ilgili detaylar
- Alis tarafinda: 153 stok, 7xx gider, 191 indirilecek KDV, 320 satici hesaplari ve ilgili detaylar
- Ozel durumlarda: indirilemeyen KDV, sabit kiymet, kanunen kabul edilmeyen gider veya review gerektiren hesap gruplari

Bu daraltma deterministik motorun gorevidir. AI bu aday havuzundan secim yapar veya adaylar yetersizse bunu gerekceyle belirtir.

### 9. AI-first karar patikasi

Sistem once elindeki kesin bilgileri ve yuksek guvenli ogrenmeleri kontrol eder:

1. Birebir ve yuksek guvenli ogrenilmis kural var mi?
2. Ayni cari + ayni urun/hizmet + ayni yon icin tekrarli tutarli onay var mi?
3. Sert muhasebe kuralinin sonucu acik mi?

Bu sorularin cevabi guvenliyse sistem bu bilgiyi one alir ve AI/research maliyetini azaltabilir. Degilse AI-first akis calisir.

AI'a verilen context:

- Mukellef unvani, vergi kimligi ve faaliyet bilgisi
- NACE kodu, NACE arastirma ozeti ve faaliyet tagleri
- Fatura yonu ve yon guven sinyali
- Parse edilmis fatura satirlari
- Satici/alici/cari adaylari
- Yonle filtrelenmis hesap plani adaylari
- Gecmis ogrenme sinyalleri

AI'dan beklenen cikti:

- Fatura kategori/oneri sinifi
- Uygun hesap veya hesap aday secimi
- Cari esleme onerisi
- Gerekce
- Guven skoru
- Risk flag'leri
- Gerekirse `needs_research` ve arastirma sorgusu

### 10. Urun/marka/faaliyet arastirmasi

Fatura satirindaki "urun adi" her zaman gercek urun adi olmayabilir; marka, model, hizmet paketi, abonelik aciklamasi veya teknik kod olabilir. Arastirma ajaninin fatura tarafindaki isi karsi firmanin NACE'ini kesin bulmak degildir. Burada ana soru sudur:

"Bu satir veya marka/hizmet neye benziyor ve mukellefin faaliyeti icinde hangi muhasebe davranisina daha yakin?"

Arastirma ajanina genelde su bilgiler gider:

- Satir aciklamasi/urun-hizmet ifadesi
- Satici unvani veya marka ipucu
- Mukellefin NACE/faaliyet contexti
- Fatura yonu

Bu adim su durumlarda calismalidir:

- AI satira yeterince guvenemiyorsa
- Urun/marka ilk kez goruluyorsa
- Statik siniflandirma ile faaliyet contexti uyusmuyorsa
- Belge tipi genel faturadan farkliysa
- Sabit kiymet, stok, gider, hizmet, indirilemez gider ayrimi belirsizse

Arastirma sonucu da cache'lenmelidir. Ayni marka/urun/hizmet tekrar geldiginde once bilgi havuzu kullanilir.

### 11. NACE ile urun arastirmasi catismasi

NACE/faaliyet contexti ile urun/marka arastirmasi farkli yone isaret ederse otomatik "biri kazanir" kuralimiz olmamali. Siralama soyle olmalidir:

1. Sert yasal/muhasebesel kural
2. Birebir, yuksek guvenli ve ilgili kapsamli ogrenilmis kural
3. Fatura yonu ve hesap plani aday uygunlugu
4. AI + urun/marka arastirmasi gerekcesi
5. NACE/faaliyet contextiyle uyum

Catismada sistem taslak uretmeli ama review sebebi yazmalidir. Ornek: "Satir arastirmasi stok gibi gorunuyor, ancak mukellef faaliyet profili hizmet agirlikli; hesap secimi onay gerektiriyor."

### 12. Cari esleme ve yeni cari onerisi

Parse sonucu cari bilgisi cikarsa sistem once hesap planindaki cari adaylarla eslestirir:

- Vergi kimligi birebir eslesiyorsa en guclu sinyal
- IBAN birebir eslesiyorsa cok guclu sinyal
- Unvan benzerligi tek basina daha riskli sinyal

Karsi firma ismini her zaman cok dogru cikaramayabiliriz. Bu nedenle sadece unvan benzerligiyle sessiz otomasyon yapilmamali; review sebebi kalabilir. Uygun cari bulunamazsa deterministik motor yeni cari onerir. Alis icin genelde 320, satis icin 120 grubu kullanilir. AI burada hangi cari mantiginin uygun oldugunu gerekcelendirir, ama yeni hesap kodu uretme standardi deterministik olmalidir.

### 13. Taslak fis ve UI

Sistem sonucunda musavirin onune bir taslak gelir:

- Belge yonu
- Secilen gider/stok/satis hesabi
- Secilen veya onerilen cari
- KDV hesaplari
- Satir gerekceleri
- AI guveni
- Arastirma ozeti
- Review sebepleri
- Export/aktarim hazirlik durumu

Musavir taslagi aynen onaylayabilir veya manuel degistirebilir. Degisiklik hem o belge kararina yazilir hem de ogrenme olayina donusur.

### 14. Ogrenme

Ogrenme iki seviyede dusunulur:

1. Dogal ogrenme:
   Musavir belgeyi duzelttikce sistem ayni cari, ayni urun/hizmet, ayni yon ve benzer faaliyet baglaminda sonraki onerileri iyilestirir.

2. Acik kural:
   Musavir bilerek "bu cariden gelenler her zaman stoktur" gibi bir kural yazabilir. Bu kural kapsam, kosul ve istisna mantigiyla saklanmalidir. Cok farkli durum olursa yine review gate acilabilmelidir.

Yuksek guvenli ogrenme olusmadan AI/research devreden cikarilmamalidir. Ogrenme guveni yeterince birikince sistem once o kurali uygular, AI'i sadece audit/gerekce veya dusuk guven durumunda cagirir.

### 14.1 Musavir ogrenme UX plani

Bu akisin hedefi musavire cok butonlu bir "programi egit" ekrani acmak
degil; normal review isini yaparken sistemin ne ogrendigini netlestirmektir.
Buton sayisi az tutulmali, asil guven "sistem bunu nasil anladigini" gosteren
onay formundan gelmelidir.

Iki ayri ogrenme yolu vardir:

1. Otomatik tekrar sinyali:
   Musavir hic not yazmasa bile ayni mukellef, ayni cari/VKN, ayni belge yonu
   ve ayni urun/hizmet mantiginda tutarli kararlar birikirse sistem bunu
   "kural adayi" olarak fark eder. Ornek: ayni stok faturasi 3 kez ayni sekilde
   onaylandiysa 4. benzer belgede veya 3. onaydan hemen sonra musavire
   "Bu faturadaki islemi kural olarak kaydetmek ister misiniz?" uyarisi
   gosterilebilir.

2. Acik musavir notu:
   Musavir bilincli olarak "bundan sonra bu VKN'den gelen faturalar kargo
   gideridir" veya "bu mukellefte Kolay Soft e-fatura hizmeti 770.05'e gider"
   gibi bir not yazar. Bu not tek alan olmali: `Karar notu` veya
   `Egitim notu`. Sistem notu, fis uzerindeki son degisikliklerle birlikte
   yorumlar ve yapilandirilmis kural adayina cevirir.

Otomatik tekrar sinyalinde onerilen karar secenekleri:

- `Evet`: Bu karari kural adayi olarak ac ve onay formunu goster.
- `Hayir`: Bu belge icin kural olusturma, normal review akisiyle devam et.
- `Tekrar onerme`: Bu benzerlik anahtari icin ayni uyariyi bastir.

Acik musavir notu akisi:

1. Musavir fisi duzeltir veya onaylar.
2. Tek not alanina gerekcesini yazar.
3. `Egitim notunu kaydet` aksiyonu notu ve fis farkini birlikte inceler.
4. Sistem bir modal/form acar ve "bunu boyle anladim" diye yapilandirilmis
   kural adayini gosterir.
5. Musavir form alanlarini gerekirse duzeltir.
6. Musavir sonucu `Kural olarak kaydet` veya `Benzerlerde oner` olarak secer.

Formun temel alanlari:

```text
Kapsam: Bu mukellefe ozel / Musavir ofisi geneli / Firma geneli aday
Tetikleyici: Yurtiçi Kargo / VKN 9860008925 / alis faturasi
Uygulama: Bu caride 320.01.888 kullanilacak; gider hesabi 760.03.010 olacak
Guvenlik: Ilk uygulamalarda musavir kontrolu iste
Durum: Kural adayi
```

Kapsam karari keskin olmalidir:

- Mukellefe ozel: Ayni mukellef icinde uygulanir. Varsayilan guvenli secim budur.
- Musavir/ofis geneli: Ayni musavir ofisinin diger mukelleflerinde once oneri
  olarak cikar; yeterli guven ve celiskisiz tekrar olmadan otomasyon olmaz.
- Firma geneli aday: Urun/hizmet veya kanuni muhasebe mantigi genelse sadece
  merkezi kural kutuphanesine aday olur; tek musavir karariyla aktif olmaz.

`Kural olarak kaydet` ile `Benzerlerde oner` farki:

- `Kural olarak kaydet`: Kapsam, tetikleyici ve uygulama yeterince netse daha
  guclu kural adayi olusur. Pilot boyunca ilk uygulamalarda yine musavir onayi
  istenir; direkt export ready verilmez.
- `Benzerlerde oner`: Sistem sonraki benzer belgelerde fisi bu mantikla hazirlar
  veya one cikarir, ama baska bir guvenli kural ya da yeterli skor yoksa export
  ready yapmaz.

Export guvenlik karari:

- Pilot icinde yeni ogrenilen kural tek basina direkt export ready yapmamalidir.
- Kural aktif olsa bile ilk uygulamalarda musavir kontrolu istenir.
- Pilot cikisinda, tekrarli ve celiskisiz kural icin ayrica onay alinarak
  otomasyon seviyesi artirilabilir.
- Direction conflict, dusuk parse/OCR guveni, eksik VKN/cari kimligi, KDV
  tutarsizligi veya faaliyet-urun catismasi varsa kural otomasyon degil, sadece
  oneri olur.

UI prensibi:

- Yeni buton sayisi artirilmaz; ana ekranda tek not/egitim aksiyonu yeterlidir.
- Ayrintili secimler ana review ekraninda degil, sadece modal/form icinde
  gosterilir.
- Form dili "kural JSON'u" gibi degil, musavirin okuyacagi muhasebe cumleleriyle
  yazilir.
- Sistem sadece "not kaydedildi" dememeli; "bu nottan sunu anladim" diyerek
  tetikleyici, kapsam ve uygulamayi gostermelidir.

## AI kalite farkini nasil anlayacagiz?

Mevcut sistemde bazi sinyaller zaten var: statik siniflandirma guveni, AI kullanildi bilgisi, provider, AI guveni, risk flag'leri, review reason'lari, research confidence, hesap aday uygunlugu, export hazirligi, musavir duzeltmesi ve learning event.

Ama kaliteyi gercekten olcmek icin her belge icin su karsilastirma katmani gerekir:

- Statik motor ne onerdi?
- AI ne onerdi?
- Arastirma sonrasi sonuc degisti mi?
- Musavir finalde neyi onayladi veya degistirdi?
- Hangi alan degisti: cari, ana hesap, KDV, yon, satir aciklamasi?
- AI dogru aday havuzundan mi secti?
- AI gerekcesi NACE/faaliyet ve fatura satiri ile uyumlu muydu?
- Review sebebi gercekten musavir duzeltmesine denk geldi mi?
- Ayni karar kac kez tekrar onaylandi?

Bu metrikler olmadan "AI iyi calisiyor mu" sorusuna sadece tekil orneklerle cevap veririz. Hedef, statik motor, AI, arastirma ve final musavir karari arasindaki farki kaydedip zamanla hangi durumda AI'a, hangi durumda ogrenilmis kurala guvenebilecegimizi olcmektir.

### Karar kalitesi paneli

Belge detayinda teknik JSON gostermek yerine sade bir "Karar kalitesi" paneli olmali. Bu panel pasif kalmali; musavire tekrar AI calistirma butonu gibi davranmamalidir.

Panelde su katmanlar kisa sekilde gorunmelidir:

- Statik motor: urun/hizmet satirini klasik kurallar ne sandi?
- AI: AI hangi kategori, hesap ve cari onerdi?
- Research: arastirma karari guclendirdi mi veya review sebebi mi uretti?
- Sistem final taslagi: musavire gelen hesap/cari/KDV/yon ne?
- Musavir finali: karar aynen onaylandi mi, yoksa hangi alanlar degisti?

Catismalar sade cumleyle yazilmalidir. Ornek: "Faaliyet context'i hizmet agirlikli, urun arastirmasi stok gibi goruyor" veya "Cari unvan benzerligi dusuk; VKN/IBAN eslesmesi yok."

### Musavir final karari ve quality delta

AI'in ilk onerisi sonradan ezilmemelidir. Aksi halde kaliteyi olcemeyiz. Her review/onay sonrasinda belge sonucunda su alanlar kalmalidir:

- `proposal_snapshot`: sistemin review oncesi hesap/cari/yon/KDV taslagi
- `ai_quality_scorecard`: statik, AI, research, context ve sistem final taslagi
- `accountant_final_decision`: musavirin onayladigi nihai karar
- `quality_delta`: musavir neyi degistirdi?

Ornek `quality_delta`:

```json
{
  "changed_fields": ["selected_account_code", "counterparty_account"],
  "account_changed_from": "770.01",
  "account_changed_to": "153.01",
  "counterparty_changed_from": "320.NEW",
  "counterparty_changed_to": "320.01.015",
  "decision": "corrected",
  "learning_candidate": true
}
```

Bu sayede AI'in hesapta mi, caride mi, yonde mi, KDV'de mi yanildigi olculebilir. Research sonrasi karar iyilesiyor mu, statik motor bazi durumlarda AI'dan daha mi iyi, musavir sadece kucuk duzeltme mi yapti yoksa taslagi komple mi degistirdi sorularina veriyle cevap verilir.

### Ogrenilmis kural ne zaman AI'in onune gecer?

Baslangic policy:

- 1 tutarli onay: sadece sinyal. Sonraki belgede "benzer gecmis karar var" diye gosterilir, AI-first devam eder.
- 2 tutarli onay: guclu aday. AI yine calisir ama ogrenilmis karar aday havuzunda one cikar.
- 3 tutarli onay: ayni client + ayni cari + ayni urun/hizmet + ayni yon icin kural AI/research onune gecebilir.
- Acik musavir kurali: kapsam netse direkt one gecer; conflict varsa review gate kalir.

Kuralin AI/research onune gecmesi icin en az su kosullar aranmalidir:

- Ayni mukellef kapsaminda veya acikca ofis politikasi olarak isaretlenmis olmali
- Ayni yon olmali: alis/satis farkliysa uygulanmaz
- Cari guveni yuksek olmali: VKN/IBAN veya ayni counterparty identity key
- Urun/hizmet anahtari benzer olmali: normalize satir, kategori veya research product key
- Hesap/KDV davranisi ayni kalmis olmali
- Sonraki musavir duzeltmeleriyle bozulmamis olmali

Direction conflict, dusuk OCR/parse guveni, eksik VKN/cari kimligi veya faaliyet-urun catismasi varsa kural otomasyon degil, sadece guclu oneri olur.

Kisa karar: AI-first defaulttur. Ogrenilmis kural sadece dar kapsamli, tekrarli ve celiskisizse AI/research maliyetini azaltir. Musavir acik kural yazarsa daha hizli one gecer ama conflict gate kalkmaz.

## Mevcut durum ve eksikler

Su an uygulamada olan ana parcalar:

- Vergi levhasi onboarding attachment olarak saklaniyor.
- Vergi levhasi parse edilip mukellef profiline yazilabiliyor.
- Hesap plani yuklenip parse edilerek hesap adaylari olusuyor.
- NACE arastirmasi cache'li calisacak sekilde tasarlanmis.
- Fatura yuklemesi processing job uretir.
- Onboarding dosyalari processing job uretmez.
- Belge yonu intake ve fatura icerigiyle kontrol edilir.
- AI'a faaliyet/NACE, hesap adaylari ve cari adaylari context olarak verilebilir.
- AI ciktisi aday listeleriyle sinirlanir.
- Marka/urun arastirmasi ihtiyaca gore devreye girebilir ve cache kullanir.
- Musavir onayi/duzeltmesi review ve learning event olarak kaydedilebilir.
- Export/aktarim icin denge ve review gate kontrolleri vardir.

Net eksikler / yapilacaklar:

- Vergi levhasi core alanlari eksikse musavire tamamlatan zorunlu onboarding gate keskinlestirilmeli.
- Vergi levhasi ve hesap plani mukellef ayarlarinda gorulebilir/indirilebilir olmali.
- Delegated upload metadata belge kaydinda acik alanlar olarak saklanmali.
- NACE cache kullanimi UI/operasyon seviyesinde gorulebilir olmali; ayni NACE icin gereksiz internet arastirmasi engellenmeli.
- Urun/marka satiri parse guveni ve karsi firma kimligi guveni ayri ayri gosterilmeli.
- NACE/faaliyet ile urun/marka arastirmasi catismasi UI'da anlasilir review sebebi olarak cikmali.
- AI kalite scorecard'i eklenmeli: statik, AI, research ve final musavir karari karsilastirilmali.
- Yuksek guvenli ogrenme kurallarinin ne zaman AI/research yerine gececegi net esiklerle belirlenmeli.

## Kisa ozet

Senin anlattigin ana akis dogru: vergi levhasi ve hesap plani mukellefin muhasebe contextini kuruyor; fatura parse ediliyor; yon kontrol ediliyor; hesap plani yone gore daraltiliyor; AI satir, faaliyet ve hesap adaylarini birlikte degerlendiriyor; gerekirse urun/marka arastirmasi yapiliyor; cari eslesiyor veya yeni cari oneriliyor; musavir onay/duzeltme ile sistemi ogretiyor.

En kritik farklar sunlar:

- Vergi levhasi parser "kesin okur" diyemeyiz; ama eksik kalmasini kabul etmeyip musavire tamamlatmaliyiz.
- NACE arastirmasi karsi firmanin NACE'i degil, bizim mukellefin faaliyet contextidir.
- Urun/marka arastirmasi karsi firma kimligini kanitlamaz; satirin muhasebe davranisini anlamaya yardim eder.
- NACE ile urun arastirmasi catistiginda sessiz kazanan yoktur; taslak + review reason gerekir.
- AI'a hesap plani yone gore filtrelenmis verilmelidir.
- AI kalitesini anlamak icin statik/AI/research/final musavir karari birlikte kaydedilmelidir.
