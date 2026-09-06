# Fisora UX / QA Audit — 2026-09-05

## Executive verdict

Fisora’nın `/portal-next` akışı, müşavir çalışma masası fikrini ve kaynaklı mahsup fişi taslağını görünür biçimde taşıyor; ancak mevcut durumda muhasebe ofisi pilotuna güvenli şekilde alınmamalı. En kritik neden, filtre sonucu boşaldığında önceki belgenin ve karar butonlarının ekranda kalmasıdır. Bu, yanlış kayıt üzerinde karar verme riskidir.

Denetim UI üzerinden, kimlik doğrulanmış mevcut Chrome oturumunda yapıldı. Kod değişikliği yapılmadı. Demo veri yetkisiyle karar ve çıktı aksiyonları çalıştırıldı. Dosya yükleme iki farklı yerel dosya yolu ile denendi ancak Chrome/CUA `fileChooser.setFiles` çağrısı `Not allowed` döndürdü; bu nedenle yeni belge sisteme alınamadı.

## Post-authorization demo-state validation

Kullanıcının demo verilerinde karar ve veri değişikliğine açık yetkisi sonrasında aşağıdaki UI işlemleri gerçek demo kayıtları üzerinde çalıştırıldı:

- `ARİF ŞAN / Haziran 2026 / 1790617537_BEF2026002324731.html / 754.65`: `Onayla ve sonraki →` sonrası `Kontrol 3 → 2`, `Onaya hazır 0 → 1`; liste kaydı `Onaya hazır` etiketi aldı. Sağdaki fiş durumu yine `Müşavir onayı bekliyor` kaldı; buton adı ile sonuç durumunun dili aynı şeyi anlatmıyor.
- Aynı kayıt üzerinde `Kontrolde tut`: `Kontrol 2 → 3`, `Onaya hazır 1 → 0`; önceki etiket kaldırıldı. Bu aksiyon görünür olarak çalışıyor.
- `ARİF ŞAN / Haziran 2026 / 1790617537_BEF2026002228563.html / 17.61`: `Hariç tut` tıklanmasına rağmen kayıt kuyrukta kaldı; `Kontrol 3`, `Onaya hazır 0`, fiş durumu `Müşavir onayı bekliyor` olarak değişmeden kaldı ve kullanıcıya hata/sonuç mesajı çıkmadı.
- `Ctrl+Z`: seçili kontrol kaydında görünür bir geri alma sonucu oluşmadı; kısayolun uygulanıp uygulanmadığı kullanıcıya açıklanmadı.
- `Onay & Çıktılar`: `CSV oluştur` ve `Paketi hazırla` butonları aktifken tıklanınca `Cikti paketi icin once mukellef ekleyin.` mesajı görüldü. `XLSX oluştur` erişilebilirlik ağacında disabled kaldı. `İşlem Durumu` sonrasında `Kontrol 75`, `Hazır 0`, `Belge 75` gösterdi.

Bu işlemler sırasında kod değiştirilmedi; sonuçlar demo ortamının mevcut kalıcı durumudur.

## Top 10 issues

### UXR-001 — P0 — Boş filtrede eski belge ve karar eylemleri kalıyor

- **Screen:** Çalışma Masası
- **Action:** Seçili fatura varken `Onaya hazır 0` filtresine geçildi.
- **Expected:** `Evrak 0 / 0`, boş kaynak/fiş alanı ve devre dışı karar eylemleri.
- **Observed:** Liste boş ve `Evrak 0 / 0`; buna rağmen önceki belgenin kaynağı, mahsup fişi ve `Onayla ve sonraki`, `Kontrolde tut`, `Hariç tut` butonları kaldı.
- **Impact:** Müşavir yanlış belgeyi onaylama/dışlama riskiyle karşılaşabilir.
- **Recommendation:** Görünür liste boşsa seçimi atomik olarak temizle; belge kimliği ile taslak kimliğini her render ve eylem öncesi eşleştir; seçim yokken karar butonlarını disable et.
- **Reproducible:** Evet.
- **Evidence:** Inline boş `Onaya hazır 0` ekran görüntüsü; exact labels `Evrak 0 / 0`, `Onayla ve sonraki →`.

### UXR-002 — P1 — Kuyruk araması seçimi senkronize etmiyor

- **Screen:** Çalışma Masası / APEX / Satış
- **Action:** Kuyruk aramasına `1500` yazıldı.
- **Expected:** Tek sonuç seçilir veya mevcut seçim temizlenir; sağ panel aynı belgeyi gösterir.
- **Observed:** Liste tek `1500.00` belgeye düştü; sağ panel önceki `238.69` belgeyi göstermeye devam etti.
- **Impact:** Liste, kaynak ve muhasebe taslağı birbirinden kopuyor.
- **Recommendation:** Arama sonucu değiştiğinde seçim yoksa otomatik seçim veya boş durum; belge kimliği eşleşmiyorsa sağ paneli temizleme.
- **Reproducible:** Evet.
- **Evidence:** `1500` arama sonucu ile eski `238.69` taslağının birlikte görüldüğü inline ekran görüntüsü.

### UXR-003 — P1 — Eksik hesap seçimi varken onay aktif

- **Screen:** Çalışma Masası / APEX / Superonline alış faturası
- **Action:** Taslak incelendi.
- **Expected:** `Hesap planından seçim bekleniyor` satırı varken kayıt `review_required` benzeri bir güvenlik durumunda kalmalı ve onay engellenmeli.
- **Observed:** Taslak `✓ Dengeli`, `Müşavir onayı bekliyor` ve `Onayla ve sonraki →` aktif; karşı taraf satırı `Hesap planından seçim bekleniyor`.
- **Impact:** Matematiksel denge, muhasebe kararının tamamlandığı izlenimini veriyor.
- **Recommendation:** Eksik hesap, kaynak veya anlam çözümü varsa karar butonlarını engelle; görünür blokaj nedeni ve sonraki adımı göster.
- **Reproducible:** Evet.
- **Evidence:** Inline Superonline taslağı; exact labels `Hesap planından seçim bekleniyor`, `✓ Dengeli`.

### UXR-004 — P1 — Kaynak bağlantısı görünen belgeyi bulamıyor

- **Screen:** Çalışma Masası / Vodafone ve Superonline taslakları
- **Action:** `↗ Kaynak` ve `Kaynak ayrıntısı` açıldı.
- **Expected:** Kaynak metni bulunur ve vurgulanır; bulunamıyorsa belge içeriğiyle tutarlı açık bir açıklama verilir.
- **Observed:** Kaynak HTML içinde görünürken `Kaynak metin HTML içinde bulunamadı.` uyarısı oluştu. Ayrıntıda `Kaynak: KDV %0` ve bazı satırlarda `Hesap planı açıklaması yok` görüldü.
- **Impact:** Müşavir kaynak kanıtına güvenemez; satır-doğrulama akışı bozulur.
- **Recommendation:** Canonical line/source anchor eşleşmesini düzelt; bulunamayan kaynağı başarı durumu gibi göstermeme; KDV ve satır bağlamını kaynak verisiyle doğrula.
- **Reproducible:** Evet.
- **Evidence:** Inline sarı kaynak kartı ve exact label `Kaynak metin HTML içinde bulunamadı.`.

### UXR-005 — P1 — Öğrenilen Kurallar ekranı 500 hatasını kullanıcıya sızdırıyor

- **Screen:** Öğrenilen Kurallar
- **Action:** Ekran açıldı.
- **Expected:** Kurallar listesi veya müşavir dilinde tekrar dene/açıklama durumu.
- **Observed:** `learning rules failed with 500` ve `Bu kapsamda etkin kural yok.` birlikte gösterildi.
- **Impact:** İşlev çalışmıyor; teknik hata ile geçerli boş liste ayrımı yapılamıyor.
- **Recommendation:** 500 durumunu backend gözlemine kaydet, UI’da kullanıcıya dönük hata ve retry göster; hata varken boş liste mesajını göstermeme.
- **Reproducible:** Evet.
- **Evidence:** Inline Öğrenilen Kurallar ekranı; exact label `learning rules failed with 500`.

### UXR-006 — P1 — Kontrol sayıları bağlamlar arasında açıklamasız çelişiyor

- **Screen:** Üst özet, Onay & Çıktılar, İşlem Durumu, Ayarlar
- **Action:** Aynı oturumda ekranlar arasında gezinildi.
- **Expected:** Ofis/mükellef/dönem kapsamı her sayıda açık ve sayılarla tutarlı olmalı.
- **Observed:** Üstte `0 kontrol` görünürken Onay & Çıktılar `Kısa kontrol 43`, `Blokeli 32`; İşlem Durumu `Kontrol 75`; Ayarlar `Kontrol bekleyen 9` gösterdi.
- **Impact:** Bazı farklar kapsam değişiminden kaynaklanabilir; UI bunu anlatmadığı için müşavir iş yükünü yanlış okur.
- **Recommendation:** Kapsamı bütün sayaçların yanında göster; global badge’i aynı veri kaynağıyla üret; dönem/mükellef değişiminde sayaçların hangi scope’a ait olduğunu açıkla.
- **Reproducible:** Evet.
- **Evidence:** Inline Onay & Çıktılar, İşlem Durumu ve Ayarlar ekranları; exact labels `0 kontrol`, `Kontrol 75`, `Kontrol bekleyen 9`.

### UXR-007 — P1 — Yeni yükleme dönemi üst bağlamla uyuşmuyor

- **Screen:** Yeni Yükleme
- **Action:** Global dönemde `Haziran 2026` görünürken yükleme ekranı açıldı.
- **Expected:** Yükleme dönemi üst bağlamla aynı olmalı veya fark açıkça açıklanmalı.
- **Observed:** Üstte `Haziran 2026`, yükleme alanında `08.2026` göründü.
- **Impact:** Dosyanın yanlış muhasebe dönemine alınması riski.
- **Recommendation:** Tek bir dönem modeli kullan veya “yükleme dönemi” ile “çalışma dönemi” ayrımını belirgin, zorunlu onaylı seçim olarak göster.
- **Reproducible:** Evet.
- **Evidence:** Inline Yeni Yükleme ekranı; exact labels `Haziran 2026` ve `08.2026`.

### UXR-008 — P1 — Mükellef liste ve detay sayıları açıklamasız farklı

- **Screen:** Mükellefler / ARİF ŞAN
- **Action:** Liste ve detay arasında geçiş yapıldı.
- **Expected:** Aynı dönem/kapsam için belge sayıları eşleşmeli veya kapsam belirtilmeli.
- **Observed:** Liste satırında ARİF ŞAN için 3 belge görünürken detayda `Faturalar 7 / 3 kontrol` görüldü.
- **Impact:** Müşavir hangi sayının dönem, toplam veya kontrol kapsamı olduğunu anlayamıyor.
- **Recommendation:** Her sayaca dönem ve kapsam etiketi ekle; drill-down parametresini koru; kapsam farkını metinle anlat.
- **Reproducible:** Evet.
- **Evidence:** Inline Mükellefler listesi ve ARİF ŞAN detay ekranları.

### UXR-009 — P1 — Çıktı kontrollerinin hazır olma durumu birbiriyle çelişiyor

- **Screen:** Onay & Çıktılar
- **Action:** Çıktı özeti incelendi; `CSV oluştur` ve `Paketi hazırla` çalıştırıldı.
- **Expected:** Hazır kayıt yoksa çıktı eylemleri disable veya neden/önizleme ile güvenli hale getirilmeli.
- **Observed:** `Çıktıya hazır 0`, `Dönem toplamı 0 TL`, `Çıktı hazır değil` görünürken `CSV oluştur` ve `Paketi hazırla` aktif; iki aksiyon da `Cikti paketi icin once mukellef ekleyin.` ile sonuçlandı. XLSX için erişilebilirlik ağacı disabled kaldı.
- **Impact:** Boş veya eksik paket üretme ve kontrol durumu konusunda belirsizlik.
- **Recommendation:** Backend readiness tek kaynağı kullan; hazır kayıt yoksa tüm dışa aktarma eylemlerini tutarlı biçimde disable et; XLSX görsel/ARIA durumunu eşleştir.
- **Reproducible:** Evet.
- **Evidence:** Inline Onay & Çıktılar ekranı; exact labels `Çıktıya hazır 0`, `Dönem toplamı 0 TL`, `CSV oluştur`, `Paketi hazırla` ve `Cikti paketi icin once mukellef ekleyin.`.

### UXR-011 — P1 — Hariç tut aksiyonu görünür sonuç üretmiyor

- **Screen:** Çalışma Masası / ARİF ŞAN / Haziran 2026
- **Action:** `1790617537_BEF2026002228563.html` (`17.61`) seçilip `Hariç tut` tıklandı.
- **Expected:** Kayıt kuyruktan çıkarılmalı veya `Hariç` durumu, geri alma yolu ve kullanıcı mesajı görünmeli.
- **Observed:** Liste, sayaçlar ve fiş durumu değişmedi; kayıt hâlâ `Müşavir onayı bekliyor` olarak göründü. Console error/warn kaydı da oluşmadı.
- **Impact:** Hariç bırakma kararı kaydedildi mi bilinmiyor; müşavir aynı kaydı tekrar işleyebilir.
- **Recommendation:** Aksiyonu atomik kaydet; başarılı sonucu kuyrukta ve sayaçta göster; başarısızlığı müşavir dilinde ve retry/geri alma ile açıkla.
- **Reproducible:** Evet.
- **Evidence:** UI sonrası inline snapshot; exact labels `Hariç tut`, `Kontrol 3`, `Onaya hazır 0`, `Müşavir onayı bekliyor`.

### UXR-010 — P1 — Okuma Kalitesi karşılaştırması Fisora satırı üretmiyor

- **Screen:** AI Ajanları / Okuma Kalitesi
- **Action:** Birden fazla HTML belge seçildi.
- **Expected:** Reader sonucu ile Fisora satırları karşılaştırılmalı; kaynak satırı, güven ve uyarı ölçümleri dolmalı.
- **Observed:** Belgeler yüklenmesine rağmen `Reader -`, `Güven -`, `Kaynak satırı 0`, `Fisora satırı 0` ve `Bu belge için Fisora UI satırı oluşmamış.` gösterildi.
- **Impact:** Okuma kalitesi ve satır eşleşmesi denetlenemiyor.
- **Recommendation:** Workbench taslağı ile kalite ekranı arasında ortak belge/satır kimliği kullan; satır oluşmadığında neden ve beklenen durumu ayrıştır.
- **Reproducible:** Evet.
- **Evidence:** Inline AI Okuma Kalitesi ekranı; exact label `Bu belge için Fisora UI satırı oluşmamış.`.

## Broken / non-working interactions

- Boş `Onaya hazır` ve arama filtrelerinde seçim/taslak senkronizasyonu bozuluyor.
- Kaynak satırı bağlantısı bazı görünür HTML kaynaklarında `Kaynak metin HTML içinde bulunamadı.` veriyor.
- Öğrenilen Kurallar API’si UI’da 500 ile görünüyor.
- Okuma Kalitesi, seçilen belgelerde Fisora satırı eşleştirmiyor.
- XLSX üretimi erişilebilirlikte disabled; CSV ve kontrol paketi butonları aktif görünmesine rağmen ikisi de `Cikti paketi icin once mukellef ekleyin.` ile duruyor.
- `Onayla ve sonraki →` ve `Kontrolde tut` sayaç/etiket değişimi üretti; `Hariç tut` görünür sonuç üretmedi; `Ctrl+Z` için görünür geri alma kanıtı oluşmadı.
- Dosya seçimi kullanıcı yetkisi olmasına rağmen mevcut Chrome/CUA katmanında `fileChooser.setFiles failed: Not allowed` ile engellendi; bu nedenle yeni dosya işleme akışı doğrulanamadı.

## Working but poor UX

- Dosya adları ve kuyruk kayıtları çoğunlukla teknik ID/UUID ağırlıklı; tedarikçi, fatura no ve tarih daha görünür olmalı.
- Tarih gösterimleri karışık: `2026-05-21`, `31/05/2026`, `06- 05- 2026 11:12:38`.
- Çalışma Masası’na geçişte sidebar’ın geniş/dar durumu tutarlı görünmüyor; dar durumda metinler görsel olarak kayboluyor, yalnızca ikon/erişilebilir ad kalıyor.
- Banka ve Diğer Belgeler boş durumunda başlık hâlâ `İncelenecek Faturalar`; fatura yönü sekmeleri de görünür kalıyor.
- Teknik hata metni müşavir diline çevrilmemiş.
- Dengeli toplam etiketi, eksik hesap seçimi gibi semantik eksikleri yeterince öne çıkarmıyor.

## Missing product capabilities

- Seçim–liste–kaynak–taslak–eylem arasında atomik belge kimliği güvenlik kapısı.
- Eksik hesap/kaynak/anlam için görünür `review_required` durumu ve zorunlu çözüm yolu.
- Dönem/mükellef/ofis kapsamını bütün sayaçlarda taşıyan ortak context modeli.
- Kaynak satırının canonical HTML/PDF satırına sağlam anchor ile bağlanması.
- Okuma kalite ölçümünde Reader–Fisora satır eşleştirmesi.
- Hazır olmayan çıktıların güvenli şekilde engellenmesi ve boş paket önizlemesi.
- Müşavir dilinde hata, retry ve destekleyici açıklama akışları.

## Strongest parts of the product

- Sol menü görünür ve anlaşılır; `F1` yardım modalı ve `F10` sidebar kısayolu çalıştı.
- Çalışma Masası kaynak belgeyi ve muhasebe taslağını yan yana gösteriyor.
- Alış/Satış yönü ve mükellef açısından yön açıkça gösteriliyor.
- Borç/alacak toplamları ve `Dengeli` durumu hızlı okunuyor.
- PDF/HTML görüntüleyicide sığdır, genişlik, içerik, yüzde, zoom ve büyüteç kontrolleri çalıştı; çok sayfalı belgede sayfa geçişi çalıştı.
- `↗ Kaynak` ile satır kartı vurgulanıyor ve kaynak ayrıntısı açılabiliyor; eşleşme hatası giderildiğinde bu güçlü bir güven katmanı olur.
- AI `İncele` akışı doğru mükellef/dönem ve belgeye yönlendirdi.
- Dosya seçilmeden Yeni Yükleme’de başlatma kontrolleri pasif kaldı.

## Scorecard

| Alan | Skor | Not |
|---|---:|---|
| Günlük iş akışı | 5/10 | Ana yüzey güçlü; filtre/karar senkronu kritik riskli |
| Müşavir anlaşılabilirliği | 6/10 | Görsel hiyerarşi iyi; teknik ID ve teknik hata metni fazla |
| Muhasebe güvenliği | 4/10 | Eksik hesapla onay aktif; stale selection P0 riski |
| Kaynak/izlenebilirlik | 5/10 | Kaynak kartı iyi fikir; anchor eşleşmesi başarısız |
| Navigasyon/kısayollar | 8/10 | F1/F10 ve menü akışı iyi |
| Etkileşim kararlılığı | 4/10 | Arama ve boş filtre eski taslağı bırakıyor |
| Çıktı hazırlığı | 3/10 | Readiness ve button state uyumsuz |
| Hata/boş durumları | 4/10 | Boş yüzeyler var; bazıları teknik veya generic |
| Responsive kanıtı | 2/10 | Bu oturumda 1366/1920/125%/mobil ayrı doğrulanamadı |
| **Genel** | **4.6/10** | **Kontrollü demo seviyesi; ofis pilotu için erken** |

## P0/P1 fixes required before demo

1. UXR-001 ve UXR-002: seçim/taslak/eylem senkronizasyonunu düzelt; boş veya eşleşmeyen seçimde sağ paneli ve eylemleri temizle.
2. UXR-003: eksik hesap, kaynak veya anlam çözümü varken onayı engelle; semantik blokajı `Dengeli` etiketinden daha görünür yap.
3. UXR-004: kaynak anchor ve satır eşleşmesini düzelt; yanlış `bulunamadı` mesajını kaldır.
4. UXR-005 ve UXR-010: öğrenilen kurallar ve okuma kalite ekranlarını kullanıcıya dönük hata/boş durumuyla çalışır hale getir.
5. UXR-006–008: scope/dönem/mükellef context’ini tüm sayaçlara taşı ve sayıların neden farklı olduğunu açıkla.
6. UXR-009: çıktı readiness kapısını tekleştir; disabled/ARIA/görsel durumlarını eşleştir.

## P2 fixes recommended soon

- İnsan tarafından okunabilir kuyruk kimliği ve standart tarih biçimi.
- Boş Banka/Diğer Belgeler başlıklarını ve ilgili olmayan fatura yönü kontrollerini bağlama göre sadeleştirme.
- Sidebar durumunu route geçişlerinde koruma; dar görünüm için tooltip/label ve daha net erişilebilirlik.
- Teknik hata metinlerini müşavir diline çevirme; retry ve destek aksiyonu ekleme.
- 1920×1080, 1366×768, browser zoom 125% ve mobil/tablet için ayrı görsel QA turu.

## Office adoption verdict

Şu an gerçek muhasebe ofisi pilotuna güvenli kabul: **Hayır**. Kontrollü sunum/demo: **Evet**, fakat `Hariç tut` görünür sonuç üretmediği ve çıktı akışları mükellef bağlamı eksikliğiyle durduğu için karar/çıktı akışı güvenilir kabul edilmemeli. Demo durum değişiklikleri bu denetimde ayrıca doğrulandı; canlı/gerçek veri kanıtı değildir.

## Perceived product maturity

Görsel ve bilgi mimarisi “erken çalışan ürün / kontrollü demo” seviyesinde. Müşavir çalışma masası yönü belirgin; güven kapıları, kalite ölçümü, hata iyileştirme ve çıktı hazırlığı üretim olgunluğunda değil.

## Would I buy this for my accounting office? Why / why not?

Bugün satın almazdım. Yan yana kaynak–fiş deneyimi, kaynaklı satır fikri ve klavye akışı satın alma yönünde güçlü; ancak yanlış kayda karar verme riski, eksik hesapla aktif onay, açıklamasız sayı farkları ve çıktı/kalite ekranlarındaki kırık durumlar güven eşiğini geçirmiyor. UXR-001–004 ve çıktı/kalite kapıları düzeltildikten sonra yeniden değerlendirilir.

## Audit journey steps

| # | Akış | Genel sağlık |
|---:|---|---|
| 1 | Login/session ve mevcut müşavir oturumu | Geçti; mevcut oturumla doğrulandı |
| 2 | Landing / Ana Sayfa | Geçti |
| 3 | Sidebar ve ana navigasyon | Geçti; dar/geniş tutarlılık sorunu |
| 4 | Mükellefler listesi | Geçti |
| 5 | Mükellef arama | Geçti |
| 6 | Mükellef detayına geçiş | Kısmi; sayı kapsamı açıklamasız |
| 7 | Yeni Yükleme / alış görünümü | Geçti; dönem bağlamı sorunlu |
| 8 | Yeni Yükleme / satış görünümü | Geçti |
| 9 | Dosyasız yükleme boş durumu | Geçti; dosya seçilmedi |
| 10 | Çalışma Masası’na giriş | Geçti |
| 11 | Alış faturaları | Geçti |
| 12 | Satış faturaları | Geçti |
| 13 | Kaynak PDF/HTML yüklenmesi | Kısmi; kısa loading görüldü, sonra yüklendi |
| 14 | Sığdır/genişlik/içerik/%100/zoom/büyüteç | Geçti |
| 15 | Çok sayfalı belge ileri/geri | Geçti |
| 16 | Fiş satırı kaynak vurgusu | Kısmi; UXR-004 |
| 17 | Kaynak ayrıntısı | Kısmi; metadata/anchor sorunu |
| 18 | Fiş toplamları ve denge | Geçti; semantik gate eksik |
| 19 | Eksik hesap satırı | Kırık güvenlik davranışı; UXR-003 |
| 20 | Onayla ve sonraki | Kısmi; `Kontrol 3 → 2`, `Onaya hazır 0 → 1`; sağ durum metni hâlâ onay bekliyor |
| 21 | Kontrolde tut | Geçti; onaya hazır kaydı tekrar kontrole alındı |
| 22 | Hariç tut | Kırık/no-op; sayaç, liste ve durum değişmedi |
| 23 | Tümü/Kontrol filtreleri | Geçti |
| 24 | Onaya hazır boş filtre | Kırık; UXR-001 |
| 25 | Kuyruk araması | Kırık; UXR-002 |
| 26 | Mükellef değiştirme | Geçti; doğru bağlam senkronlandı |
| 27 | Dönem değiştirme | Geçti; bağlam açıklığı yetersiz |
| 28 | Kuyruk gizle/göster ve Belgeyi İncele | Geçti |
| 29 | F1/F10 ve görünür keyboard yardım | Kısmi; Ctrl+Z çalıştırıldı, görünür geri alma kanıtı oluşmadı |
| 30 | Onay/çıktı, AI, hata, boş durumlar ve responsive kapsam | Kısmi; UXR-005/006/009/010/011; çıktı aksiyonları müşavir ekleme mesajında durdu, 1366/1920/125%/mobil doğrulanmadı |

## Evidence and limitations

Tam denetim çıktısı bu rapordadır. Ekran kanıtları bu sohbet içindeki inline ekran görüntülerinde ve çalışma ağacındaki `ux_audit_*.png` kanıt dosyalarında yer alıyor. UI console error/warn kontrolünde sonuç `[]` oldu. Gerçek dosya yükleme Chrome/CUA dosya seçici kısıtı nedeniyle doğrulanamadı; karar aksiyonları ve çıktı butonları çalıştırıldı, ancak CSV/kontrol paketi indirmesi başlamadı.
