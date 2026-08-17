# Gemini Direct-PDF Two-Stage V1 Design

Status: Review-ready

## Amaç

Fisero'nun ilk çalışan sürümünde PDF faturayı doğrudan Gemini native-PDF
çağrısıyla okumak, çıkan belge olgularını muhasebeden ayrı tutmak ve gerçek
tenant hesap adaylarıyla ikinci bir muhasebe AI aşamasında kullanılabilir fiş
taslağı üretmek.

Bu V1'in amacı uzun vadeli politika, otomatik export veya otomatik onay kararı
vermek değildir. Önce gerçek belgelerde oluşan ürün kalitesini görmek ve ölçmek
amaçlanır.

## V1 kapsamı

1. PDF extraction için Gemini native-PDF birincil ve tek provider yoludur.
2. Textract veya başka bir extraction fallback'i eklenmez.
3. Extraction aşaması hesap, cari veya muhasebe hesabı seçmez.
4. Gemini'nin exact request ve response body'leri yeniden incelenebilir raw
   receipt olarak saklanır.
5. Raw response'tan muhasebecinin okuyabileceği canonical invoice form üretilir.
6. İkinci AI'a yalnız muhasebe için gereken kompakt projection ve tenant'ın
   gerçek hesap adayları gönderilir.
7. Muhasebe AI ilk listeden seçim yapabilir veya en fazla iki kez ek aday
   isteyebilir.
8. Mevcut aktif belge işleme ekranına yeni panel, sekme veya teknik yüzey
   eklenmez.

## Kapsam dışı

- Otomatik onay politikası.
- Otomatik export politikası.
- Uzun vadeli provider receipt saklama politikası.
- Yeni provider veya extraction fallback zinciri.
- Textract entegrasyonu.
- Mevcut aktif belge işleme ekranının yeniden tasarlanması.
- Model kalitesi görülmeden geniş ürün-politika dokümantasyonu.

## Çalışma akışı

```text
Immutable source PDF
-> Gemini native-PDF extraction attempt
-> immutable raw provider receipt
-> canonical invoice form revision
-> accounting input projection
-> initial real tenant candidate pool
-> accounting AI attempt
   -> seçim
   veya
   -> en fazla iki candidate-expansion attempt
-> best available accounting proposal
-> mevcut belge işleme ekranındaki fiş taslağı
```

## Artifact sözleşmesi

### 1. Raw provider receipt

Her gerçek HTTP çağrısı ayrı receipt üretir. Receipt en az şunları taşır:

- `receipt_id`
- `document_ref` ve source PDF hash'i
- stage: `document_extraction` veya `accounting_selection`
- provider, model alias ve dönen gerçek model version
- prompt, schema ve pipeline version
- exact request body
- exact response body veya exact error body
- HTTP status
- başlangıç/bitiş ve `elapsed_ms`
- token/usage metadata
- `retry_of_receipt_id` veya `expanded_from_receipt_id`
- request ve response hash'leri

API anahtarı ve authentication header'ları hiçbir zaman receipt'e girmez.
Body'ler mevcut document storage yaşam döngüsünü izler ve kaynak PDF silindiğinde
onunla birlikte silinir. V1 uzun dönem saklama taahhüdü vermez.

### 2. Canonical invoice form revision

Raw response değiştirilmez. Version'ı kayıtlı bir mapper, raw response'tan ayrı
bir canonical revision üretir.

Canonical form en az şunları korur:

- fatura numarası, ETTN, tarih, tür, senaryo ve para birimi
- satıcı ve alıcı unvanı, VKN/TCKN, vergi dairesi ve adres
- bütün fatura satırları
- miktar, birim, birim fiyat, net/gross anlamı, KDV oranı ve KDV tutarı
- KDV özeti
- özel vergi ve diğer parasal bileşenler
- net, vergi, brüt ve ödenecek toplamlar
- alan ve satırların raw-response path/evidence bağlantıları
- extraction warning'leri

Bir warning canonical formu silmez, boşaltmaz veya yararlı alanların kaydını
engellemez.

### 3. Accounting input projection

Projection canonical revision'dan deterministik olarak üretilir ve ikinci AI'a
şunları taşır:

- belge yönü
- taraflar ve vergi kimlikleri
- bütün `canonical_line_id` değerleri ve satır muhasebe olguları
- KDV grupları
- özel vergi/parasal bileşenler
- belge toplamları
- muhasebe kararını etkileyebilecek kısa warning'ler
- tenant/client faaliyet bağlamı

Tekrarlanan evidence metinleri, raw provider envelope'u ve muhasebe kararını
etkilemeyen ayrıntılar projection'a alınmaz. Projection hiçbir canonical satırı,
taraf VKN'sini, vergi bileşenini veya toplamı kaybedemez.

### 4. Accounting proposal

Muhasebe AI yalnız tenant'ın gerçek hesap adaylarını `candidate_id` ile seçer.
Seçim semantiği deterministik kod tarafından yeniden yorumlanmaz veya relevance
puanıyla reddedilmez.

Proposal düşük güvenli, eksik veya yeni cari önerili olabilir; yine de saklanır
ve mümkün olan en iyi taslak akışına girer.

## Candidate expansion protokolü

İlk accounting attempt başlangıç candidate pool'unu görür. Her karar noktası
bağımsız olarak aday yeterliliğini bildirebilir:

- canonical line
- VAT group
- tax component
- counterparty

AI aynı cevapta hem geçici en iyi adayını seçebilir hem de daha fazla aday
isteyebilir. Ek tur geldiğinde önceki adaylar kaybolmaz; yeni adaylar biriken
pool'a eklenir.

```json
{
  "decision_ref": "tax_component:T-1",
  "selected_candidate_id": "candidate-C",
  "selection_status": "provisional",
  "candidate_set_sufficient": false,
  "request_more_candidates": {
    "search_terms": ["özel iletişim vergisi", "ÖİV"],
    "requested_scope": "broader_chart_slice",
    "reason": "Mevcut adaylar içinde C en iyi; ilgili diğer vergi hesaplarını görmek istiyorum."
  }
}
```

En fazla iki expansion attempt yapılır. Son attempt:

- ilk turdaki adayı seçebilir,
- sonraki turdaki adayı seçebilir,
- düşük güvenli best-effort seçim bırakabilir,
- hiçbirini seçmeyip unresolved veya yeni cari önerisi döndürebilir.

Tur sınırına ulaşılması belgeyi processing failure yapmaz.

## Yeni cari kararı

Existing seçim ve yeni cari önerisi ayrı karar türleridir:

```json
{
  "action": "select_existing",
  "selected_candidate_id": "counterparty-17"
}
```

```json
{
  "action": "propose_new",
  "selected_candidate_id": null,
  "new_counterparty_proposal": {
    "party_title": "Örnek Tedarikçi A.Ş.",
    "tax_id": "1234567890",
    "direction": "supplier",
    "suggested_parent_family": "320"
  }
}
```

`select_existing` yalnız candidate'ın aynı tenant'ın gerçek planında bulunduğunu
ve çağrıda gönderildiğini doğrular. Bu kontrol semantik alaka değerlendirmesi
yapmaz.

`propose_new` mevcut hesap seçimi değildir. V1'de yeni cari otomatik oluşturulmaz;
öneri mevcut draft-first sonuçta korunur ve gerçek oluşturma müşavir onayına
bırakılır.

## Soft-gate ilkesi

Dört artifact katmanı engel zinciri değildir:

- Raw receipt başarılı veya başarısız her çağrıyı korur.
- Parse edilebilen canonical form warning'lerle birlikte kaydedilir.
- Accounting projection mevcut bütün kullanılabilir olgularla üretilir.
- Accounting proposal düşük güvenli olsa da kaydedilir ve taslakta kullanılır.

Herhangi bir aşamada oluşan warning kanıt olarak sonuca eklenir; warning'in
varlığı boru hattını kısa devre etmez. Eldeki veriyle çalışabilen bütün sonraki
aşamalar devam eder ve mümkün olan en iyi taslak hazırlanır. Warning nedeniyle
geride kalan çalışabilir aşamalardan veya taslak üretiminden vazgeçilmez.

Deterministik kontrol yalnız veri bütünlüğü ve matematik gibi objektif alanlarda
uygulanır. Semantik hesap/cari uygunluğunu yeniden seçmez ve AI kararını başka
bir hesaba dönüştürmez.

Gerçek teknik imkânsızlıklar sonraki aşamayı çalıştırmayabilir; örneğin provider
hiç cevap vermemişse veya response JSON olarak açılamıyorsa uydurma canonical
veri üretilmez. Buna rağmen source PDF ve hata receipt'i korunur, belge tekrar
denenebilir durumda kalır ve önceki geçerli revision varsa bozulmaz.

Processing/draft üretimi ile ileride tanımlanacak approval/export authority
birbirine bağlanmaz.

## UI sınırı

- Mevcut aktif belge işleme ekranı korunur.
- V1 için raw receipt paneli, yeni tab veya yeni teknik kart eklenmez.
- Canonical form ve accounting proposal mevcut ekran payload'ını besler.
- Debug/benchmark incelemesi backend artifact'ları üzerinden yapılır.
- Sahadaki kalite görüldükten sonra kullanıcıyla birlikte UI ihtiyacı yeniden
  değerlendirilir.

## Idempotency ve yeniden çalışma

Extraction reuse fingerprint'i source hash, provider, resolved model, prompt,
schema ve pipeline version'dan oluşur. Aynı effective input için mevcut başarılı
artifact yeniden kullanılabilir.

Accounting fingerprint ayrıca canonical revision, tenant chart revision,
candidate-builder version ve client-context revision taşır.

Yeni model, prompt, schema, mapper veya chart revision yeni artifact üretir;
eskisini değiştirmez. Başarısız yeniden çalışma önceki geçerli canonical formu
veya taslağı silmez.

## İlk çalışma sırası

1. Mevcut beş belgeli one-vs-two deney setinde uçtan uca çalışan V1 kurulur.
2. Exact raw receipt ve lineage doğrulanır.
3. Canonical header/line/tax/total kapsamı doğrulanır.
4. Accounting projection'ın hiçbir gerekli muhasebe olgusunu kaybetmediği
   doğrulanır.
5. Initial candidate selection ve iki expansion turu kontrollü örneklerle
   çalıştırılır.
6. Sonuçlar mevcut aktif belge işleme ekranında taslak olarak açılır.
7. Müşavirle çıktı kalitesi incelenir.
8. Ancak gözlenen saha sonucuna göre candidate limitleri, tur sayısı, UI,
   retention, approval ve export politikaları yeniden ele alınır.

## V1 başarı kanıtı

- PDF doğrudan Gemini'ye gider; parser-first veya Textract primary yol çalışmaz.
- Extraction ve accounting ayrı provider attempt'leri olarak izlenebilir.
- Exact raw request/response body'leri secret içermeden yeniden okunabilir.
- Canonical form bütün görülen satırları, tarafları, vergi bileşenlerini ve
  toplamları korur.
- Accounting projection canonical satır/VKN/vergi/toplam kaybetmez.
- AI initial pool'dan doğrudan seçim yapabilir.
- AI gerektiğinde iki expansion turu isteyebilir ve sonradan ilk adayına
  dönebilir.
- Yeni cari önerisi taslağı durdurmaz ve otomatik cari oluşturmaz.
- Düşük güven veya warning yararlı taslağı silmez, boru hattını durdurmaz ve
  sonraki çalışabilir aşamaların yürütülmesini engellemez.
- Mevcut belge işleme ekranına yeni UI yüzeyi eklenmez.
- Sonuçlar kalite, süre, token/maliyet, expansion kullanım oranı ve müşavir
  düzeltme ihtiyacıyla raporlanır; production/export readiness iddiası yapılmaz.
