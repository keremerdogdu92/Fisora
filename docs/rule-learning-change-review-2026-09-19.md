# Fisora Rule-Learning Değişiklik İncelemesi — 2026-09-19

Bu belge, production baseline `829c468` sonrasında gelen rule-learning değişikliklerini **tek tek** değerlendirmek için hazırlanmıştır.

Amaç: Değişiklikleri topluca kabul/ret etmek yerine her davranışı ayrı incelemek; korunacak parçaları kurtarmak, yanlış mimari yolları geri almak ve gerekiyorsa doğru mimariyle yeniden yazmak.

## Güvenli başlangıç noktası

- Production: `829c468` — test edilmiş ve çalışan sürüm.
- Main: `de0a486`.
- `15d310c` semantic hesap adaylarını zorla daraltan değişiklik geri alınmıştır.
- Production'a yeni deploy yapılmadı.
- Bu inceleme tamamlanana kadar davranış değiştiren yeni patch uygulanmayacak.

## Şimdiden kesinleşenler

### KALACAK

1. `f7569fa` — Routeway provider desteği.
2. Kuralların yalnız exact hesap kodu sabitlemek zorunda olmaması.
3. `binding_mode = semantic_role` modeli.
4. Tedarikçi bazlı genel semantic kurallar. Örnek: “Bu firmadan gelen her şey mal alımıdır.”
5. Aynı kararın üç tekrar sayılması için **üç farklı belge/fatura** evidence'ı aranması.
6. Production'da zaten bulunan AI Rule Harness ve `Öğrenilmiş kural kontrolü` UI'sı.
7. `2db12ed` içindeki otomatik upload test düzeltmesi.

### İNCELENECEK / MUHTEMELEN DEĞİŞECEK

1. `4d9f0b7` ile eklenen `_active_semantic_rule_constraint` yolu.
2. Semantic rule'un AI muhasebe çağrısından önce deterministik olarak aday gruplarını etkilemesi.
3. Semantic rule'ların mevcut AI Rule Harness tarafından kullanılamaması.
4. `Onayla ve sonraki` akışının learning prompt geldiğinde aynı faturada durması.
5. Utility precedent davranışının kapsamı ve UI'daki yeri.
6. `2db12ed` içindeki semantic testlerin hangi nihai mimariyi sabitlemesi gerektiği.

---

# İnceleme sırası

Her seferinde yalnız **bir adım** konuşulacak. Karar verilmeden sonraki adıma geçilmeyecek.

## Adım 1 — Mevcut production Rule Harness tam olarak ne yapıyor?

Amaç:
- `829c468` içindeki Harness'ın görevini netleştirmek.
- Nerede devreye girdiğini görmek.
- Fişi otomatik değiştirip değiştirmediğini kesinleştirmek.
- `Uygula / Doğru değil` kullanıcı kontrolünün rolünü anlamak.

Bilinen mevcut yapı:

```text
Normal muhasebe pipeline
        ↓
Fiş taslağı oluşur
        ↓
AI Rule Harness (shadow audit)
        ↓
Kural arama planı
        ↓
Host rule search
        ↓
Aday kural seçimi / açılması
        ↓
Final AI audit
        ↓
Öneri
        ↓
Müşavir: Uygula / Doğru değil
```

Önemli: `backend/app/services/learned_rule_audit_shadow.py` bugün kendisini **non-authoritative** olarak tanımlar ve draftı otomatik değiştirmez.

### Adım 1 kararı — 2026-09-19

Bu davranış değiştirilecek: Harness tam ve doğrulanmış bir `correction` ürettiğinde kural sonucu **muhasebe fişine doğrudan uygulanacak**. Ancak Muhasebe AI'ın ilk kararı silinmeyecek.

Mevcut Harness çıktısı bunu taşımak için zaten gerekli provenance alanlarına sahip:

```text
from_account = Muhasebe AI'ın ilk seçimi
to_account   = öğrenilmiş kuralın uygulanmış sonucu
rule_id      = uygulanan kural
reason       = neden uygulandığı
```

Hedef gösterim:

```text
Fişte aktif hesap: 153.01
Kural uygulandı
Muhasebe AI: 770.01 -> Öğrenilmiş kural: 153.01
```

Yani `draft_lines` / aktif fiş kural uygulanmış sonucu gösterecek; ilk AI seçimi ise Harness provenance'ında korunacak ve UI'da erişilebilir/görünür olacak. Bu bir kör overwrite olmayacak.

Otomatik uygulama ancak Harness sonucu `completed`, `audit_status=complete`, validation error yok ve hedef hesap hesap planında doğrulanmışsa yapılmalı. `unresolved` veya çelişkili sonuç fişi değiştirmemeli.

UI tarafında mevcut `Öğrenilmiş kural kontrolü` bölümü artık yalnız `Uygula` bekleyen bir kutu olmak yerine **hangi kuralın otomatik uygulandığını ve AI'ın önceki kararını gösteren provenance/karşılaştırma alanına** dönüşecek. Nihai görsel biçim daha sonra ayrıca netleştirilecek.

### Adım 1 uygulama durumu — tamamlandı

Adım 1 kodlandı. Güvenli ve doğrulanmış Harness correction artık aktif muhasebe fişine otomatik uygulanıyor.

Uygulama sözleşmesi:
- `draft_lines` kural uygulanmış hesabı taşır.
- Muhasebe AI'ın ilk hesabı Harness provenance'ında `from_account` olarak korunur; ayrıca uygulanan draft satırında `ai_original_account_code` tutulur.
- `line_decisions` değiştirilmez; AI'ın ilk satır kararı olarak kalır.
- `rule_id`, `reason`, `to_account` ve `application_status` görünür provenance sağlar.
- UI'daki eski `Uygula / Doğru değil` butonları kaldırıldı.
- UI artık `Muhasebe AI: ... → Kural: ...` ve `Kural uygulandı` gösterir.
- Harness sonucu incomplete/unresolved ise, validation error varsa, hedef hesap hesap planında yoksa, satır tekil eşleşmiyorsa veya bir fiş satırına birden fazla correction geliyorsa uygulama atomik olarak bloklanır ve fiş değiştirilmez.
- Kuralın otomatik uygulanmış hesabı daha sonra yeni bir öğrenme notu/kuralı oluştururken de kullanılan efektif iş hesabı olarak taşınır.
- `learned_rule_audit_shadow` / `FISORA_LEARNED_RULE_AUDIT_SHADOW_*` gibi mevcut iç isimler bu adımda uyumluluk için korunmuştur; artık workflow seviyesinde güvenli correction sonucu authoritative olarak fişe uygulanır.

Doğrulama:
- Hedef backend Harness/application testleri: 11/11 geçti.
- Frontend unit/contract testleri: 256/256 geçti.
- TypeScript `tsc --noEmit`: geçti.
- Targeted Chromium Harness E2E: 3/3 geçti.
- Full Chromium E2E: 36/36 geçti.
- Full backend regression: 1188 passed / 37 skipped / 0 failed. Mevcut 882 warning Python 3.14/FastAPI/pytest-cache kaynaklıdır; test failure değildir.

## Adım 2 — Semantic rule nedir ve nasıl saklanmalı?

Bu adımın ana tasarım sorusu ayrıca şudur: kuralı doğrudan belirli hesap koduna (`153.01`, `760.03.010`) mı bağlayacağız, yoksa önce muhasebe mantığına (`stock`, `expense`, `kargo_gideri`, `mal_alim`) bağlayıp o mükellefin hesap planındaki exact hesabı çalışma anında mı çözeceğiz? Mevcut `semantic_role / semantic_intent` işi ikinci yaklaşım için hazırlanmış görünüyor. Burada hazır yapılmış parçalar tek tek kontrol edilmeden karar verilmeyecek.

Örnek hedef:

```text
Bu firmadan gelen her şey mal alımıdır.
```

Beklenen kayıt mantığı:

```text
scope = client_counterparty
binding_mode = semantic_role
semantic_role = stock
semantic_intent = mal_alim
line_match_mode = all_lines
account_code = ""
```

Bu adımda sadece **kural veri modeli** değerlendirilecek. Kuralın nasıl uygulanacağı henüz tartışılmayacak.

### Adım 2 deney notu — Rule record A/B + ölçek testi (2026-09-19)

Adım 2 veri modelini seçmeden önce mevcut Rule Harness test ortamı yeniden kullanıldı. Eski benchmark corpus'u korunarak iki kayıt biçimi karşılaştırıldı:

- Legacy rule record.
- Dört alanlı compact rule record: `summary / trigger / action / guardrail` + mevcut deterministic machine fields.

Test ilkesi:
- Search aşamasına full rule metni verilmez.
- Candidate aşaması kısa index kullanır.
- Dört alanın tamamı yalnız `get_rule` ile gerçekten açılan kurallarda final audit'e taşınır.
- Böylece rule-store 500 / 2.000 / 10.000 kurala büyüse bile bütün rule metinleri context'e basılmaz.

Kontrollü final-stage A/B:
- 500 rule / 19 vaka:
  - Legacy: 19/19, false correction 0.
  - 4 alanlı: 19/19, false correction 0.
  - Ortalama total token: 5.175 -> 5.692 (~%10 artış).
  - Ortalama süre: 2.84 sn -> 2.90 sn.
- 2.000 rule / en ağır 5 vaka:
  - Legacy: 4/5; başarısız vakada hedef hesap doğru bulundu fakat model final JSON'da 11 satırın yalnız ilk 3'ünü döndürdü ve coverage validation'a takıldı.
  - 4 alanlı: 5/5, false correction 0.
  - Ortalama total token: 6.706 -> 7.598.

Gerçek 3-stage 10.000-rule stres testi:
- Legacy: 5/5; expected rule seen/opened/applied 5/5; false correction 0; ortalama ~20.1k token / ~20.5 sn.
- 4 alanlı ilk koşuda 2/2 başarılı sonuçtan sonra üç çağrı Gemini 429 provider rate-limit'e girdi.
- Retry/backoff destekli tekrar koşusunda eksik üç vaka da 3/3 geçti; böylece 4 alanlı 10.000-rule setinin beş ağır vakasının tamamı başarıyla doğrulandı. False correction 0.
- İlk 429 sonuçları model/record-format kalite hatası olarak sayılmadı; provider error olarak ayrı tutuldu.

Benchmark provider retry sözleşmesi:
- 429 / Too Many Requests ve geçici 408/5xx/timeout/transport/connection hataları retry edilebilir provider hatasıdır.
- 429 sonrasında Gemini project-pool cooldown'u ile uyumlu 65 saniye backoff uygulanır.
- Varsayılan en fazla 2 retry yapılır.
- Retry bütçesi tükense bile provider error, semantic/functional model failure metriğine karıştırılmaz; ayrı raporlanır.
- Bu retry yalnız benchmark runner içindir; production runtime davranışı bu deneyle değiştirilmez.

Gemini havuzu doğrulaması:
- Benchmark env'de 6 benzersiz slot mevcut: 1, 3, 4, 5, 6, 7.
- 429 stresinden sonra altı slot da ayrı ayrı health probe ile başarılı cevap vermiştir; gözlenen durum kalıcı key kaybı değil geçici burst/rate-limit'tir.

Bu deneyler production davranışını değiştirmedi ve deploy edilmedi.

### Adım 2 semantic-role Harness deneyi — exact hesap saklamadan

Ayrı lab testinde hedef kuralların authoritative kaydından exact hesap kodu tamamen kaldırıldı. Her semantic target rule için model yalnız şu bilgileri gördü:

- `summary / trigger / action / guardrail`
- `binding_mode=semantic_role`
- `semantic_role`
- `semantic_intent`
- scope / direction / counterparty / line-match alanları
- `account_code=""`

Benchmark, beklenen exact hesabın full rule JSON'unda geçtiğini görürse model çağrısından önce fail olacak leakage guard ile çalıştırıldı.

İlk 500-rule / 7 zor vaka:
- Full hesap planını final prompta verme: 5/7 functional success, ortalama ~35.3k token.
- Burada bir postal-service sonucu aslında doğru correction üretmesine rağmen eski fixed-account conflict validator'ının `semantic account_code=""` değerini ayrı hesap sanması nedeniyle false failure oldu. Validator semantic-aware hale getirildi.
- Full chart yaklaşımı gereksiz context ürettiği için devam yaklaşımı olarak uygun görülmedi.

Semantic-role family-filtered current-chart deneyi:
- Host yalnız semantic role dışındaki hesap ailelerini deterministik olarak eler; exact detail hesabı seçmez.
- 500 rule / 7 vaka: 6/7 functional success, false correction 0, validation error 0.
- Ortalama total token ~14.2k. Full-chart deneye göre context belirgin biçimde küçüldü.
- Tek kalan oynak vaka `AMPLIFIER XCEED 3 BTE UP SER MDR`: doğru Xceed rule her seferinde search'te görüldü ve açıldı, fakat final applicability modeli bazı koşularda bariz family eşleşmesini `not_applicable` saydı.
- Production family-match yönergesi semantic prompta da eklendikten sonra aynı vaka üç tekrar koşusunda 1/3 geçti. Dolayısıyla bu, retrieval değil final applicability kararlılığı riski olarak kaydedildi; mimari kararda göz ardı edilmeyecek.

Geniş tedarikçi semantic rule deneyi:
- Tek kural: `DUYU normal alışları = stock / mal_alim`.
- Kuralın içinde `153.01` veya `153.02` hiç saklanmadı; leakage guard ile doğrulandı.
- Aynı 9 satırlı gerçek faturada her tur yalnız bir satıra ters stok alt hesabı enjekte edildi.
- Beklenen doğru dağılım cihaz satırlarında mevcut chart'tan `153.01`, KIT/aksesuar satırlarında `153.02` idi.
- 500-rule store içinde sonuç: **9/9**; rule seen/opened/applied 9/9, false correction 0, unresolved 0.
- Bu sonuç semantic supplier rule'un muhasebe yönünü/aileyi sabitleyip exact detail hesabı güncel hesap planı + satır içeriğine bırakmasının uygulanabilir olduğunu güçlü biçimde destekliyor.

10.000-rule broad-supplier ölçek tekrarı:
- Temsilî üç hedef satır çalıştırıldı: cihaz `153.01`, KIT `153.02`, KIT `153.02`.
- İlk semantic final contract'ında rule seen/opened üçünde de 3/3 olmasına rağmen exact sonuç 2/3 kaldı.
- Başarısız KIT vakasında model broad semantic rule için açıkça `applies` dedi fakat mevcut yanlış draft hesabı `153.01`'i koruyup "doğru" saydı.
- Bu nedenle failure retrieval veya semantic applicability değil, **draft-account anchoring** olarak sınıflandırıldı.

Draft-account-blind final resolver deneyi:
- Final model çağrısından mevcut draft hesap kodu tamamen çıkarıldı.
- Modelin görevi artık "correction/no-change" kararı vermek değil; yalnız opened semantic rule + invoice row + current family-filtered chart üzerinden `resolved_account` seçmek.
- Host daha sonra `resolved_account` ile mevcut draft hesabını deterministik karşılaştırarak correction/no-change üretir.
- Ek model çağrısı eklenmedi; pipeline yine search + candidate + final olmak üzere 3 model çağrısıdır.
- Problemli KIT satırı 500-rule ortamında üç tekrar **3/3** doğru `153.02` çözüldü.
- Aynı 9 satırlı gerçek tedarikçi faturasında 500-rule tam set **9/9** geçti; cihaz satırları `153.01`, KIT/aksesuar satırları `153.02`; false correction 0, unresolved 0.
- 10.000-rule temsilî set de **3/3** geçti; rule seen/opened/applied 3/3, false correction 0, unresolved 0.
- 10k ortalama toplam token yaklaşık 24.8k, ortalama süre yaklaşık 32.6 sn.
- Bu sonuç broad supplier semantic rule için exact detail hesabı seçerken mevcut draft hesabını final resolver'dan gizlemenin anchoring sorununu kaldırdığını güçlü biçimde destekliyor.
- Semantic rule kaydında eski/source exact hesap kodu yine hiçbir yerde saklanmadı; leakage guard korunuyor.

Product/service semantic rule doğrulaması:
- Blind-final contract'a ayrıca sert gate eklendi: en az bir opened rule `applies` değilse model hesap çözemez; zorunlu `no_applicable_rule` + boş hesap döndürür. Böylece Harness, learned rule yokken kendi başına muhasebe kararı üretmez.
- Daha önce applicability oynaklığı gösteren Xceed vakası bu sıkı kontratla 500-rule ortamında üç tekrar **3/3** geçti; target `153.01`, false correction 0, validation error 0.
- 500-rule / 7 farklı zor semantic vaka tam set: **7/7** geçti. Aksesuar stok, cihaz stok, kira/işyeri gideri, personel yemek, kargo/posta ve istisnalı satış dahil; rule seen/opened/applied 7/7, false correction 0, unresolved 0.
- 500-rule tam sette ortalama yaklaşık 14.7k token / 12.3 sn.
- 10.000-rule temsilî product/service stress: aksesuar stok `153.02`, Xceed cihaz stok `153.01`, posta/kargo gideri `770.01.005` => **3/3** geçti; rule seen/opened/applied 3/3, false correction 0, unresolved 0.
- 10k product/service üçlü ortalama yaklaşık 20.4k token / 22.8 sn.
- Böylece semantic lab'de kalan iki ana hata sınıfı — draft-account anchoring ve learned-rule yokken serbest hesap çözme — ayrı final contract ile kapatılmış görünüyor.
- Bu bölümdeki sonuçlar önce lab'de elde edildi; aşağıdaki Adım 3/4 kararıyla doğrulanan kontrat production Harness koduna taşındı.

## Adım 3 — Semantic rule'u kim uygulamalı?

### Karar — 2026-09-19

Current three-stage AI pipeline için canonical yol **AI Rule Harness** seçildi.

```text
Planner
    ↓
Muhasebeci AI
    ↓
Normal fiş taslağı
    ↓
AI Rule Harness
    ↓
Kural arama / açma / applicability
    ↓
Kuraldan bağımsız resolved_account
    ↓
Host mevcut fişle karşılaştırır
    ↓
Gerekirse correction uygulanır
```

Kritik ayrım: Harness AI artık Muhasebeci AI'ın seçtiği mevcut hesap kodunu veya karar gerekçesini görmez. Böylece semantic resolver önceki yanlış hesaba ankraj olmaz. Muhasebeci AI'ın ilk kararı provenance olarak sistemde korunur; yalnız Harness model context'ine verilmez.

Bu karar üç-aşamalı güncel AI akışı içindir. Eski simulation/fallback tarafında bulunan direct semantic constraint yardımcı yolu bu adımda sökülmedi; ayrı legacy cleanup konusu olarak kalır ve bu commitin kapsamı değildir.

## Adım 4 — Harness semantic-role desteği — uygulandı

Production Harness kodu semantic-role kuralları çalıştıracak şekilde güncellendi:

- `_usable_rule()` artık `binding_mode=semantic_role` ve `account_code=""` kuralları kabul eder.
- `fixed_account` kurallarda exact `account_code` authoritative kalır.
- `semantic_role` kurallarda eski/source exact hesap kural kaydında taşınmaz.
- Full rule açıldığında AI'a dört alan verilir: `summary / trigger / action / guardrail` + makine alanları.
- Search/candidate aşamalarında full dört alan context'e basılmaz; kısa index kullanılır.
- Semantic final resolver yalnız opened rule + fatura satırı + semantic aileye filtrelenmiş **güncel hesap planı** görür.
- Final AI correction/no-change kararı vermez; yalnız bağımsız `resolved_account` üretir.
- Host `resolved_account` ile Muhasebeci AI'ın mevcut draft hesabını deterministik karşılaştırır.
- En az bir opened rule `applies` değilse hesap çözümü yasaktır: zorunlu `no_applicable_rule` + boş hesap.
- Birden fazla applicable rule çelişirse validation audit'i incomplete yapar; güvenli auto-apply gerçekleşmez.
- Semantic kural persistence artık `meaning_label / trigger_tr / action_tr / guardrail_tr` alanlarını saklar.
- Semantic narrative içinde historical exact hesap metin olarak bile tutulmaz; exact hesap yalnız fixed-account rule'da saklanır.

Doğrulama:
- Harness/application/lifecycle/phase0 hedef regresyonu: **54 passed / 1 skipped / 0 failed**.
- Full backend regression: **1191 passed / 37 skipped / 0 failed**.
- Gerçek Gemini production-Harness smoke: semantic MINIFIT kuralı ile yanlış draft `153.02` bağımsız olarak `153.01` çözüldü; audit complete, validation error 0, 3 model çağrısı.
- Lab ölçek sonuçları: 500-rule semantic zor set 7/7; broad supplier 9/9; 10.000-rule temsilî semantic setler 3/3.
- Bu aşamada deploy yapılmadı.

## Adım 5 — Tedarikçi bazlı genel kurallar

Korunacak davranış:

```text
Bu firmadan gelen her şey mal alımıdır.
```

Alt hesap ürün/fatura içeriğine göre seçilebilir.

Bu adımda:
- client + counterparty scope,
- alış/satış yönü,
- normal/iade ayrımı,
- utility istisnaları,
- line-specific istisnalar
ayrı ayrı gözden geçirilecek.

## Adım 6 — 3 farklı fatura evidence sistemi

Korunacak temel davranış:

- Aynı document tekrar kaydedilerek sayaç şişmemeli.
- `document_ref` benzersiz olmalı.
- Aynı karar üç farklı faturada doğrulanınca prompt oluşmalı.
- UI son evidence faturalarını gösterebilmeli.

İncelenecek:
- aynı belge farklı revision olduğunda nasıl sayılmalı,
- issue_date yalnız gösterim mi yoksa kimliğin parçası mı,
- threshold her durumda 3 mü olmalı.

## Adım 7 — Yeni Learning UI

İki UI birbirinden ayrılacak:

### A. Production'da zaten olan Harness UI

`Öğrenilmiş kural kontrolü`

- Harness sonucudur.
- `Uygula / Doğru değil` vardır.
- Production baseline'da zaten mevcuttur.

### B. `4d9f0b7` ile gelen tekrar/öğrenme kartı

`Fisora bir tekrar fark etti`

Gösterdiği bilgiler:
- `3/3`
- evidence documents
- suggested note
- `Şimdilik geç`
- `Kuralı incele`

Bu kartın korunup korunmayacağı ve nerede görünmesi gerektiği ayrı değerlendirilecek.

## Adım 8 — Onayla ve sonraki davranışı

`4d9f0b7` sonrası:

```text
Onayla ve sonraki
    ↓
Kaydet
    ↓
client_repeat_prompt / office_utility_precedent varsa
    ↓
Aynı faturada kal
```

Bu davranış ayrı karardır. Semantic rule modeline bağlı değildir.

Seçenekler:
- A: Learning prompt akışı durdursun.
- B: Normal şekilde sonraki faturaya geçsin, prompt başka UI'da beklesin.
- C: Sadece belirli prompt tipleri durdursun.

## Adım 9 — Utility precedent

`office_utility_precedent` ayrı değerlendirilecek.

Sorular:
- Cross-client bilgi yalnız öneri mi olmalı?
- Otomatik hesap taşımalı mı?
- Sadece aynı service_profile için mi?
- Harness'ın parçası mı olmalı, ayrı learning prompt mu?

## Adım 10 — `2db12ed` test sözleşmeleri

Üç ayrı parça olarak ele alınacak.

### 10A — Semantic rule backend testleri

Şu davranışı sabitliyor:

```text
binding_mode = semantic_role
semantic_intent = kargo_gideri
semantic_role = expense
account_code = ""
```

Semantic model korunacaksa bu test fikri korunmalı. Ancak rule execution mimarisi değişirse testlerin kapsamı yeniden yazılabilir.

### 10B — Learning UI mapping testi

Frontend'e şu alanların kaybolmadan geçmesini sabitliyor:

```text
status
promptKey
evidenceDocuments
utilityPrecedent
suggestedNote
```

Evidence UI korunacaksa ilgili testler de korunmalı.

### 10C — Upload testi

Learning ile ilgisizdir ve korunmalıdır:

```text
.pdf / .html / .htm / .xml
Dosya seçilince otomatik upload
ZIP yok
```

## Adım 11 — Temizleme planı

Yukarıdaki adımlar tek tek karara bağlandıktan sonra:

1. Korunacak davranışların listesi çıkarılacak.
2. Geri alınacak `4d9f0b7` parçaları hunk/file bazında belirlenecek.
3. Yeniden yazılacak Harness/semantic entegrasyonu tasarlanacak.
4. Önce testler yeni canonical mimariyi tarif edecek.
5. Sonra minimal runtime değişikliği yapılacak.
6. Production `829c468` ile A/B test yapılacak.
7. Kullanıcı onayı olmadan deploy yapılmayacak.

---

# Çalışma kuralı

Bu inceleme boyunca:

- Bir adım bitmeden sonraki adım konuşulmayacak.
- Test sırasında bulunan bir davranış problemi kullanıcı onayı olmadan runtime patch'e çevrilmeyecek.
- Her davranış değişikliği önce açıkça anlatılacak.
- Production'a deploy ancak açık kullanıcı talebiyle yapılacak.
