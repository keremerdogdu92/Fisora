# Accountant Field-Validation Questions

Status: Active supporting register

## Purpose

This file tracks decisions whose regulatory/default direction is documented but
whose real office treatment must be confirmed with the pilot accountant before
unattended automation. Answers are dated, attributed, and promoted into the
canonical decision register, PRD, architecture, and acceptance tests where
applicable. An unanswered item does not stop Fisero from preparing its strongest
reviewable draft unless the canonical decision register explicitly says so.

## Q-001 - Foreign-currency invoice exchange rate

Status: Awaiting pilot-accountant answer

Decision affected: `00-canonical-decision-register.md` - Foreign-currency invoice
and exchange-rate policy

### Primary question to ask

> Dövizli alış ve satış faturalarını pratikte TL muhasebe kaydına alırken hangi
> kuru kullanıyorsunuz? Faturadaki kur ile vergiyi doğuran olay/fatura tarihindeki
> TCMB döviz alış kuru farklıysa hangisini esas alıyor, farkı nasıl işliyorsunuz?

### Follow-up points if needed

1. Fatura tarihi ile teslim/hizmet veya vergiyi doğuran olay tarihi farklıysa
   hangi tarihi kullanıyorsunuz?
2. Faturada hem döviz tutarı hem TL matrah/KDV hem de belge kuru yazıyorsa hangi
   değerleri muhasebe ve KDV için esas alıyorsunuz?
3. Hafta sonu/resmi tatil tarihli faturada hangi günün kurunu kullanıyorsunuz?
4. TCMB'nin ilan etmediği bir para birimi veya yabancı satıcı/ithalat faturasında
   kur kaynağınız ve kullandığınız destekleyici belge nedir?
5. Maddi kur farkında fişi doğrudan review'e mi bırakıyorsunuz; ofisinizde kabul
   edilen bir tolerans veya mükellefe özel politika var mı?
6. Ödeme/tahsilat kur farkını ilk fatura fişinden ayrı mı kaydediyorsunuz?

### Current provisional default

- Preserve original currency, document rate, declared TRY amounts, and applied
  accounting rate with provenance.
- For ordinary taxable transactions, use the TCMB foreign-exchange buying rate
  applicable to the taxable-event date unless a validated scenario/policy
  requires otherwise.
- Show a material unexplained document-rate difference in focused review while
  still preparing the strongest complete balanced journal.
- Keep settlement exchange differences and period-end valuation separate from
  initial invoice recognition.
- Do not enable unattended automation for affected foreign-currency invoices
  until the accountant confirms the practical policy.

### Answer record

- Answered by:
- Answered at:
- Office/client scope:
- Confirmed treatment:
- Exceptions/tolerance:
- Evidence/example invoice:
- Canonical decision update:

## Q-002 - Price, maturity, and exchange-difference invoice accounts

Status: Awaiting pilot-accountant answer

Decision affected: `00-canonical-decision-register.md` - Price-difference,
maturity-difference, and exchange-difference invoices

### Primary question to ask

> Fiyat farkı, vade farkı ve kur farkı faturalarını alış ve satış yönünde hangi
> hesaplara kaydediyorsunuz? Asıl faturanın hesabını mı düzeltiyorsunuz, yoksa
> kullandığınız ayrı fark hesapları var mı?

### Follow-up points if needed

1. Alış ve satış yönünde kullandığınız hesap/açıklama yapıları farklı mı?
2. Fiyat farkında mal stokta duruyorsa ve satılmışsa uygulama değişiyor mu?
3. Kur farkında lehe/aleyhe fark ve KDV kaydını nasıl ayırıyorsunuz?
4. Vade farkını ilgili mal/hizmet hesabına mı, ayrı finansman hesabına mı
   kaydediyorsunuz?
5. Tek fark faturası birden fazla asıl faturaya bağlıysa nasıl dağıtıyorsunuz?
6. Asıl fatura sistemde yoksa pratikte hangi bilgiyle hesap seçiyorsunuz?
7. Bu uygulamalardan hangileri ofis geneli, hangileri mükellefe özeldir?

### Current provisional default

- Treat all three as adjustment semantics rather than generic services.
- Link original invoices/periods where evidence permits, without requiring the
  link to prepare a complete journal.
- Do not overwrite the original invoice for later exchange differences.
- Use focused review until the accountant confirms account policy; then promote
  consistent treatment through the normal scoped-rule approval flow.

### Answer record

- Answered by:
- Answered at:
- Office/client scope:
- Confirmed treatment:
- Exceptions/tolerance:
- Evidence/example invoice:
- Canonical decision update:

## Q-003 - Foreign invoices, customs costs, and imported services

Status: Awaiting pilot-accountant answer

Decision affected: `00-canonical-decision-register.md` - Foreign-supplier
invoices, imports, and imported services

### Primary question to ask

> Yabancı satıcıdan gelen mal ve hizmet faturalarını, gümrük beyannamesiyle
> oluşan vergi/masrafları ve yurt dışından alınan hizmetlerde KDV2/stopaj
> işlemlerini pratikte hangi fiş ve hesap yapısıyla kaydediyorsunuz?

### Follow-up points if needed

1. Yabancı mal faturası ilk geldiğinde hangi stok/maliyet/cari hesapları ve hangi
   kuru kullanıyorsunuz?
2. Gümrük beyannamesi, ithalat KDV'si, gümrük/ilave vergiler, navlun, sigorta ve
   müşavirlik bedellerini ayrı fişte mi yoksa mal faturasıyla birlikte mi
   kaydediyorsunuz?
3. Hangi ithalat KDV'si indirilecek KDV'ye, hangi tutarlar maliyet veya kabul
   edilmeyen gider yapısına gidiyor?
4. Bir beyanname birden fazla faturaya veya bir fatura birden fazla beyannameye
   bağlıysa masraf/vergi dağıtımını neye göre yapıyorsunuz?
5. Gümrük belgesi henüz gelmediyse yabancı satıcı faturasını onaylıyor musunuz;
   sonradan gelen gümrük kaydını nasıl bağlıyorsunuz?
6. Yurt dışı yazılım, reklam, danışmanlık, test, abonelik ve benzeri hizmetlerde
   KDV2 ve stopaj kararını hangi bilgiye göre veriyorsunuz?
7. Çifte vergilendirmeyi önleme anlaşması veya mukimlik belgesi gerektiğinde
   ofis iş akışınız nedir?
8. Hangi satıcı/hizmet örüntüleri ofis genelinde, hangileri mükellefe özel kural
   olabilir?

### Current provisional default

- Prepare the foreign-invoice goods/service and payable journal without
  inventing Turkish import VAT or customs amounts.
- Process later customs/tax evidence as linked accounting work with many-to-many
  source relationships.
- Do not block the underlying invoice or automatically request client evidence
  merely because customs evidence is not yet linked.
- Treat foreign services separately and require first-pattern accountant review
  before activating a scoped tax/account rule.
- Keep exhaustive customs automation outside the first-pilot go/no-go gate.

### Answer record

- Answered by:
- Answered at:
- Office/client scope:
- Confirmed treatment:
- Exceptions/tolerance:
- Evidence/example invoice:
- Canonical decision update:

## Q-004 - Goods and service export accounting

Status: Awaiting pilot-accountant answer

Decision affected: `00-canonical-decision-register.md` - Goods exports, service
exports, and customs completion evidence

### Primary question to ask

> Mal ihracatı ve hizmet ihracatı faturalarını hangi hesaplara ve hangi aşamada
> kaydediyorsunuz? Gümrük/GTB/ETGB kapanışı veya hizmetten yurt dışında
> faydalanma değerlendirmesi, fiş onayı ve vergi uygulamanızı nasıl etkiliyor?

### Follow-up points if needed

1. Mal ihracatı faturasında kullandığınız yabancı alıcı ve yurt dışı satış hesap
   yapısı nedir; mükellefe göre değişiyor mu?
2. Fişi fatura tarihinde mi hazırlayıp onaylıyorsunuz, yoksa gümrük çıkış/kapanış
   kanıtını mı bekliyorsunuz?
3. GTB ret veya kısmi kabul/çıkış halinde hangi düzeltme, iptal veya yeni fatura
   sürecini uyguluyorsunuz?
4. Mikro ihracat/ETGB ve kargo çıkış kanıtını nereden alıyor ve muhasebe kaydına
   nasıl bağlıyorsunuz?
5. Hizmet ihracında hizmetten yurt dışında faydalanıldığını pratikte hangi bilgi
   veya belgelerle değerlendiriyorsunuz?
6. Aynı yabancı müşterinin Türkiye faaliyetine verilen hizmeti nasıl ayırıyorsunuz?
7. Döviz tahsilatını ilk satış fişinden ayrı mı izliyor; kur farkını ve varsa
   iade/beyan kanıtını ne zaman bağlıyorsunuz?
8. Hangi ihracat örüntüleri ofis geneli, hangileri mükellef/müşteri/proje özelinde
   öğrenilebilir?

### Current provisional default

- Prepare the full export-invoice journal immediately while tracking customs
  completion as separate linked evidence.
- Prevent unattended external delivery while required goods-export completion
  remains pending; do not block draft preparation or request client evidence
  automatically.
- Apply rejection/correction behavior at whole-document or partial-line scope
  according to verified GTB/customs evidence.
- Treat service-export use/benefit context semantically and require one first-
  pattern accountant confirmation before scoped automation.
- Keep exhaustive customs/ETGB automation outside the first-pilot go/no-go gate.

### Answer record

- Answered by:
- Answered at:
- Office/client scope:
- Confirmed treatment:
- Exceptions/tolerance:
- Evidence/example invoice:
- Canonical decision update:
