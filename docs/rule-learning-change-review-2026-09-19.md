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

## Adım 3 — Semantic rule'u kim uygulamalı?

İki yol ayrı ayrı değerlendirilecek.

### Yol A — `4d9f0b7` direct semantic constraint

```text
Aktif semantic rule
    ↓
Deterministik eşleşme
    ↓
AI context / aday grup etkisi
    ↓
Normal muhasebe AI
```

### Yol B — AI Rule Harness

```text
Aktif semantic rule
    ↓
Harness rule search
    ↓
AI applicability kararı
    ↓
Kural sonucu / önerisi
```

Kritik mevcut sorun: Harness `_usable_rule()` bugün `account_code` dolu olmasını şart koşuyor. Bu nedenle `account_code=""` olan semantic-role kuralları Harness şu anda **görmüyor**.

Bu adım sonunda tek bir canonical rule execution yolu seçilecek.

## Adım 4 — Harness semantic-role rule destekleyecekse nasıl?

Eğer Adım 3'te Harness seçilirse:

- `_usable_rule()` semantic rule kabul edecek şekilde yeniden tasarlanacak.
- `account_code` zorunluluğu fixed-account kurallara özel hale gelecek.
- Harness semantic intent / semantic role / scope / counterparty / direction / line-match bilgilerini değerlendirecek.
- Semantic kuralın sonucu “doğrudan hesap” olmak zorunda olmayacak.
- Gerekirse Harness sonucu normal muhasebe AI'sına constraint olarak aktarılacak; bunun hangi aşamada olacağı ayrıca tasarlanacak.

Bu yapılmadan direct semantic yolu sökülmeyecek; aksi halde semantic kurallar kaydedilir fakat kullanılmaz hale gelebilir.

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
