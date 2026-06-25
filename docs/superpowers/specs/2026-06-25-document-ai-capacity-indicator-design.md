# Belge İşleme AI Kapasite Göstergesi Tasarımı

## Amaç

Belge işleme sayfasında, iş akışını bölmeden iki AI kapasitesini sürekli görünür kılmak:

- **Belge ajanı:** Güvenli yaklaşık kalan belge işleme kapasitesi.
- **Araştırma ajanı:** Güvenli yaklaşık kalan internet araştırması kapasitesi.

Gösterge yalnızca bilgi verir. Tıklama, araştırma yenileme, belge işleme veya başka bir sağlayıcı çağrısı başlatmaz. Normal belge işleme ve araştırma kararları mevcut akışta kalır.

## Yerleşim ve görünüm

Gösterge belge işleme alanının sağ üst bölümünde, düşük kontrastlı ve tek satırlık bir durum şeridi olarak yer alır:

`AI kapasitesi · Belge ajanı ≈ 120 · Araştırma ajanı ≈ 35`

Masaüstünde tek satır, dar ekranlarda iki kısa satır kullanılır. Büyük kart, uyarı rengi veya dikkat çeken animasyon kullanılmaz.

Her değer yaklaşık olduğunu açıkça belirtir. Veri henüz alınmadıysa ilgili değer yerine `hesaplanıyor`; güncel ve güvenilir bir sayı üretilemiyorsa `ölçülemiyor` gösterilir. Eski fakat kullanılabilir bir snapshot varsa sayı korunur ve `son bilinen` olarak işaretlenir.

## Veri akışı

Mevcut korumalı `GET /phase0/store/ai-capacity` endpoint'i tek kaynak olmaya devam eder. Belge işleme sayfası portal seviyesinde zaten yüklenen kapasite sorgusunu kullanır; aynı render sırasında ikinci bir API isteği oluşturmaz.

Sorgu:

- Sayfa açıldığında çalışır.
- Pencere yeniden odaklandığında yenilenir.
- Sayfa açık kaldığında beş dakikada bir yeniden okunur.
- Hata halinde son başarılı veri ekranda tutulur.

Sağlayıcı kota endpoint'leri daha sık çağrılmaz. Backend, dış kota snapshot'ını en az on dakika önbellekte tutar. Dış kontrol başarısız olursa son başarılı snapshot döndürülür.

## Temkinli kapasite hesabı

Kullanıcıya sağlayıcının teorik üst sınırı değil, tekrar denemeler için rezerv ayrılmış güvenli kapasite gösterilir.

### Belge ajanı

Her sağlayıcı için:

1. Sağlayıcının kalan günlük istek sayısı alınır.
2. Bir belgenin mevcut azami sağlayıcı çağrısı belirlenir.
3. Yeniden deneme setleri için iki tam deneme varsayılır.
4. Kalan kapasitenin yüzde 25'i operasyon rezervi olarak ayrılır.
5. Sonuç aşağı yuvarlanır.

Formül:

`floor(kalan istek × 0,75 / (belge başına azami çağrı × 2))`

Birden fazla belge sağlayıcısı varsa yalnız hazır ve ölçülebilir sağlayıcıların güvenli kapasiteleri toplanır. Snapshot bulunmayan sağlayıcı toplamı yapay biçimde büyütmez.

### Araştırma ajanı

Tavily kullanıldığında backend resmi `/usage` endpoint'inden kalan kredi bilgisini alır ve snapshot olarak saklar. Mevcut `basic` arama bir kredi kullansa da hesap iki kredi/araştırma kabul eder; bu, tekrar deneme ve olası maliyet değişimi için temkinli tabandır. Ayrıca yüzde 25 operasyon rezervi ayrılır.

Formül:

`floor(kalan kredi × 0,75 / 2)`

Başka bir araştırma sağlayıcısı kullanılırsa yalnız doğrulanmış kalan kota/credit verisi mevcutsa sayı hesaplanır. Sadece API anahtarının tanımlı olması kapasite sayısı üretmek için yeterli değildir.

## API sözleşmesi

Mevcut toplam alanları korunur:

- `totals.document_queries`
- `totals.internet_researches`

Bu alanlar bundan sonra temkinli, kullanılabilir yaklaşık kapasiteyi ifade eder. Arayüzün güven durumunu doğru anlatabilmesi için toplam seviyesinde aşağıdaki metadata eklenir:

- `estimate_mode`: `conservative`
- `confidence`: `live`, `cached`, `partial` veya `not_available`
- `last_checked_at`
- `reserve_percent`: `25`
- `retry_multiplier`: `2`

Mevcut operasyon ekranı da aynı düzeltilmiş toplamları gösterir; iki sayfada farklı kapasite hesabı oluşmaz.

## Hata ve güvenlik davranışı

- API anahtarları hiçbir response alanına girmez.
- Kota sağlayıcısı 401/403 döndürürse araştırma ajanı `ölçülemiyor` durumuna geçer; anahtar veya hata gövdesi kullanıcıya gösterilmez.
- 429 veya geçici ağ hatasında son başarılı snapshot korunur.
- Hiç snapshot yoksa sıfır gösterilmez; sıfır gerçek tükenme anlamına ayrılır.
- Gösterge hiçbir POST isteği yapmaz ve kullanıcı tıklamasıyla token/kredi tüketmez.

## Test kapsamı

- Belge kapasitesi iki deneme ve yüzde 25 rezervle aşağı yuvarlanır.
- Ölçülemeyen sağlayıcı toplamı büyütmez.
- Tavily usage payload'ı normalize edilir ve güvenli araştırma kapasitesine çevrilir.
- Eski snapshot dış kota kontrolü başarısız olduğunda kullanılmaya devam eder.
- Belge işleme sayfası iki ajan başlığını ve yaklaşık değerleri render eder.
- Yükleniyor, son bilinen ve ölçülemiyor durumları ayrı test edilir.
- Gösterge etkileşimsizdir; araştırma refresh veya belge işleme çağrısı üretmez.
- Operasyon ekranı ve belge işleme ekranı aynı backend toplamlarını kullanır.
