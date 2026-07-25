# QNB Giden Fatura Sandbox Hazırlık Tasarımı

## Kabul edilen kapsam

Fisero bu dilimde müşavirlere veya mükelleflere production ortamında fatura
kesme yetkisi açmayacaktır. Hedef daha dardır: mevcut giden fatura taslak, onay,
değişmez UBL, provider gönderimi, receipt/durum kanıtı ve muhasebe bağlantısının
gerçek QNB sandbox ortamında uçtan uca çalıştığını kanıtlamak.

Bu tasarım uygulanıp kabul edildiğinde kullanılabilecek doğru ürün ifadesi:

> QNB e-Fatura ve e-Arşiv giden belge entegrasyonu gerçek QNB test ortamında
> uçtan uca doğrulandı. Production gönderimi bilinçli olarak kapalıdır.

Bu belge,
`docs/superpowers/plans/2026-07-10-qnb-end-to-end-integration.md` içindeki Faz 8
ve Faz 9'u ayrıntılandırır. Gelen belge planının veya ilerideki production kabul
kapısının yerine geçmez.

## Mevcut sistem gerçeği

- `OutgoingInvoiceService`, `draft -> approved -> sending -> sent/failed`
  akışını, onay anında UBL 2.1 dondurmayı, SHA-256 kanıtını ve
  tenant/client-kapsamlı idempotency claim'i destekliyor.
- API yalnızca `accountant/admin` rollerine açık; `client_user` reddediliyor.
- `get_outgoing_invoice_service()` gerçek provider enjekte etmiyor. Ortak API
  bu nedenle yerel fake provider kullanıyor.
- `QnbSoapEfaturaAdapter.send_outgoing_invoice_ubl()` ve
  `QnbSoapEarsivAdapter.create_invoice_ubl()` mevcut ve adapter seviyesinde
  testli. Gerçek e-Fatura sandbox gönderimi özel script ile daha önce başarılı
  oldu. e-Arşiv WS bağlantısı aktif; ancak ortak outgoing service üzerinden
  gerçek e-Arşiv sandbox faturası henüz oluşturulmadı.
- Ortak servis bütün provider hatalarını `failed` yapıyor. Bu davranış güvenli
  bir gönderim-öncesi ret ile QNB'nin kabul ettiği fakat cevabı kaybolan isteği
  birbirinden ayıramıyor.
- Mutating SOAP operasyonları için retry yapmayan ayrı bir transport yolu yok.
- e-Arşiv env credential'ları global; güncel `client_id` connection kaydından
  çözülmüyor.
- Invoice içindeki `history` mutable projection verisi; geri döndürülemez
  provider denemeleri için tek audit kaynağı olmaya yeterli değil.

## Engineering reviewer sonucu

Sınırlandırılmış engineering review, `93/100` güvenle doğrudan sandbox gönderimi
için **NO-GO** sonucu verdi. Ortak servisle ilk gerçek sandbox gönderiminden önce
aşağıdakiler zorunludur.

### P0 — Gönderimden önce zorunlu

1. Mutating QNB çağrıları timeout, transport hatası, HTTP 429 veya HTTP 5xx
   sonrasında otomatik tekrar edilmemeli.
2. Belirsiz provider sonucu `failed` değil `reconciliation_required` olmalı.
   Read-only mutabakat sonuçlanmadan aynı veya yeni idempotency key başka bir
   gönderim başlatamamalı.
3. Gerçek provider routing fail-closed olmalı. Yalnız server tarafında açıkça
   seçilen `qnb_sandbox` modu QNB outgoing provider kurabilmeli; her mutating
   adapter çağrısı test endpointini ayrıca doğrulamalı.
4. Credential, şifreli QNB connection kaydından `client_id` kapsamında
   çözülmeli. Dondurulmuş UBL içindeki satıcı VKN/TCKN ile connection kimliği
   eşleşmezse gönderim reddedilmeli.

### P1 — Sandbox kabulünden önce zorunlu

1. Dondurulmuş UBL'nin SHA-256 değeri gönderimden hemen önce yeniden
   hesaplanıp saklanan değerle karşılaştırılmalı.
2. Mutable invoice projection'dan bağımsız append-only gönderim denemeleri ve
   olayları saklanmalı.
3. Aynı key ile eşzamanlı çağrılar tek bir deneme/sonucu paylaşmalı ve QNB'ye
   yalnız bir istek çıkarmalı.
4. Provider başarısı normalize edilmeli. Belge türüne özgü açık başarı ve
   zorunlu QNB receipt kimliği olmadan ortak servis `sent` yazmamalı.

## Ürün ve güvenlik sınırı

Bu dilimde production gönderim modu ve kullanıcıya açık "Fatura kes" özelliği
yoktur. Production gönderimi kapalıdır.

Server tarafındaki provider modları:

```text
disabled      varsayılan API runtime; gönderim yok
fake          açıkça seçilen deterministic test/runtime modu
qnb_sandbox   yalnız QNB test endpointleri
```

`qnb_production` uygulanmayacaktır. Provider modu API payload, URL parametresi,
client metadata veya frontend state üzerinden seçilemez. `qnb_sandbox` modunda
production QNB hostname görülmesi, network isteğinden önce kesin hata üretir.

Unit testler fake provider'ı açıkça kurar. Normal uygulama başlangıcı
`disabled` olur; eksik environment ayarı harici gönderime dönüşemez.

## Mimari

### Provider sınırı

Ortak domain, gevşek SOAP response sözlükleri yerine normalize edilmiş kontrata
bağlanır:

```python
@dataclass(frozen=True)
class OutgoingProviderReceipt:
    provider: str
    provider_operation: str
    provider_document_id: str
    provider_transaction_id: str
    provider_invoice_no: str
    provider_status: str
    response_received: bool
    evidence: dict[str, object]

class OutgoingProviderOutcomeUnknown(RuntimeError):
    pass

class OutgoingInvoiceProvider(Protocol):
    def send(self, *, invoice: dict[str, Any], ubl_content: bytes) -> OutgoingProviderReceipt: ...
    def reconcile(self, *, invoice: dict[str, Any], attempt: dict[str, Any]) -> dict[str, Any]: ...
```

`QnbSandboxOutgoingInvoiceProvider`, dondurulmuş `document_type` değerine göre
routing yapar:

- `efatura` -> `QnbSoapEfaturaAdapter.send_outgoing_invoice_ubl()`;
- `earsiv` -> `QnbSoapEarsivAdapter.create_invoice_ubl()`.

Wrapper client connection'ını çözer, environment ve kaynak kimliğini doğrular,
adapter'ı bir kez çağırır ve provider alanlarını `OutgoingProviderReceipt`
kontratına çevirir. HTTP 200 tek başına başarı değildir; belge türüne özgü QNB
sonuç kodu ve zorunlu receipt kimliği doğrulanmalıdır.

### Credential kapsamı

Her gönderim, credential'ı `invoice.client_id` sahibi olan şifreli QNB
connection kaydından çözer. Global `.env.qnb.local` değerleri yalnız secret-safe
sandbox araçlarında kalır; multi-tenant API credential kaynağı olmaz.

Gönderimden önce:

1. connection aynı client'a ait, mevcut ve `active` olmalı;
2. connection environment test/sandbox olmalı;
3. bütün user/service endpointleri QNB test-host allowlist'inden geçmeli;
4. UBL satıcı VKN/TCKN değeri connection kimliğiyle eşleşmeli;
5. UBL byte'ları saklanan approval SHA-256 değerini yeniden üretmeli.

Bu kontrollerdeki hata mutating request başlamadan oluşur.

### Durum modeli

```text
draft
  -> approved
  -> sending
      -> sent
      -> failed
      -> reconciliation_required

reconciliation_required
  -> sent
  -> failed
```

- `failed` yalnız QNB operasyonu açıkça reddettiğinde veya read-only mutabakat
  kabul edilmiş belge olmadığını kanıtladığında kullanılabilir.
- Request başladıktan sonra timeout, connection reset, response parse hatası,
  HTTP 429 ve HTTP 5xx belirsizdir; `reconciliation_required` oluşturur.
- `reconciliation_required`, yeni key dahil bütün mutating retry'ları engeller.
- Mutabakat read-only çalışır; e-Fatura için OID/fatura numarası, e-Arşiv için
  canlı QNB kontratının istediği provider fatura UUID'si veya fatura numarası
  kullanılır. `islemId`, `faturaSorgulaExt` sorgu kimliği değildir.
- QNB kontratı yokluğu kanıtlayamıyorsa deneme belirsiz kalır ve sandbox
  operatörü/portal kontrolü ister; iyimser retry yapılmaz.

### Idempotency ve eşzamanlılık

Claim, attempt oluşturma ve `approved -> sending` geçişi tek atomik store
operasyonudur. Kalıcı unique sınırı:

```text
tenant_id + client_id + idempotency_key
```

Claim ayrıca `invoice_id` ve `ubl_sha256` saklar. Aynı key'in farklı invoice veya
hash için kullanımı reddedilir. Aynı key ile eşzamanlı çağrılar aynı attempt
projection'ını döndürür ve QNB'yi iki kez çağırmaz. Farklı key, `sending`, `sent`
veya `reconciliation_required` durumlarını aşamaz.

JSON storage aynı semantiği mevcut process lock altında sağlar. PostgreSQL,
mevcut transaction ile row lock/unique record kullanır; uniqueness yarışı
kazanan attempt yeniden okunarak döndürülür.

### Append-only kanıt

Her gönderim immutable bir `outgoing_invoice_send_attempt` oluşturur ve şu
olayları append eder:

```text
claimed
preflight_passed
request_started
response_received
provider_confirmed
provider_rejected
outcome_unknown
reconciliation_started
reconciliation_confirmed_sent
reconciliation_confirmed_failed
```

Asgari attempt kanıtı:

- tenant/client/invoice ve attempt ID;
- idempotency key'in güvenli değeri veya hash'i;
- belge türü ve provider operasyonu;
- dondurulmuş UBL SHA-256;
- credential/token içermeyen sandbox endpoint sınıfı;
- request-started ve response-received zamanları;
- sanitize edilmiş QNB sonuç/hata kodu;
- döndüyse OID, transaction ID, provider UUID ve fatura numarası;
- reconciliation kaynağı ve terminal sonuç.

Invoice payload son projection olarak kalır. Attempt/event kayıtları audit
gerçeğidir ve overwrite edilmez.

### Mutating transport politikası

Read-only liste, download, connection test ve status çağrıları sınırlı
retry/backoff kullanabilir. Mutating metotlar tek-denemeli transport kullanır:

```text
belgeGonderExt       otomatik transport retry yok
faturaOlusturExt     otomatik transport retry yok
gelecekteki iptal    ayrıca tasarlanmadan otomatik retry yok
```

Retry kararı genel HTTP/SOAP client'a değil domain reconciliation state
machine'e aittir.

### Canonical ve muhasebe bağlantısı

QNB kanıt ve transport katmanıdır; muhasebe karar motoru değildir.

Sandbox başarısı doğrulandıktan sonra:

1. gönderilen UBL/hash ile QNB receipt aynen korunur;
2. dönen UBL/PDF, outgoing invoice ve provider kimliğiyle ilişkilendirilir;
3. özgün satır/KDV/toplam kanıtıyla canonical satış faturası oluşturulur;
4. yalnız gerçek client hesap planı ve doğrulanmış satırlardan açıklanabilir,
   dengeli satış fişi taslağı hazırlanır;
5. provider delivery, müşavir review ve export readiness ayrı durumlar kalır;
6. iptal/status kanıtı, onaylı muhasebe işini sessizce silmez veya ters çevirmez.

Hesap planı ya da satır kanıtı eksikse `insufficient-evidence` ve uygulanabilir
review nedeni üretilir; taraf adından hesap anlamı uydurulmaz.

## Sandbox kabul sırası

1. Fake/disabled provider ile deterministic ve persistence testlerini çalıştır.
2. Network çağrısı olmadan production-host ve supplier-identity guard'larını
   kanıtla.
3. Ortak API/service üzerinden QNB TEST2'ye kontrollü tek e-Fatura gönder; OID
   ve durumu doğrula, TEST1'den geri çek ve duplicate korumasını kanıtla.
4. Ortak API/service üzerinden kontrollü tek e-Arşiv sandbox faturası oluştur;
   QNB UUID/no/receipt ve UBL/PDF çıktısını saklayıp durumunu sorgula.
5. Doğrulanmış QNB sandbox kontratı izin veriyorsa yalnız bu kontrollü e-Arşiv
   belgesini iptal et ve iptal kanıtını sakla. Production iptal/itiraz kapsam
   dışıdır.
6. Request başladıktan sonra zorlanmış timeout testi çalıştır; ikinci mutating
   çağrı olmadığını, `reconciliation_required` ve güvenli mutabakatı kanıtla.
7. Secret-safe kabul özeti üret. Gerçek belge kanıtları ignored/private kalır.

## Kabul kriterleri

- Varsayılan runtime outgoing dispatch yapamaz.
- API payload provider veya endpoint seçemez.
- `qnb_sandbox`, bütün production endpointlerini network öncesi reddeder.
- Yanlış tenant credential ve supplier identity mismatch fail-closed olur.
- Dondurulmuş UBL hash mismatch gönderimi engeller.
- e-Fatura ve e-Arşiv, standalone script dışında ortak
  `OutgoingInvoiceService` üzerinden birer gerçek sandbox gönderimi tamamlar.
- Provider başarısı belge türüne özgü QNB başarı kodu ve receipt kimliği ister.
- Post-submit timeout `reconciliation_required` üretir; aynı ve yeni key ikinci
  provider isteği çıkarmaz.
- PostgreSQL aynı-key eşzamanlı çağrıları tek attempt/istek üretir ve aynı
  sonucu döndürür.
- Append-only attempt zinciri secret içermeden request, response, receipt,
  status ve mutabakat kanıtını gösterir.
- Saklanan UBL SHA-256, provider attempt ve dönen kanıtla birebir eşleşir.
- Doğrulanmış sandbox belgesi canonical satış akışına girer; fiş taslağı
  dengeli, kaynağa bağlı ve review/export gate'li olur.
- Secret-safe kanıt, sandbox'ın doğrulandığını ve production gönderiminin kapalı
  olduğunu açıkça söyler.

## Kapsam dışı

- Production QNB endpoint, credential, onboarding veya dispatch.
- Müşteri ya da müşavire açık fatura kesme arayüzü.
- Production seri/numara politikası ve hukuki kabul.
- Production iptal, itiraz, ticari kabul/red, toplu kesim, rate-limit kapasitesi
  veya unattended gönderim.
- Provider tesliminden sonra otomatik muhasebe onayı/export.
- Ayrı release onayı olmadan commit, push, deploy veya production mutation.
