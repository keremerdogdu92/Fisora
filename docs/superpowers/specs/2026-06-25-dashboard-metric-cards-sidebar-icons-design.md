# Dashboard Metrik Kartları ve Sidebar İkonları Tasarımı

## Amaç

Müşavir anasayfasındaki altı ofis metriğini dikey, tam genişlikli satırlar yerine hızlı taranabilen kompakt kartlar halinde göstermek ve sidebar navigasyonundaki iki harfli rozetleri anlamlı ikonlarla değiştirmek.

Mevcut portal kabuğu, renk sistemi, sayfa rotaları ve navigasyon davranışları korunur. Değişiklik yalnızca görsel hiyerarşi, responsive yerleşim ve ikon sunumunu kapsar.

## Onaylanan görsel yön

Onaylanan seçenek masaüstünde altı kartın tek satırda yer aldığı düzendir.

- Geniş masaüstü içerik alanında altı eşit kolon kullanılır.
- Orta genişlikte üç kolon ve iki satıra geçilir.
- Mobilde iki kolon ve üç satır kullanılır.
- Kartlar yaklaşık 78-84 piksel yüksekliğinde kalır.
- Grafikler kartların hemen altında mevcut üç kolonlu yapısını korur.

Bu düzen, mevcut ekrandaki kullanılmayan yatay alanı değerlendirir ve grafiklerin ilk görünümde aşağı itilmesini sınırlar.

## Metrik kart anatomisi

Her kart üç parçadan oluşur:

1. Sol tarafta düşük kontrastlı, vurgulu zemin içinde anlamlı ikon.
2. Sağ tarafta kısa metrik etiketi.
3. Etiketin altında büyük ve güçlü metrik değeri.

Kart sırası ve ikon eşlemesi:

| Metrik | İkon anlamı |
| --- | --- |
| Mükellef | Kullanıcılar |
| Yükleyen | Yükleme |
| Yüklemeyen | Eksik kullanıcı |
| Kontrol | Kontrol listesi |
| Çıktı hazır | Hazır paket |
| Talep | Uyarılı mesaj |

Kartlar mevcut `Metric` bileşeninin ikon destekleyen, geriye uyumlu bir varyantını kullanır. Dashboard dışındaki `Metric` kullanımları ikon verilmediğinde mevcut görünüm ve davranışı korur.

## Sidebar ikonları

Sidebar içindeki `CA`, `MK`, `BL`, `BK`, `DB`, `CK`, `BH`, `OP` ve `AY` metin rozetleri kaldırılır. Yerlerine aynı çizgi kalınlığına ve optik boyuta sahip tek bir ikon ailesi kullanılır.

| Navigasyon | İkon anlamı |
| --- | --- |
| Çalışma Alanı | Dashboard |
| Mükellefler | Kullanıcılar |
| Belgeler | Belge |
| Banka Ekstreleri | Banka |
| Diğer Belgeler | Çoklu belgeler |
| Çıktı / Kontroller | Tamamlanmış kontrol |
| Bilgi Havuzu | Açık kitap |
| Operasyon | Aktivite |
| Ayarlar | Dişli |

İkon kaynağı olarak `lucide-react` kullanılacaktır. Yeni ikonlar `currentColor` ile sidebar satırının normal, hover ve aktif renklerini otomatik izler. Harf rozeti için kullanılan çevreleyen sınır kaldırılır; ikonlar 18-20 piksel optik boyutta doğrudan hizalanır.

## Responsive kurallar

- `min-width: 1280px`: metrikler `repeat(6, minmax(0, 1fr))`.
- `760px - 1279px`: metrikler `repeat(3, minmax(0, 1fr))`.
- `max-width: 759px`: metrikler `repeat(2, minmax(0, 1fr))`.
- Çok dar ekranlarda etiket metni taşmaz; kart içeriği küçülmeden iki satıra kırılabilir.
- Sidebar'ın mevcut 1020 ve 720 piksel kırılımları korunur. Navigasyon grid olduğunda ikon ve etiket aynı satırda kalır.

## Erişilebilirlik

- İkonlar dekoratiftir ve `aria-hidden="true"` kullanır; erişilebilir isim mevcut görünür etiketten gelir.
- Kart grubu mevcut `aria-label="Ofis durumu"` sözleşmesini korur.
- Renk tek başına anlam taşımaz; her ikonun yanında metin etiketi bulunur.
- Aktif sidebar öğesi mevcut `aria-current="page"` davranışını korur.

## Kod sınırları

Değişiklikler aşağıdaki alanlarla sınırlıdır:

- `frontend/app/portal-dashboard-view.tsx`: dashboard metriklerine ikon eşlemesi.
- `frontend/app/portal-shared.tsx`: opsiyonel ikon destekli `Metric` bileşeni.
- `frontend/app/portal-shell-components.tsx`: sidebar sembollerinin ikon bileşenlerine dönüşümü.
- `frontend/app/styles.css`: kart grid'i, kart iç düzeni ve sidebar ikon ölçüleri.
- `frontend/package.json` ve lockfile: `lucide-react` bağımlılığı.
- İlgili CJS kaynak testleri: ikon eşlemeleri, erişilebilirlik ve responsive CSS sözleşmesi.

Route, API, veri modeli, dashboard hesapları veya navigasyon mantığı değişmez.

## Test ve doğrulama

- Kaynak testi altı dashboard metriğinin doğru ikonlarla render edildiğini doğrular.
- Kaynak testi sidebar öğelerinin iki harfli `symbol` alanı yerine ikon bileşeni kullandığını doğrular.
- Test ikonların dekoratif erişilebilirlik niteliğini ve görünür etiketlerin korunmasını doğrular.
- Stil testi 6 kolon, 3 kolon ve 2 kolon responsive sözleşmelerini doğrular.
- Mevcut frontend CJS testleri çalıştırılır.
- Next.js production build çalıştırılır.
- Tarayıcıda geniş masaüstü, orta ekran ve mobil viewport kontrol edilir.
- Son render, onaylanan A seçeneğiyle kart sırası, tek satır masaüstü düzeni, ikon stili, boşluk ve kart yüksekliği açısından karşılaştırılır.
