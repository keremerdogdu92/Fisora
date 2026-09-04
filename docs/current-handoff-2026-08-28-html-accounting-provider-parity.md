# Fisora HTML Accounting / Provider / HTML-PDF Parity Handoff — 2026-08-28

Bu doküman 2026-08-28 oturumunun source-of-truth handoff'udur.
Yeni konuşmada önce bu dosya okunmalı; eski benchmark sonuçları bu dosyadaki metodoloji notlarıyla birlikte yorumlanmalıdır.

## 1. Kesin mimari sınır

Kullanıcı kararı: muhasebe kararına dokunan deterministic guard, correction, repair, reconciliation, fallback veya routing kuralı **önceden konuşulmadan yazılmayacak**.
PDF tarafında da kaynak okuma/muhasebe davranışına yeni deterministic muhasebe katmanı eklenmeyecek.
HTML için frozen reader/source evidence teknik kaynak katmanı olarak kalabilir; fakat muhasebe anlamı Python kurallarıyla yeniden üretilmeyecek.

Bugün kısa süreli eklenen posting-basis muhasebe guard'ı geri alındı.
Kod araması temiz: `posting_basis_integrity`, `counterparty_posting_basis_mismatch`, `source_posting_basis_mismatch` için backend/app altında 0 eşleşme.
Ortak PDF Planner/Final promptlarına bu deney sırasında eklenen v4-v6 muhasebe yönlendirmeleri de geri alındı; PDF ortak davranışı HEAD çizgisinde tutuldu.

Prensip:
- source/security invariant: enforce edilebilir,
- technical/schema invariant: enforce edilebilir,
- accounting observation: ölçülür/gösterilir; otomatik muhasebe kararı veya düzeltme üretmez.

## 2. Repo / release durumu

Repo: `C:\Users\kerem\Documents\Fisero`
Branch: `main`
Bu handoff yazılırken HEAD: `1fdd827`.
Çalışma ağacı dirty; HTML entegrasyonu ve deney dosyaları henüz commit/push/deploy edilmedi.
Migration 014 production DB'ye uygulanmadı.
## 3. Frozen HTML Reader ve entegrasyon özeti

Frozen reader release: `html-source-reader-v1.0.0-20260827`, snapshot contract `DocumentSourceSnapshot 1.0.0`.
Eski corpus: 1327/1327 parse; 123 exact / 95 generalized structural family; audit 130 PASS / 3 intentional REVIEW / 0 FAIL; table provenance 119/119; regression 59/59; security 7/7; edge 10/10; robustness 8/8; mutation 500/500; public API 7/7; freeze verify 20/20.
Genuine blind holdout: 347/347 parse, 343 PASS-equivalent / 4 intentional fragmented-energy REVIEW / 0 FAIL; 347/347 robustness parity; 1735 metamorphic vaka, strict 1734/1735.

Fisero'ya controlled integration slice eklendi ancak deploy edilmedi:
`HTML upload -> html_source_invoice -> frozen reader -> immutable DocumentSourceSnapshot -> source rows/UI`.
Accountant UI'da üçlü comparison hazırlandı: original HTML appearance / frozen snapshot / Fisora sourceReviewRows.
Original HTML preview isolated/sandboxed; normal React path raw HTML'yi `dangerouslySetInnerHTML` ile render etmiyor.

HTML accounting bridge deneysel olarak hazırlandı:
`frozen snapshot + semantic evidence -> Planner -> Final Accountant`.
Bu bridge rollout flag arkasında tutuldu; production'a açılmadı.
HTML semantic evidence script/iframe çalıştırmıyor; source hash ve provenance taşıyor.

Son full regression (guard tartışmasından önce): backend **1124 passed / 34 skipped / 0 failed**; frontend **178/178 PASS**; Next production build ve TypeScript PASS.
Guard/prompt rollback sonrası focused HTML/accounting testleri **12/12 PASS**.
Rollback sonrasında full 1124-suite tekrar koşturulmadı; yeni mesajda gerekirse final release gate öncesi yeniden çalıştırılmalı.

Stale/untracked not: repo kökünde `_html_integration_patch.py` hâlâ var; daha önce oluşturulmuş, çalıştırılmamalı ve commit öncesi kaldırılmalı.
`backend/tmp-html-ai-smoke/` deney artefaktları untracked ve production runtime parçası değildir.
## 4. İlk gerçek HTML -> muhasebe AI smoke

Gerçek production taxpayer/chart ile ilk anlamlı vaka: Arif San + gerçek TTNET alış HTML'i `8590491872_A162026005401322.html`.
Production chart'ta `329.03 TTNET ANONIM SIRKETI` mevcut.
Frozen reader: 6 satır / 4 kolon / confidence 0.99 / 0 warning.
Kaynak: fatura no `2026067242577`, tarih `30-06-2026`, ödenecek 1.144,00 TL, KDV 177,54 TL.

XKIRO Strong Final sonucu:
- 770.02.002 Haberleşme Giderleri: 887,69 borç
- 191.01.020: 177,54 borç
- 795 Vergi Resim ve Harçlar: 78,77 borç
- cari: 1.144,00 alacak
- 6/6 source row coverage, 0 warning
- Final latency yaklaşık 71-80 saniye (farklı tekrarlar).

Bu sonuç source ile güçlü şekilde uyumlu göründü; fakat accountant-approved ground truth değildir.
Bu smoke sırasında eklenen posting-basis deterministic warning/guard daha sonra kullanıcı kararıyla tamamen geri alındı.

## 5. A/B/C mimari deneyleri

A = strong accountant tek başına (XKIRO DeepSeek V4).
B = Gemini fast accountant -> bağımsız critic -> gerekirse strong from scratch.
C = Gemini + XKIRO bağımsız accountant -> bağımsız judge; judge fiş üretmez, yalnız A/B/neither seçer.
Self-repair/reconciliation deneyde kullanılmadı; strong escalation sıfırdan çalıştı.

5 gerçek Arif alış vakası: Aventek, TTNET, Superonline, CK Elektrik, Yeni Işık.
Planner süreleri yaklaşık 1.4-1.6 sn.
Gemini Final ortalama yaklaşık 3.05 sn; XKIRO Final ortalama yaklaşık 44.35 sn, medyan yaklaşık 47.31 sn.
5-vaka gözlemi:
- Aventek: Gemini ve XKIRO aynı `153.01 + 191.01.020`, 26.000 sonucu.
- TTNET: Gemini rakamları doğru ayırdı ancak ÖİV'yi `770.02.009 Damga Vergisi Giderleri`ne koydu; XKIRO `795` kullandı.
- Superonline: Gemini parçalı hesaplar/ÖİV `770.02.009`; XKIRO `770.02.002 + 191.01.020 + 795`, toplam 711.
- CK Elektrik: Gemini `Vergi ve Fonlar 74,32` subtotalını tekrar sayıp 823,16 üretti; XKIRO alt bileşenleri ayırıp 754,59 üretti.
- Yeni Işık: Gemini ve XKIRO aynı `153.01 + 191.01.020`, 24.960 sonucu.

Bu küçük sette XKIRO 5/5 source ile güçlü uyum gösterdi; Gemini basit stoklarda iyi, telekom/enerji edge-case'lerinde sapma gösterdi.
Bu skor müşavir ground truth'u değildir; source audit gözlemidir.

Groq critic 5-vakada routing açısından güvenilir çıkmadı:
- Aventek ACCEPT: makul,
- TTNET ACCEPT: semantik olarak problemli Gemini taslağını kaçırdı,
- Superonline RETRY: problemi yakaladı,
- CK Elektrik ACCEPT: double-count'u kaçırdı,
- Yeni Işık ACCEPT: makul.
Kabaca 3/5 doğru routing gözlemi.

Groq judge:
- TTNET'te sıra ters çevrilince de XKIRO taslağını seçti (position-bias görülmedi),
- Superonline ve CK Elektrik zor vakalarında Gemini taslağını seçerek problemli sonucu onayladı.
Sonuç: critic/judge şu haliyle muhasebe otoritesi veya güvenlik katmanı kabul edilmemeli.

A/B/C hiçbir production routing'e eklenmedi.
## 6. Groq full accountant / free-tier gözlemleri

Groq standard full-accountant request'leri 413 verdi.
Kök neden context window değil, mevcut free-tier TPM limiti: yaklaşık 8.000 token; full chart + source + schema istekleri yaklaşık 12.8K tokena çıkıyordu.
Hesap planından hesap elemeden, token-verimli transport/reasoning ayarıyla model kabiliyeti ayrıca ölçüldü.

Groq GPT-OSS-20B:
- çok hızlı (~1-3 sn),
- Aventek'te 153 yerine 150 seçti,
- TTNET'te 622 / 611 / 391 output KDV / damga vergisi gibi ciddi alış-satış semantik hataları yaptı,
- CK Elektrik'te de zayıf sonuç verdi.

Groq GPT-OSS-120B:
- 20B'den daha iyi muhasebe anlamı,
- Aventek'te ana stok hesabını boş bıraktı,
- TTNET'te net/KDV/ÖİV tutarlarını doğru ayırdı fakat ana gider hesabını boş bıraktı ve ÖİV için 193 kullandı,
- CK Elektrik'te temiz sonuç vermedi.
Groq full accountant şu an XKIRO/Gemini seviyesinde aday sayılmıyor.

Cloudflare free denemeleri:
- Nemotron-3-120B Aventek: ~19.6 sn, `153.01 + 191`, temiz.
- Nemotron TTNET: output budget reasoning'de tükendi; final JSON yok.
- GLM-4.7-Flash: free capacity timeout.

Cerebras mevcut hesap: 402 / kredi tükenmiş.
NVIDIA NIM: güncel denemelerde uzun timeout; düşük öncelik.
GoRouter/Opus env hazırdı fakat gerçek çağrı 403 Forbidden; kalite sonucu alınmadı.
## 7. B.AI ve diğer yeni ücretsiz adaylar

B.AI DeepSeek V4 Flash:
- Aventek non-thinking: yaklaşık 43.4 sn, `153.01 + 191`, temiz.
- TTNET non-thinking: yaklaşık 6.65 sn fakat 1.144 toplamı gider alıp KDV/ÖİV'yi ayrıca ekleyerek double-count yaptı.
- low/high thinking: yaklaşık 56-58 sn ve 6.000 reasoning token; final JSON üretmeden budget bitti.
Bu nedenle B.AI V4 şu haliyle XKIRO alternatifi olarak kabul edilmedi.

B.AI MiMo-V2.5:
- Aventek ~14.1 sn,
- 153 Ticari Mallar yerine 760.03.003 seçti; ilk temel vakada elendi.

B.AI GLM-5.3-Flash:
- deneme sırasında 429 `too many pending requests`; model kalitesi ölçülemedi.
B.AI Qwen3.8-Flash resmi free/promotional aday olarak not edildi ancak bu oturumda full-accountant sonucu alınmadı.

OpenRouter free: benchmark için kullanılabilir ancak çıplak free hesap limiti üretim kapasitesi için düşük; bu oturumda yeni Final benchmarkı yapılmadı.

## 8. Provider secret/env düzeni

Yeni Grokified ve DeepSeek direct keyleri ayrı benchmark env'den `deploy/production.env` içine taşındı.
Ayrı `deploy/.env.provider-benchmark` silindi.
Benchmark harness'leri `deploy/production.env` okuyor.
Bu dosya Git ignore altında; key değerleri hiçbir log/dokümana yazılmadı.
Provider env'in tek dosyada olması **routing'i otomatik açmıyor**; yalnız secret/config kaynağını birleştiriyor.
## 9. Grokified / Grok 4.6 durumu

Grokified config ve key okundu; benchmark endpoint/model hazırlandı.
Aventek ve TTNET full accountant çağrıları yaklaşık 1.1 sn'de 503 döndü.
Daha sonra `/models` ve minimal `Reply exactly OK` çağrısı da 503 döndü.
Hata: `upstream_overloaded` / upstream API temporarily overloaded.
Bu nedenle Grok 4.6 için **kalite sonucu yok**; bugünkü durum provider availability problemidir, model başarısızlığı değildir.
Yeni mesajda servis yeniden erişilebilir olduğunda aynı production-schema accountant promptuyla tekrar denenebilir.

## 10. DeepSeek direct API — preliminary sonuçlar

DeepSeek direct key `platform.deepseek.com` üzerinden çalışıyor; hesapta test için ücretli bakiye var.
Denenen modeller: `deepseek-v4-flash`, `deepseek-v4-pro`.
Non-thinking ve thinking modları ayrı ölçüldü.

Önemli metodoloji notu:
İlk `benchmark_direct_new_providers.py` deneyleri ACCOUNTANT_INSTRUCTIONS + kısaltılmış shape ile yapıldı; production XKIRO provider'ın tam `ACCOUNTANT_SCHEMA` paketlemesiyle birebir değildi.
Bu nedenle ilk DeepSeek-vs-XKIRO kalite kıyası **preliminary** kabul edilmeli.
HTML/PDF parity harness'i daha sonra production generic Final Accountant prompt formatına düzeltildi: aynı system instructions, tam ACCOUNTANT_SCHEMA, aynı `temperature=0.2`, `top_p=1`; DeepSeek tarafında yalnız thinking mode seçimi ekstra.
Yeni mesajdaki ilk görev doğrudan DeepSeek-vs-XKIRO karşılaştırmasını bu birebir prompt/request sözleşmesiyle yeniden kurmaktır.

Preliminary direct DeepSeek sonuçları yine latency/kapasite sinyali olarak değerlidir:
- V4 Flash non-thinking Aventek: 4.24 sn, `153.01 + 191`, 26.000.
- V4 Flash non-thinking TTNET: 6.79 sn, 887.69 + 177.54 + 78.77 = 1.144; ÖİV'yi 795 yerine 770 haberleşme giderine gömdü.
- Flash remaining: Superonline 7.58 sn, CK Elektrik 4.98 sn, Yeni Işık 5.33 sn.
- Superonline'da basis 711.00 iken counterparty 711.02; CK'de 0.35 güncel yuvarlama atlanıp 754.24 üretildi; Yeni Işık temiz 153+191.
V4 Pro non-thinking preliminary:
- TTNET 9.53 sn; rakamlar doğru, ÖİV yine 770 içine.
- Superonline 13.65 sn; ÖİV için 795 seçti, fakat küçük satır/toplam farkı kaldı.
- CK Elektrik 7.20 sn; 679.92 + 5.75 + 68.57 = 754.24; 0.35 güncel yuvarlamayı atladı.

Thinking modları:
- Flash thinking Aventek 32.65 sn temiz.
- Flash thinking TTNET 107.4 sn, 12K reasoning token, `finish_reason=length`, final JSON yok.
- Pro thinking Aventek 70.1 sn temiz.
- Pro thinking TTNET 180.5 sn ve güçlü XKIRO-benzeri `770 + 191 + 795`, 1.144 sonucu.
- Pro thinking CK Elektrik 281.4 sn, 12K reasoning token, `finish_reason=length`, final JSON yok.

Sonuç: DeepSeek direct non-thinking çok hızlı ve ciddi aday; thinking zor faturada bazen daha güçlü ama 2-5 dakika ve no-output riski nedeniyle genel çözüm olarak kabul edilmedi.

## 11. HTML ↔ PDF parity testinin veri seti

Desktop'ta aynı invoice stem için gerçek HTML + gerçek PDF çiftleri bulundu.
Rana İşitme dataset'i özellikle uygun:
- gerçek source PDF'ler,
- aynı invoice stem'li HTML'ler,
- 916 hesaplı gerçek hesap planı,
- bazı invoice'larda HTML'den render edilmiş generated-PDF de mevcut.

Rana İşitme alışlarında 26 ortak HTML/PDF invoice stem bulundu; 12 farklı supplier temsil edilebildi.
Parity testinde DeepSeek V4 Flash non-thinking Final kullanıldı.
PDF tarafında native PDF Reader + Planner; HTML tarafında frozen HTML reader/evidence + Planner kullanıldı.
Controlled testlerde source-text ve Planner planı çaprazlandı; böylece Reader/Planner/Final etkisi ayrılmaya çalışıldı.

Kritik metodoloji düzeltmesi:
İlk parity pilotunda DeepSeek direct promptu production schema ile birebir değildi; bu ilk sonuçlar geçersiz/pilot sayıldı.
Harness sonradan production generic Final prompt formatına geçirildi ve 3 controlled + 12 natural pair tekrar koşturuldu.
## 12. Düzeltilmiş 3 controlled HTML/PDF vaka

### 12.1 RMA2026000000169 — Ranamed
HTML reader 26 row, PDF reader 26 row.
HTML/PDF Planner dict'i birebir aynı değil; HTML'de %0 ve %20 tax component, PDF'de %20 component var.
Buna rağmen dört kombinasyonun tamamı aynı ekonomik sonucu verdi:
- natural HTML + HTML plan,
- natural PDF + PDF plan,
- HTML text + PDF plan,
- PDF text + HTML plan.
Hepsi: `153 = 259,283.35`, `191 = 2,616.67`, cari `261,900.02`.
Bu vaka format-parity açısından güçlü PASS gözlemidir.

### 12.2 AVA2026000285029 — Avansas
HTML reader 8, PDF reader 8; posting basis iki tarafta 4,638.30.
Economic split 3,954.23 net + 684.07 VAT civarında korunuyor.
Ancak account-code/line-granularity run-to-run ve source representation'a göre oynadı: boş code, 150, 153 gibi seçimler görüldü.
Bu durum yalnız format farkı değildir; DeepSeek Flash non-thinking stability ayrıca ölçülmelidir.

### 12.3 AS02026001117415 — Enerjisa
HTML reader 4 row, PDF reader 6 row; natural basis iki tarafta 2,316.16.
PDF natural Final `740 1879.68 + 770 50.45 + 191 386.03` üretti.
HTML natural Final bir turda operating lines'ı boş bırakıp yanlış biçimde chart'ın verilmediğini iddia etti.
`PDF text + HTML plan` doğru `740+770+191` sonucuna döndü.
`HTML text + PDF plan` ise vergi satırını atlayıp 2,265.71 basis üretebildi.
Bu vaka HTML source representation'ın Final attention/reasoning davranışını etkileyebildiğine dair güçlü gözlemdir.
## 13. Düzeltilmiş 12-supplier natural HTML/PDF parity sonucu

12 gerçek eş fatura, 12 farklı supplier; aynı Rana İşitme chart ve DeepSeek V4 Flash non-thinking Final.
Son JSON: `backend/tmp-html-ai-smoke/html_pdf_deepseek_12_result.json`.

Özet:
- Reader row count eşit: **10/12**.
- Planner full-dict birebir eşit: **3/12**. Bu metrik çok katıdır; küçük party/tax wording farkını da mismatch sayar.
- Posting basis numerik eşit: **10/12**.
- Counterparty debit/credit numerik eşit: **9/12**.
- Raw account-code listesi birebir eşit: **7/12**.
- Raw operating amount listesi birebir eşit: **8/12**.

Latency:
- HTML Planner avg ~1.48 sn, median ~1.50 sn.
- PDF Reader avg ~5.71 sn, median ~5.68 sn.
- PDF Planner median ~1.26 sn; bir 50.2 sn outlier nedeniyle avg ~5.36 sn.
- DeepSeek Final HTML avg ~4.02 sn, median ~4.03 sn.
- DeepSeek Final PDF avg ~4.75 sn, median ~4.39 sn.

Posting-basis farkı çıkan iki vaka:
1. `1790617537_BEF2026002486161`: HTML 377.32, PDF 517.32.
2. `8590380323_GB32026007781128`: HTML 293.75, PDF 287.50.

Bunlar otomatik FAIL/guard olarak yorumlanmamalı; source inspection ile katman teşhisi yapılmalı.
## 14. İki posting-basis farkının source inspection sonucu

### 14.1 CK Boğaziçi `BEF2026002486161`
Gerçek PDF doğrudan okundu.
PDF üzerinde:
- enerji bedeli 283.49,
- kesme-bağlama bedeli 140.00,
- elektrik/havagazı vergisi 7.61,
- KDV 86.22,
- fatura tutarı 517.32.

HTML semantic evidence ise enerji, vergi/fon ve KDV bilgilerini taşıyor fakat 140.00 kesme-bağlama bedelini Final'a yeterli kanıt olarak taşımıyor.
Bu nedenle HTML Final 377.32, PDF Final 517.32 üretti.
Bu vaka **HTML source/evidence coverage farkı**; muhasebe guard'ı ile kapatılmamalı. Sonraki analizde frozen snapshot + semantic evidence + rendered accountant text adım adım karşılaştırılmalı.

### 14.2 TT Mobil `GB32026007781128`
Gerçek PDF doğrudan okundu.
Kaynak PDF açıkça `Ödenecek Tutar = 293.75 TL` ve `ÖDENECEK TOPLAM TUTAR = 293.75 TL` diyor.
HTML semantic evidence da 293.75 toplamını taşıyor.
Düzeltilmiş production-schema parity turunda HTML Final **293.75** ile kaynağı izledi; PDF Final **287.50** üretti.
Bu vaka source eksikliğinden çok **PDF source representation / Final reasoning** farkına işaret ediyor.

Bu iki örnek birlikte önemli: HTML her zaman daha kötü veya PDF her zaman daha iyi değil.
Format etkisini Reader -> rendered source -> Planner -> Final aşamalarında ayrı ölçmek gerekiyor.

## 15. Run-to-run stability açık sorunu

Aynı invoice/model aynı genel ayarlarla farklı tekrarlar arasında account-code veya operating-line yapısı değiştirebildi.
Özellikle Avansas'ta boş account code / 150 / 153 gibi farklı seçimler görüldü.
Bu yüzden HTML-PDF farkına model stochasticity karışıyor olabilir.
Henüz aynı exact request body'yi 3-5 kez tekrar eden kontrollü stability matrisi yapılmadı.
Yeni mesajda bu test zorunlu.
## 16. XKIRO vs DeepSeek direct — bilinen request/config farkları

Mevcut product XKIRO provider:
- endpoint: `https://api.xkiro.com/v1/chat/completions`
- model: `deepseek/deepseek-v4-flash`
- timeout: `120` saniye
- max_tokens: `4096`
- class: `ChatCompletionsAccountingProvider`
- request: full ACCOUNTANT_SCHEMA user message içinde, `response_format=json_object`, `temperature=0.2`, `top_p=1`, non-stream.

DeepSeek direct benchmark/parity:
- endpoint: `https://api.deepseek.com/chat/completions`
- model: `deepseek-v4-flash` veya `deepseek-v4-pro`
- parity harness max_tokens: `6000`; bazı ilk provider deneylerinde 12K output bütçesi kullanıldı.
- `thinking={'type':'disabled'}` explicit gönderildi (non-thinking deneyleri).
- parity harness production ACCOUNTANT_SCHEMA paketlemesine sonradan eşitlendi.

Kritik açık soru: XKIRO request'inde `thinking` alanı gönderilmiyor. XKIRO proxy'nin DeepSeek V4 için default reasoning/thinking davranışı, token budget/caching/normalization ve upstream model parametreleri henüz bilinmiyor.
Bu nedenle mevcut süre/kalite farkını yalnız "aynı model farklı provider" diye yorumlamak için erken.

Yeni mesajda ilk deney: XKIRO ve DeepSeek direct için **aynı invoice_source_text + aynı semantic_plan + aynı chart_text + aynı ACCOUNTANT_INSTRUCTIONS/SCHEMA + aynı temperature/top_p + aynı 4096 max_tokens + aynı timeout + repair yok** koşulu kurulmalı.
Mümkünse iki provider da aynı `ChatCompletionsAccountingProvider` request-builder yolundan geçirilerek yalnız endpoint/model/key ve zorunlu provider-specific thinking farkı değişmeli.
Raw request payload hash/size ve response usage/finish_reason/reasoning bilgisi secret göstermeden kaydedilmeli.
## 17. Yeni mesajda uygulanacak deney sırası

### P0 — XKIRO vs DeepSeek direct gerçek apples-to-apples
1. Önce bu handoff ve `docs/next-execution-backlog-20260825.md` oku.
2. Product kodunu değiştirme; guard/routing/repair ekleme.
3. XKIRO ve direct DeepSeek request-builder/headers/body farkını koddan ve secret-safe raw request metadata'dan çıkar.
4. Aynı exact prepared Final input'u disk checkpoint olarak dondur: source_text, semantic_plan, chart_text, client, expected_direction, schema/instructions digest.
5. XKIRO V4 Flash ve direct V4 Flash'a aynı max_tokens=4096, temp=0.2, top_p=1, timeout=120 ile gönder.
6. XKIRO'nun implicit thinking davranışı belirsizse direct tarafta hem XKIRO'ya en yakın default/omitted-thinking hem explicit disabled varyantını ayrı isimle ölç; birbirine karıştırma.
7. İlk set: Aventek, TTNET, Superonline, CK Elektrik, Yeni Işık.
8. Her exact input/provider için en az 3 tekrar yap; latency, finish_reason, usage/reasoning, output stability ve account/tutar seçimini kaydet.
9. İlk beşten sonra ancak anlamlı adayda 10-20 belgeye büyüt.

### P1 — HTML vs PDF step-by-step parity
Her eş invoice için aşağıdaki katmanları ayrı artifact/diff olarak kaydet:
A. original source facts (PDF görsel/metin ve HTML görünür/machine data),
B. Reader output/snapshot,
C. rendered planner source text,
D. Planner semantic plan,
E. rendered accountant source text,
F. aynı frozen plan ile Final output,
G. natural pipeline Final output.

Fark ilk hangi adımda oluşuyorsa orada sınıflandır; sonraki katmanda deterministic muhasebe düzeltmesi yazma.
Özellikle `BEF2026002486161` ve `GB32026007781128` ilk iki teşhis vakasıdır.
12 mevcut çiftin tamamı yeniden bu step-by-step formatta incelenebilir; gerekirse 26 ortak çifte genişlet.
### P2 — Stability / stochasticity
1. Aynı exact request body'yi HTML ve PDF için ayrı ayrı 3-5 kez tekrarla.
2. İlk tur production ayarı `temperature=0.2` ile olsun.
3. Sonuç varyansı ölçüldükten sonra ancak deney olarak temp=0 destekleniyorsa ayrı bir stability karşılaştırması yapılabilir; product ayarı değiştirilmez.
4. Account-code, posting basis, operating amounts, counterparty amount ve warning yapısındaki varyansı raporla.
5. Format farkı ile stochastic model farkını aynı metrikte birleştirme.

### P3 — Provider/format sonuçlarını müşavir ground truth'undan ayır
Mevcut testlerde "doğru görünüyor" source inspection anlamındadır; resmi accountant reference değildir.
Muhasebe semantiği tartışmalı vakalarda sonuçlar observation olarak tutulmalı.
Hiçbir model sonucu yalnız dengeli olduğu, critic/judge kabul ettiği veya diğer modelle aynı olduğu için ground truth sayılmamalı.

## 18. Evidence / experiment dosyaları

Ana deney klasörü: `backend/tmp-html-ai-smoke/` (untracked).
Önemli artefaktlar:
- `matrix_5_models_result.json` — Gemini/XKIRO + critic 5-vaka matrisi.
- `abc_ttnet_checkpoint_complete.json` — TTNET A/B/C ayrıntılı checkpoint.
- `abc_1050567070_avt2026000000248_checkpoint.json` — Aventek A/B checkpoint.
- `direct_new_providers_result.json` — Grokified + direct DeepSeek ilk iki vaka (preliminary prompt packaging).
- `direct_flash_remaining_result.json` — direct Flash remaining 3 Arif vaka.
- `direct_pro_nonthinking_ttnet.json`, `direct_pro_nonthinking_hard2.json`, `direct_pro_thinking_ck.json`.
- `html_pdf_deepseek_result.json` — production-schema 3 controlled HTML/PDF pair.
- `html_pdf_deepseek_12_result.json` — production-schema 12-supplier natural parity.
- `compare_html_pdf_deepseek.py`, `compare_html_pdf_deepseek_12.py` — parity harness'leri.

Bu artefaktlar commit edilmedi; yeni mesajda silmeden önce gerekli özet/checkpoint korunmalı.
## 19. Bu oturum sonunda kesin durum

- Yeni muhasebe guard yok; geri alınan posting-basis guard product kodunda bulunmuyor.
- A/B/C routing product'a yazılmadı.
- DeepSeek direct/Grokified provider'ları production accounting chain'e eklenmedi.
- Provider key/config değerleri ignored `deploy/production.env` içinde tek yerde tutuluyor.
- HTML integration kodu local dirty worktree'de; commit/push/deploy yok.
- Migration 014 uygulanmadı.
- PDF ortak muhasebe prompt davranışı deneysel v4-v6 değişikliklerinden geri döndürüldü.
- Grokified şu an 503 upstream overloaded; kalite kararı yok.
- XKIRO mevcut source-audit referans lider; direct DeepSeek hızlı ve umut verici fakat apples-to-apples Final benchmarkı henüz tamamlanmadı.
- HTML/PDF parity'de gerçek farklar var; fakat farkın Reader/evidence, Planner, Final representation ve model stochasticity katmanları ayrılmadan çözüm yazılmamalı.

## 20. Değişiklik yasağı / karar kapısı

Yeni mesajda test ve read-only analiz serbesttir.
Aşağıdakiler için kullanıcıya önce sonuç/öneri göster ve açık onay al:
- deterministic muhasebe guard,
- automatic retry/correction/self-repair değişikliği,
- reconciliation/fallback,
- provider routing/escalation,
- PDF kaynak okuma davranışına müdahale,
- HTML source evidence'ı muhasebe varsayımıyla dönüştürme,
- production deploy/migration/authoritative accounting enable.

Öncelik basitlik ve AI muhasebe otoritesini deterministic ikinci muhasebe motoruna dönüştürmemektir.
## 21. Yeni mesaj bootstrap özeti

Yeni oturumda Work PC üzerinde Remote Desktop Commander ile devam et.
Repo: `C:\Users\kerem\Documents\Fisero`.
İlk iş bu dosyayı source-of-truth olarak oku:
`docs\current-handoff-2026-08-28-html-accounting-provider-parity.md`.
Gerektiğinde `docs\next-execution-backlog-20260825.md` ve `docs\current-handoff.md` kullan.

Önce kod değiştirmeden mevcut deney/checkpointleri doğrula.
Muhasebe deterministic guard/correction/repair/reconciliation/fallback/routing yazma; böyle bir öneri çıkarsa önce kullanıcıyla konuş.
PDF source/accounting davranışını değiştirme.

İlk çalışma:
1. XKIRO DeepSeek V4 Flash ile DeepSeek direct V4 Flash'ın request/config farklarını çıkar.
2. Aynı exact Final Accountant inputunu dondur ve iki provider'a birebir aynı schema/prompt/temp/top_p/max_tokens/timeout ile gönder.
3. XKIRO implicit thinking vs DeepSeek thinking-disabled/default farkını ayrı deney olarak ölç.
4. 5 ayırıcı faturada her provider/input için en az 3 tekrar yap; latency ve output stability raporla.
5. Sonra HTML↔PDF eş faturaları Reader -> rendered source -> Planner -> Final olarak adım adım diff et.
6. Öncelikli parity vakaları: `BEF2026002486161`, `GB32026007781128`, `RMA2026000000169`, `AVA2026000285029`, `AS02026001117415`.
7. Format farkı, model stochasticity ve provider farkını ayrı eksenler olarak raporla.
8. Test sonucuna göre mimari öneri yap ama kullanıcı onayı olmadan production değişikliği/deploy/migration yapma.
