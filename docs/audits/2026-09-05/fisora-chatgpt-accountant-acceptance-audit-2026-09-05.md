# Fisora UX/UI — ChatGPT Accountant Acceptance Audit — 2026-09-05

**Reviewer:** ChatGPT
**Persona:** 50–55 yaşlarında deneyimli Türk mali müşavir
**Method:** Kod okumasını kabul kriteri saymadan canlı UI üzerinden gerçek işlem ve state geçişi testi.
**Purpose:** Multi-agent review register için bağımsız kaynak rapor.

## Executive verdict

Fisora prototip seviyesini geçmiş durumda. Çalışma Masası'nın fatura + mahsup fişi yan yana modeli, kaynak/provenance bağlantısı, klavye-first seri inceleme ve `Onayla ve sonraki` hiyerarşisi güçlü.

Ana risk görsel tasarım değil; kullanıcının `hangi mükellef + hangi dönem + hangi belge + hangi state + hangi işlem` bağlamına güveninin bazı geçişlerde bozulması.

**Demo:** Evet.
**Kontrollü pilot:** Kritik state/trust konuları çözüldükten sonra.
**Bugün ofisin ana sistemi olarak kabul:** Hayır.

## Stable finding references

### CG-01 — Empty filter leaves stale document context
`Onaya hazır 0` ve `Evrak 0/0` durumunda önceki belge ve fiş görünür kaldı. Başka bir geçişte `Evrak 0/1` iken filtre dışındaki eski belge ekrandaydı.

### CG-02 — Ctrl+Z undo did not visibly work
F1 yardımı 8 saniyelik undo vaat ediyor. `Onayla → Ctrl+Z` ve `Ctrl+Enter → Ctrl+Z` iki ayrı denemede görünür geri alma üretmedi.

### CG-03 — Preview can break after approval
Onaydan önce görünen iki belge onaylandıktan sonra `Onaya hazır` görünümünde sırasıyla `Belge geldi ancak görüntüleyici seçilemedi` ve boş beyaz preview verdi.

### CG-04 — Contradictory workflow labels
Aynı kayıt üzerinde `Onaya hazır`, `Aktarıma hazır` ve `Müşavir onayı bekliyor` ifadeleri birlikte görüldü.

### CG-05 — Approval changes provenance to `Manuel fiş girildi`
Fiş manuel düzenlenmeden yalnız `Onayla ve sonraki` kullanıldı; sonrasında provenance `Manuel fiş girildi` oldu.

### CG-06 — Returning to control did not restore provenance
`Kontrolde tut` sayaç/state'i geri çevirdi; `Manuel fiş girildi` provenance'ı kaldı.

### CG-07 — Period context is ambiguous
Ana bağlam Haziran 2026 iken resume kartında Ağustos 2026 görüldü. Ağustos çalışma masasında Mayıs tarihli belge/fişler vardı.

### CG-08 — Not all journal rows visible before approval
Normal viewport'ta görünmeyen ek fiş satırı fullscreen'de ortaya çıktı; ana onay aksiyonu buna rağmen erişilebilirdi.

### CG-09 — `Hariç tut` showed no visible transition
ARİF ŞAN 17,61 TL belgede `Hariç tut` sonrası sayaç/list/state görünür biçimde değişmedi.

### CG-10 — Zero-value document still follows normal posting UX
0 TL DEMANT belgesi `Mahsup Fişi Taslağı`, `Müşavir onayı bekliyor` ve normal onay akışıyla gösterildi.

### CG-11 — Learned Rules leaks raw backend error
Canlı UI'da `learning rules failed with 500` görüldü.

### CG-12 — QNB settings leak implementation/configuration details
`/phase0/... failed with 500`, `active QNB connection is required` ve `FISORA_QNB_CREDENTIAL_KEY is required in production` mesajları kullanıcıya çıktı.

### CG-13 — Duplicate upload result is not explained to the user
Aynı PDF APEX/Satış olarak tekrar yüklendi. UI `1 belge backend kuyruğuna alındı.` dedi; toplam belge sayısı değişmedi. Backend dedupe yapıyor olabilir, ancak kullanıcı sonucu anlayamıyor.

### CG-14 — 125% zoom with expanded sidebar compresses accounting pane
1366×768 @ 100% genel olarak kullanılabilir; %125 browser zoom + açık sidebar sağ fiş alanını ve hesap adlarını ciddi sıkıştırdı.

### CG-15 — Turkish-insensitive client search missing
`ARIF` → 0 sonuç, `ARİF` → 1 sonuç. 0 sonuçta `Henüz mükellef yok` mesajı çıktı; ofiste mükellefler vardı.

### CG-16 — Empty sales queue copy is misleading
`Satış 0` görünümünde `İşlemek için listeden belge seçin.` mesajı çıktı.

### CG-17 — Reopening queue does not reveal current item
`Evrak 12/25` konumunda kuyruk gizlenip tekrar açıldığında liste 1. belgeden başladı; mevcut seçim görünür alana scroll edilmedi.

### CG-18 — Queue/page counters are easy to confuse
`Evrak 12/25` ve `1/3` aynı alanda görülüyor; biri kuyruk, biri belge sayfası.

### CG-19 — Critical account text truncates
Cari/hesap açıklamalarında `Hesap planından seçim be...` gibi truncation görüldü.

### CG-20 — Upload history uses raw ISO timestamp
Örnek: `2026-09-04T23:00:03+00:00`.

### CG-21 — Mobile login is hero-first
~430 px genişlikte uygulama içi Yeni Yükleme iyi stack olurken login formu büyük pazarlama hero'sunun altına düştü.

### CG-22 — Shortcut behavior is focus-sensitive
F10 ve `↑↓` normal kullanımda çalıştı. Ancak dönem select focus'tayken `↓` evrak yerine dönemi değiştirdi.

### CG-23 — Preview controls work but toolbar is dense
Sığdır, Genişlik, İçerik, %100, +/− ve Büyüteç çalıştı. Kontrol sayısı ilk bakışta yoğun.

### CG-24 — Source/provenance interaction is a strong product pattern
`Kaynak 1,2,3` ve `Kaynak ayrıntısı` gerçek UI'da çalıştı; satır kanıtı muhasebe kararına güven katıyor.

### CG-25 — Output readiness/prerequisite UX is incomplete
Onay & Çıktılar alanında bazı butonlar aktifken `Cikti paketi icin once mukellef ekleyin.` mesajında durdu; XLSX bazı durumda disabled görüldü.

### CG-26 — Banka / Diğer Belgeler currently carry empty scope
Tablar çalışıyor ancak içerik boş; pilotta görünürlük/prominence ürün kararı gerektiriyor.

## Verified strong areas

- Çalışma Masası'nın kaynak belge + fiş yan yana modeli.
- `Onayla ve sonraki` ana aksiyon hiyerarşisi.
- Alış/Satış ayrımı.
- 10+ ardışık `↓` geçişinde belge/fiş senkronunun korunması.
- F2 hesap düzenleme focus'u ve autocomplete.
- F3 mükellef/dönem erişimi.
- F10 sidebar daralt/aç.
- Belgeyi incele, fişi gizle ve browser fullscreen.
- Preview fit/width/content/zoom ve büyüteç.
- Sığdır modunda büyütecin açık, Genişlik modunda kapalı gelmesi.
- Yeni Yükleme'nin temel akışı ve mobil stack davranışı.
- AI Ajanları dilinin teknik model isimleri yerine sonuç/yardım odaklı olması.
- `Kalite ölçümünü çalıştır` aksiyonunun görünür başarı sonucu üretmesi.

## Audit interpretation note

Bu rapor denetim gözlemlerini kaydeder; her finding otomatik olarak kabul edilmiş bug veya ürün eksiği değildir. Kararlar `multi-agent-review-register-2026-09-06.md` içinde tek tek görüşülerek verilecektir.
