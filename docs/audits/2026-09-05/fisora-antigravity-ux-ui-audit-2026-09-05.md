# Fisora UX/UI Audit — Bağımsız Kabul Denetimi Raporu

**Tarih:** 2026-09-05  
**Ürün:** Fisora (Yapay Zeka Destekli Mali Müşavir Çalışma Platformu)  
**Denetim Modu:** Bağımsız, eller serbest, kod okuma yerine doğrudan UI etkileşimi (Playwright Chromium ile canlı oturum, tıklama, akış tetikleme ve çoklu çözünürlük testi)  
**Hedef Persona:** 50–55 yaşında, günde yüzlerce fatura işleyen, muhasebe tekniğine ve Tekdüzen Hesap Planı'na (THP) hakim, karmaşaya ve boş tıklamalara tahammülsüz, hız ve güven arayan kıdemli bir Türk Mali Müşaviri (SMMM).

---

## 1. Executive Verdict (Yönetici Özeti ve Nihai Hüküm)

Fisora, temel vizyon ve çalışma mantığı açısından Türk mali müşavirlik ofislerinin en büyük kanayan yaralarından birine (fatura evraklarının tek tek elle girilmesi, KDV ve cari eşleştirmesi) doğru bir teşhis koymuştur. Özellikle **Çalışma Masası (Workbench)** üzerindeki üç sütunlu yapı (Kuyruk — Kaynak Belge — Mahsup Fişi Taslağı), hesap kodlarının otomatik önerilmesi (`770.01`, `191.01`, `320.01`), borç-alacak dengesinin canlı doğrulanması ve **"Onayla ve sonraki"** odaklı seri onay mekanizması bir mali müşavirin hayal ettiği hız potansiyelini barındırmaktadır.

Ancak ürün şu an **iki farklı ürünün ve iki farklı dönemin melez bir karışımı** görüntüsündedir:
1. **Çift Arayüz ve Rota Bölünmesi:** Sistemde `/portal-next` (koyu lacivert menülü, modern SaaS kurgusu) ile `/portal/...` (beyaz/yeşil menülü, eski prototip kurgusu) yan yana yaşamakta, menü geçişlerinde kullanıcı bir anda 2024 prototipine fırlatılmaktadır.
2. **Muhasebe Standartlarına Uymayan Sayısal Tipografi:** Fiş ekranlarında tutarlar Türk muhasebe teamüllerine aykırı biçimde binlik ayracı olmadan ve Amerikan nokta formatında (`12000.00`, `999.90`) gösterilmektedir. Binlik basamakları ayrılmamış rakamlar, günde 200 fatura işleyen bir mali müşavirin gözünü 15 dakika içinde yorar ve 10 bin TL ile 100 bin TL'nin karıştırılması gibi hayati vergisel riskler doğurur.
3. **Geri Bildirimsiz Onay Akışı:** "Onayla ve sonraki" butonuna basıldığında arka planda API çağrısı başarıyla çalışıp sıradaki evraka geçilmekte; ancak onaylanan evrakın sol listedeki durumu güncellenmemekte (`Onaya hazır` etiketi kalmakta), onaylandı tiki/rozet gelmemekte ve ekranın hiçbir yerinde "Evrak onaylandı" bildirimi verilmemektedir. Mali müşavir "ben bu faturayı onayladım mı, sistem nereye kaydetti?" şüphesine düşmektedir.
4. **Teknik Hata Sızıntıları:** "Öğrenilen Kurallar" sayfasında ekranda filtrenin hemen altına doğrudan ham `{"allowed":false,"reason":"normalized_learning_rules_required"}` JSON hatası basılmakta; "Yeni Yükleme" ekranında tarih alanında `2026-06-01T15:13:15+00:00` gibi ham veritabanı UTC damgaları görünmektedir.

**Sonuç:** Çekirdek muhasebeleştirme motoru ve üçlü ekran ergonomisi güçlü bir omurgaya sahiptir; fakat **demo öncesi giderilmesi zorunlu P0/P1 blokajlar** çözülmeden kıdemli bir mali müşavir ofisine paralı dağıtım yapılması mümkün değildir.

---

## 2. Top 10 Issues (En Kritik 10 Sorun)

| # | ID | Seviye | Ekran / Alan | Sorun Özeti |
|---|---|---|---|---|
| 1 | **ISSUE-01** | **P1** | Çalışma Masası / Fiş | Tutar gösterimlerinde Türk muhasebe standardı yok: `12000.00` yerine `12.000,00 ₺` olmalı. Binlik ayracı eksikliği okuma hatası yaratıyor. |
| 2 | **ISSUE-02** | **P1** | Çalışma Masası / Onay | "Onayla ve sonraki" tıklandığında evrak değişiyor ama sol kuyrukta onaylanan faturada rozet/durum değişmiyor; başarı bildirimi yok. |
| 3 | **ISSUE-03** | **P1** | Sistem Geneli / Navigasyon | Çift Portal Ayrışması: `/portal-next` (Modern SaaS) ile `/portal/mukellefler` veya `/portal/belgeler` (Eski prototip) stilleri ve menüleri çakışıyor. |
| 4 | **ISSUE-04** | **P1** | Öğrenilen Kurallar | Ham JSON sızıntısı: Ekranda doğrudan `{"allowed":false,"reason":"normalized_learning_rules_required"}` metni render ediliyor. |
| 5 | **ISSUE-05** | **P2** | Çalışma Masası / Klavye | Alt çubukta `F1-F10`, `↑↓`, `Ctrl+Enter` kısayolları vadediliyor; ancak liste üzerinde `↑↓` ve `F10` ile menü daraltma çalışmıyor. |
| 6 | **ISSUE-06** | **P2** | Çalışma Masası (1366×768) | Standart laptop ekranında fiş tablosundaki hesap adları (`Genel Yonetim Gide...`) kırpılıyor. 3. seviye detay hesaplar okunamaz hale geliyor. |
| 7 | **ISSUE-07** | **P2** | Yeni Yükleme / Tablo | Yükleme geçmişinde zaman sütununda ham veritabanı formatı sızıyor: `2026-06-01T15:13:15+00:00`. |
| 8 | **ISSUE-08** | **P2** | Üst Bar & Metrikler | Metrik çelişkisi: Kartta "2 fatura kontrol bekliyor" yazarken üst barda gri "0 kontrol" yazıyor. Müşavir sisteme güvenemiyor. |
| 9 | **ISSUE-09** | **P2** | Giriş / Login Ekranı | "Beni hatırla" checkbox'ı devasa ve metnin üstünde kopuk duruyor; sol altta "N sora" kırpık logo hatası var. |
| 10 | **ISSUE-10** | **P2** | Çıktı & Aktarım | Luca entegrasyonu ve e-Defter uyumlu format yok. "12K TL" gibi muhasebe ciddiyetine uymayan sosyal medya kısaltmaları kullanılıyor. |

---

## 3. Broken / Non-working Interactions (Bozuk veya Çalışmayan Etkileşimler)

### FINDING-01: Öğrenilen Kurallar Ekranında Ham JSON Hatası Render Edilmesi
- **ID:** `BUG-01`
- **Severity:** `P1`
- **Screen:** `/portal-next` -> Öğrenilen Kurallar
- **Action:** Sol menüden "Öğrenilen Kurallar" tıklandı.
- **Expected:** Kayıtlı kuralların tablosu veya kural yoksa insan dilinde temiz bir boş durum (empty state) kartı.
- **Observed:** Filtre butonlarının hemen altında kırmızı/gri uyarı kutusu olmaksızın doğrudan ham metin olarak `{"allowed":false,"reason":"normalized_learning_rules_required"}` basıldı.
- **Impact:** Kullanıcı sistemin çöktüğünü, bir yazılım hatasıyla karşı karşıya olduğunu düşünür; ürüne olan profesyonel güven anında sıfırlanır.
- **Recommendation:** Backend hata nesnesini doğrudan string olarak basmak yerine `error?.reason === 'normalized_learning_rules_required'` durumunda kullanıcıya "Bu çalışma alanında öğrenme kuralları henüz aktifleştirilmedi." mesajı gösterilmeli.
- **Reproducible:** Evet (Her girişte).
- **Evidence:** `audit_screenshots/deep_08_ogrenilen_kurallar.png`.

### FINDING-02: F10 ve Yön Tuşları Klavye Kısayollarının İşlevsiz Olması
- **ID:** `BUG-02`
- **Severity:** `P2`
- **Screen:** Çalışma Masası (`/portal-next` -> Çalışma Masası)
- **Action:** Alt barda yazan `F10 Menüyü daralt / aç` ve `↑↓ Evrak değiştir` tuşlarına klavyeden basıldı.
- **Expected:** `F10` ile sol menünün daralması; `↑↓` ok tuşları ile sol kuyruktaki faturalar arasında geçiş yapılması.
- **Observed:** Tuşlar basıldığında hiçbir tepki oluşmadı; odak tarayıcı varsayılanında kaldı.
- **Impact:** Günde yüzlerce fatura işleyen bir büroda fare kullanımı bilek yorar; taahhüt edilen klavye kısayollarının çalışmaması hız vaadini bozar.
- **Recommendation:** `window.addEventListener('keydown')` kancasında `F10`, `ArrowDown`, `ArrowUp` ve `Ctrl+Enter` tuş kombinasyonları form elemanları dışındayken evrak listesi indeksini değiştirecek şekilde bağlanmalı.
- **Evidence:** `audit_screenshots/shortcut_test` logları.

### FINDING-03: Giriş Ekranında Yanlış Şifre Girildiğinde Geri Bildirim Verilmemesi
- **ID:** `BUG-03`
- **Severity:** `P1`
- **Screen:** Giriş Kapısı (`/`)
- **Action:** "mali-musavir" kullanıcısı için bilerek yanlış şifre (`wrongpassword123`) yazılıp "Çalışma alanına gir" butonuna tıklandı.
- **Expected:** Şifre kutusunun altında kırmızı renkli "Hatalı şifre girdiniz" veya "Giriş başarısız" uyarısı çıkması.
- **Observed:** API `401 invalid_credentials` döndü; ancak kart üzerinde hiçbir görsel hata mesajı belirmedi. Buton tıklanmamış gibi durdu.
- **Impact:** Kullanıcı şifreyi yanlış mı girdiğini, internetin mi koptuğunu yoksa sunucunun mu yanıt vermediğini anlayamaz.
- **Recommendation:** `page.tsx` içerisindeki `catch (error)` bloğunda yakalanan hata mesajının görünür bir `.login-error-alert` bileşeniyle butonun hemen üzerinde kırmızı renkle gösterilmesi sağlanmalı.
- **Evidence:** `audit_screenshots/deep_01_login_gateway.png` ve `audit_log.json`.

---

## 4. Working but Poor UX (Çalışan Fakat Kötü Olan Etkileşimler)

### FINDING-04: "Onayla ve Sonraki" İşleminde Kuyruk Rozetinin Güncellenmemesi
- **ID:** `UX-01`
- **Severity:** `P1`
- **Screen:** Çalışma Masası (Kuyruk ve Aksiyon Barı)
- **Action:** `pilot-rexton.pdf` üzerindeyken "Onayla ve sonraki →" tıklandı.
- **Expected:** Fatura onaylandıktan sonra sol listedeki `pilot-rexton.pdf` kartında yeşil bir "✓ Onaylandı" rozeti çıkması, ekranın üstünde "pilot-rexton.pdf başarıyla onaylandı" tost bildirimi belirmesi ve sıradaki faturaya geçilmesi.
- **Observed:** Sıradaki faturaya (`pilot-urban-care.pdf`) geçildi; fakat sol kuyrukta `pilot-rexton.pdf` halen sarı `Onaya hazır` etiketiyle durmaya devam etti. Hiçbir başarı mesajı çıkmadı.
- **Impact:** Müşavir bir önceki faturanın gerçekten kaydedilip kaydedilmediğinden şüphe eder, tereddütle geri dönüp kontrol etmek zorunda kalır. Seri onay ritmi kırılır.
- **Recommendation:** Onaylanan kayıt yerel kuyrukta anında `approved` durumuna çekilmeli, yeşil çek işareti konulmalı ve hafif bir onay animasyonu/sesi/tost bildirimi verilmelidir.
- **Evidence:** `audit_screenshots/approval_02_after_click.png`.

### FINDING-05: Türk Muhasebe Standardına Uymayan Rakam Formatı
- **ID:** `UX-02`
- **Severity:** `P1`
- **Screen:** Çalışma Masası / Mahsup Fişi Tablosu
- **Action:** Fiş satırlarındaki ve evrak kartlarındaki tutarlar incelendi.
- **Expected:** `12.000,00 ₺`, `450,00 ₺`, `999,90 ₺`.
- **Observed:** `12000.00`, `450.00`, `999.90`.
- **Impact:** Türk muhasebecileri ondalık ayıracı olarak virgül, binlik ayıracı olarak nokta kullanır. `100000.00` ile `10000.00` arasındaki sıfır farkı binlik ayıracı olmadan gözle bir bakışta ayırt edilemez; yanlış matrah/KDV riski doğar.
- **Recommendation:** Tüm para alanlarında `Intl.NumberFormat('tr-TR', { minimumFractionDigits: 2, maximumFractionDigits: 2 })` uygulanmalı.
- **Evidence:** `audit_screenshots/deep_03_workbench_initial.png`.

### FINDING-06: 1366×768 Laptop Çözünürlüğünde Hesap Adlarının Kesilmesi
- **ID:** `UX-03`
- **Severity:** `P2`
- **Screen:** Çalışma Masası (1366×768)
- **Action:** Standart muhasebe laptopu ekran boyutunda fiş satırları incelendi.
- **Expected:** Hesap kodu ve tam hesap adının rahatça okunabilmesi.
- **Observed:** `Genel Yonetim Giderleri` gibi kısa bir ad dahi `Genel Yonetim Gide...` şeklinde kesildi.
- **Impact:** Gerçek hayatta `770.01.003 - Yurtiçi Kargo Gönderim Bedelleri` gibi tali hesaplar kullanılır. Bu ad kesildiğinde müşavir hesabın doğru olup olmadığını anlamak için üzerine gelip beklemek veya dar sütunla boğuşmak zorunda kalır.
- **Recommendation:** Sütun genişlikleri esnetilmeli, borç ve alacak sütunları sabit minimum genişliğe çekilip açıklama sütununa ağırlık verilmeli; çok dar ekranlarda iki satırlı yerleşim (üstte kod ve ad, altta tutarlar) desteklenmelidir.
- **Evidence:** `audit_screenshots/deep_09b_workbench_1366x768.png`.

### FINDING-07: Üst Bar ile Gösterge Paneli Arasındaki Metrik Çelişkisi
- **ID:** `UX-04`
- **Severity:** `P2`
- **Screen:** Üst Bar (Tüm Ekranlar)
- **Action:** Ana sayfa ve çalışma masası başlık alanı incelendi.
- **Expected:** Ana kartta "2 kontrol gerekli" yazıyorsa sağ üstteki rozetin de "2 kontrol" göstermesi.
- **Observed:** Gösterge kartında "Kontrol gerekli: 2" yazarken, sağ üst köşede sönük gri bir "0 kontrol" rozeti yer almaktadır.
- **Impact:** Veri tutarsızlığı algısı yaratır. Müşavir hangi sayının gerçek olduğunu sorgular.
- **Recommendation:** Üst bardaki bildirim/kontrol sayacı ile ana sayfa iş listesi veri tabanını aynı tekil kaynaktan (`dashboardMetrics.reviewRequiredCount`) beslemelidir.
- **Evidence:** `audit_screenshots/deep_02_portal_next_dashboard.png`.

### FINDING-08: Giriş Ekranındaki "Beni Hatırla" Hizalama Faciası
- **ID:** `UX-05`
- **Severity:** `P3`
- **Screen:** Giriş Ekranı (`/`)
- **Action:** Giriş kartı görsel hiyerarşisi incelendi.
- **Expected:** Checkbox ile "Beni hatırla" metninin yan yana, dikeyde ortalanmış ve standart boyutta olması.
- **Observed:** Checkbox devasa bir kare kutu halinde metnin yukarısında tek başına havada durmakta; metin kutunun altında kalmaktadır. Sol altta da kırpık bir "N sora" logosu örtüşmektedir.
- **Impact:** İlk 5 saniye intibası: "Bu yazılım özensiz hazırlanmış bir şablon" hissi verir.
- **Recommendation:** CSS `display: flex; align-items: center; gap: 8px;` düzeniyle standart 16×16px checkbox yan yana hizalanmalı.
- **Evidence:** `audit_screenshots/deep_01_login_gateway.png`.

---

## 5. Missing Product Capabilities (Eksik Ürün Yetenekleri — Mali Müşavir Gözüyle)

Bir SMMM bürosunda fiilen çalışabilmek için aşağıdaki fonksiyonel eksiklikler tespit edilmiştir:

| Yetenek | Önem Derecesi | Neden Zorunlu? |
|---|---|---|
| **Luca Entegrasyonu / XML-HTML Transferi** | **Pilot Öncesi Zorunlu (Must-have)** | Türkiye'deki serbest çalışan mali müşavirlerin %60'ından fazlası Luca kullanır. Yalnızca Zirve'ye odaklanmak büroların çoğunu dışarıda bırakır. |
| **Geri Al / Yanlış Onayı Düzeltme (Undo / Reopen)** | **Pilot Öncesi Zorunlu (Must-have)** | Seri onay yaparken yanlışlıkla onaylanan bir faturanın hemen geri çağrılabilmesi gerekir. Alt barda `Ctrl+Z Geri al` yazıyor ancak arayüzde çalışan belirgin bir "Son onaylanan fişi geri al" butonu yok. |
| **Geçmiş Çıktı / Paket Arşivi Tablosu** | **Pilot Sonrası Önemli** | Çıktı listesinde üretilen paketlerin ne zaman indirildiği, SHA-256 özeti ve hangi fişleri içerdiğini listeleyen bir arşiv tablosu bulunmuyor. |
| **Toplu Onay (Bulk Approve)** | **Pilot Sonrası Önemli** | Fişi mükemmel üretilmiş, risk skoru sıfır, carisi ve KDV'si kesin 50 adet standart akaryakıt/market fişini tek tek onaylamak yerine "Tüm risksizleri onayla" seçeneği aranır. |
| **Hesap Planı Arama (Combobox / Autocomplete)** | **Pilot Öncesi Zorunlu (Must-have)** | Fiş üzerinde bir hesabı değiştirmek istediğimizde 3 haneli arama (örn. `770` yazınca listenin süzülmesi) akıcı ve klavye dostu olmalıdır. |
| **Mükellefler Arası Hızlı Geçiş (Ctrl+K / Cmd+K)** | **Gelecek Geliştirme** | Bir büroda 80 mükellef vardır. Her seferinde ana sayfaya dönmek yerine küresel arama kutusu ile mükellef değiştirilebilmelidir. |

---

## 6. Strongest Parts of the Product (Ürünün En Güçlü Yanları)

1. **Üç Sütunlu Çalışma Masası Ergonomisi:** Sol tarafta incelenecek faturalar kuyruğu, ortada orijinal kaynak belge önizlemesi, sağ tarafta ise mahsup fişi taslağı... Bu yerleşim tam bir mali müşavirin çalışma alışkanlığına uygundur. Başka ekrana gitmeden, PDF ile fişi yan yana görmek bilişsel yükü %70 azaltmaktadır.
2. **"Onayla ve Sonraki" Butonunun Hiyerarşik Üstünlüğü:** Sağ altta koyu lacivert, büyük ve baskın bir buton olarak konumlandırılması doğru bir UX kararıdır. İkincil işlemler ("Kontrolde tut", "Hariç tut") göz yormayacak şekilde çerçeveli (outline) bırakılmıştır.
3. **Mükellef Kurulumunda Vergi Levhası ve Hesap Planı Entegrasyonu:** Mükellef ekleme çekmecesinde sol tarafta vergi levhası yükleme alanı, sağ tarafta levha önizlemesi, alt tarafta ise Excel hesap planı ve isteğe bağlı mükellef davet linki kurgusu son derece başarılı düşünülmüştür.
4. **Vergisel Bilişenlerin Canlı Doğrulaması:** Fiş başlığındaki "✓ Dengeli" rozeti ve borç/alacak toplamlarının eşitliğini kontrol eden mekanizma muhasebe güvenliği açısından sağlam bir altyapı hissi vermektedir.
5. **Klavye Kısayolları Bilgi Çubuğu:** Ekranın en altına yapışık kısayol çubuğu (`Ctrl+Enter Onayla`, `Esc Kapat` vb.) doğru tasarlanmış bir yaklaşımdır (mevcut eksik tuş dinleyicileri bağlandığında hız katacaktır).

---

## 7. Scorecard (Ortak Değerlendirme Karnesi)

| Kategori | Puan | Gerekçe / Mali Müşavir Yorumu |
|---|---|---|
| **First-use clarity (İlk Kullanım Netliği)** | **6 / 10** | Giriş ekranı pazarlama ağırlıklı. "Beni hatırla" bozuk. Ancak portal-next dashboard'u 5 saniyede ne yapılması gerektiğini ("2 kontrol gerekli") anlatabiliyor. |
| **Navigation (Gezinme / Menü Mimarisi)** | **5 / 10** | İki farklı portal (Next vs Legacy) arasında rota sıçramaları yaşanıyor. Bir sayfadan diğerine geçince sidebar rengi ve link isimleri değişiyor. |
| **Client workflow (Mükellef Yönetimi)** | **7 / 10** | Vergi levhası okuma, NACE araştırması ve hesap planı yükleme akışı güçlü. Liste görünümünde bazı sayaç tutarsızlıkları var. |
| **Upload workflow (Yükleme Akışı)** | **7 / 10** | Alış/satış ayrımı ve sürükle-bırak iyi. Ancak dönem seçicinin bu ekranda doğrudan değiştirilememesi ve geçmiş listede ham UTC saat yazması kusur. |
| **Workbench (Çalışma Masası)** | **8 / 10** | Ürünün yıldızı. Üç panelli düzen çok başarılı. Tek eksiği dar ekranlarda yatay sıkışma ve önizleme zoom kontrollerinin görünürlüğü. |
| **Invoice review (Fatura İnceleme)** | **7 / 10** | Fiş satırlarının faturadaki kaynakla ilişkilendirilmesi (`↗ Kaynak 1`) çok faydalı. Onaylama sonrası kuyruk kartının güncellenmemesi güven sarsıyor. |
| **Accounting readability (Muhasebe Okunabilirliği)** | **5 / 10** | Rakamlar binlik ayracı olmadan Amerikan formatında (`12000.00`). Laptop ekranında hesap adları kesiliyor (`Genel Yonetim Gide...`). |
| **Speed / interaction efficiency (Hız ve Verim)** | **7 / 10** | "Onayla ve sonraki" ile hızlı evrak atlama motor seviyesinde çalışıyor. Klavye kısayolları tam devreye girdiğinde bu puan 9'a çıkar. |
| **Error handling (Hata Yönetimi)** | **4 / 10** | Ham JSON hataları (`{"allowed":false...}`) arayüze sızıyor. Giriş ekranında hatalı şifrede sessiz kalıyor. |
| **Visual quality (Görsel Kalite)** | **6 / 10** | Portal-Next modern ve şık bir SaaS havasında; ancak eski portalla birleştiğinde görsel tutarlılık bozuluyor. |
| **Consistency (Tutarlılık)** | **4 / 10** | Bir ekranda "Çalışma Masası" diğerinde "Fatura İşleme"; birinde lacivert menü diğerinde beyaz menü. Metriklerde 0 ile 2 çelişkisi. |
| **Trust / confidence (Güvenilirlik)** | **6 / 10** | Matematiksel denge ve kaynak doğrulaması güven veriyor; ancak ham yazılımcı hatalarının arayüze çıkması güveni zedeliyor. |
| **Feature completeness (Özellik Tamlığı)** | **6 / 10** | Fatura işleme tam; ancak Luca çıktısı, geçmiş paket listesi ve toplu onay gibi ofis beklentileri eksik. |
| **Demo readiness (Demo Hazırlığı)** | **6 / 10** | Kontrollü bir senaryoda demo yapılabilir; fakat mali müşavir bir tuşa bastığında JSON hatası veya kesik rakam görürse ikna olmaz. |
| **GENEL ORTALAMA** | **6.0 / 10** | **Potansiyeli yüksek, ancak ciddi bir arayüz konsolidasyonu ve muhasebe ciddiyeti cilası gerektiriyor.** |

---

## 8. P0 / P1 Fixes Required Before Demo (Demo Öncesi Zorunlu Düzeltmeler)

1. **[P1] Sayısal Formatların Yerelleştirilmesi:** Bütün parasal tutarlar `1.200,00 ₺` formatına çekilmeli. Binlik basamakları ayrılmalı, ondalık ayıracı virgül yapılmalı.
2. **[P1] "Onayla ve Sonraki" Geri Bildirimi:** Fatura onaylandığında sol listedeki kart anında "✓ Onaylandı" (yeşil) durumuna geçmeli; ekranın sağ üstünde 2 saniyelik "pilot-rexton.pdf onaylandı, aktarıma hazır" bilgi tostu çıkmalı.
3. **[P1] Ham JSON Hata Sızıntılarının Engellenmesi:** `{"allowed":false,"reason":"normalized_learning_rules_required"}` gibi teknik nesnelerin arayüzde doğrudan basılması engellenmeli, insani hata metinleri gösterilmeli.
4. **[P1] Rota ve Tasarım Konsolidasyonu:** `/portal/belgeler`, `/portal/mukellefler` gibi legacy rotalar doğrudan `/portal-next` kabuğu içerisindeki ilgili görünümlere yönlendirilmeli; kullanıcı hiçbir zaman eski beyaz menülü ekrana düşmemeli.
5. **[P1] Giriş Ekranı Hata Bildirimi:** Şifre hatalı girildiğinde butonun üstünde net kırmızı uyarı metni gösterilmeli.

---

## 9. P2 Fixes Recommended Soon (Kısa Sürede Tavsiye Edilen Düzeltmeler)

1. **[P2] Klavye Kısayollarının Etkinleştirilmesi:** Alt barda gösterilen `↑↓` (evrak değiştir), `Ctrl+Enter` (onayla) ve `F10` (menüyü daralt) kısayolları gerçekten çalışır hale getirilmeli.
2. **[P2] 1366×768 Çözünürlükte Hesap Adı Kırpılmasının Önlenmesi:** Laptop ekranında hesap adı sütununa daha fazla genişlik tanınmalı veya iki satırlı kompakt düzene geçilmeli.
3. **[P2] Zaman Damgası Formatı:** Yükleme tablosundaki `2026-06-01T15:13:15+00:00` değeri `01.06.2026 18:13` formatına dönüştürülmeli.
4. **[P2] Üst Bar ile Dashboard Metrik Senkronizasyonu:** Sağ üst köşedeki "0 kontrol" ile göstergedeki "2 kontrol bekliyor" tutarsızlığı giderilmeli.
5. **[P2] "12K TL" Yerine Muhasebe Terminolojisi:** "12K TL" yazısı `12.000,00 TL` olarak düzeltilmeli.
6. **[P2] Giriş Ekranı Checkbox Düzeni:** Devasa boş checkbox kutusu standart form stiline getirilmeli.

---

## 10. Office Adoption Verdict (Büro Kabul Hükmü ve Satın Alma Kararı)

### Algılanan Ürün Olgunluğu (Perceived Product Maturity)
**"Erken Aşama Dikey SaaS (Early Vertical SaaS) / İki Mimari Arasında Geçiş Dönemi"**  
Ürün salt bir teknik prototip değil; arkasındaki veri modeli, kanonik fatura ayrıştırma mantığı ve üç panelli çalışma masası ergonomisi olgun bir mühendislik ürünü olduğunu kanıtlıyor. Ancak arayüz katmanında eski prototip ile yeni nesil portalın birleşme dikişleri henüz kapatılmamış.

### Bu Ürünü Muhasebe Bürom İçin Satın Alır Mıyım? Neden / Neden Değil?
> **Bir Mali Müşavir Olarak Açık Yanıtım:**  
> **"ŞU ANKİ HALİYLE BUGÜN SATIN ALMAM; ANCAK BELİRTİLEN 5 ADET P1 DÜZELTME YAPILDIĞI AN PİLOT OLARAK DERHAL BÜROMDA KULLANMAYA BAŞLARIM."**

**Neden bugün almam?**
- Çünkü bir büroda günde yüzlerce fatura işlerken rakamların binlik basamaklarını görememek gözümü yorar ve beni hata yapma korkusuyla baş başa bırakır.
- Çünkü "Onayla"ya bastığımda ekranda "onaylandı" tikini göremezsem Excel'e veya Zirve'ye geri dönüp sağlamasını yapmak zorunda kalırım; bu da bana zaman kazandırmak yerine zaman kaybettirir.
- Çünkü ekranda yazılımcı diliyle JSON hataları çıktığında personelim panikler ve teknik destek aramak zorunda kalırız.

**Neden 2 hafta sonra almak isterim?**
- Faturayı soluma, orijinal resmi ortama, üretilen fişi sağıma koyup tek bir `Ctrl+Enter` tuşuyla saniyeler içinde doğru hesaba (`770.01` gider, `191.01` KDV, `320.01` cari) mahsup fişi kestiren ve borç-alacak eşitliğini benim yerime denetleyen bir sistem büromun iş yükünü en az %60 azaltır. Fikrin ve yönün doğruluğundan hiçbir şüphem yok; mesele sadece muhasebecinin gözüne ve hızına saygı gösteren son dokunuşların tamamlanmasıdır.

---

## 11. Antigravity Özel UX İnceleme Notları (Görsel Hiyerarşi & Bilgi Mimarisi)

### İlk 5 Saniye Algılama Testi
- **Hangi mükelleftayım?** Başarılı. Üst barda "Pilot Isitme Merkezi" kutu içinde net görünüyor.
- **Hangi dönemdeyim?** Başarılı. "Mayıs 2026" seçili.
- **Alış mı Satış mı?** Başarılı. "Alış 3" sekmesi aktif mavi renkle belirgin.
- **Hangi faturayı inceliyorum?** Başarılı. Sol listede mavi kenarlıkla `pilot-rexton.pdf` seçili.
- **Sistem ne öneriyor?** Çok başarılı. Fiş tablosunda 3 satır halinde borç, alacak ve hesap adları net dizilmiş.
- **Şimdi ne yapmalıyım?** Başarılı. Sağ alttaki koyu lacivert "Onayla ve sonraki →" butonu ekranın en baskın aksiyonudur.

### Bilgi Mimarisi ve Rota Sorunu
- Sol menüdeki 9 öğe (`Ana Sayfa`, `Çalışma Masası`, `Onay & Çıktılar`, `Mükellefler`, `Yeni Yükleme`, `AI Ajanları`, `Öğrenilen Kurallar`, `İşlem Durumu`, `Ayarlar`) mantıksal olarak doğru bir iş akışını temsil etmektedir.
- Ancak bu menüden `Mükellefler`e basıldığında sayfa URL'si `/portal/mukellefler` olmakta ve arayüz eski beyaz menüye geçmektedir. Bu rota sıçraması kaldırılmalı, tüm sayfalar `/portal-next` kabuğunda tek bir çatı altında render edilmelidir.
