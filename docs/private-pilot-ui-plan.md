# Private Pilot Arayuz Plani

Bu fazda halka acik demo acilmaz. Ilk denemeler gercek veya pilot veriyle, Git
disi local snapshot veya yetisirse private login arkasindaki server uzerinden
gosterilir. Ama hedef aynidir: mali musavir belgeleri, uretilen fis taslagini,
AI/kural gerekcesini ve cikti listesini calisir bir arayuzde gorebilmelidir.

## Veri Kuralı

- Gercek PDF/XML/CSV/XLSX dosyalari GitHub'a eklenmez.
- Local deneme verileri `private_samples/` veya ignored frontend snapshot
  dosyalarinda tutulur.
- Frontend sirasiyla su kaynaklari okur:
  - `frontend/public/local-pilot-data.json`
  - `frontend/public/local-workspace-data.json`
  - `frontend/public/local-review-data.json`
- Bu dosyalar yoksa arayuz private pilot fallback verisiyle acilir.

## Ekranlar

- Mukellef portali: ay filtresi, yuklenen/islemde/isleme alinan belge sayilari,
  belge yukleme, sade belge listesi, iptal veya duzeltme talebi ve cikis.
- Musavir masasi: mukellef arama/secme, secili mukellef sabit ozeti, belge
  listesi, iptal talepleri, iki panelli belge + muhasebe fisi review alani.
- Cikti listesi: musavir tamamladigi mukellefleri listeye ekler; tek toplu paket
  veya mukellef bazli paket secimi arayuzde temsil edilir.
- Operasyon: hangi private/local veri kaynaginin okundugunu ve Git disi veri
  kuralini gosterir.

## UI Sozlesmesi

`local-pilot-data.json` kullanilirsa beklenen ust seviye alanlar:

```json
{
  "generatedFrom": "local pilot data",
  "clients": [],
  "documents": [],
  "cancellationRequests": [],
  "exportBasket": []
}
```

Desteklenen belge durumlari:

```text
uploaded
queued
processing
review_required
export_ready
cancel_requested
cancel_approved
cancel_rejected
export_added
exported
post_export_correction_requested
```

## Kabul Kriterleri

- Halka acik veya anonimlestirilmis demo dili arayuzde ana akisa karismaz.
- Local private veri varsa arayuz bunu okur ve musavir review ekraninda
  gosterir.
- Mukellef ekrani muhasebe fisi, AI gerekcesi ve export paketini gostermez.
- Musavir ekraninda belge onizleme ile muhasebe fisi ayni calisma alaninda
  gorunur.
- Iptal talebi export oncesi ve sonrasi ayrilabilir.
- Cikti listesi cok mukellefli ay kapanisi hedefine uygun ayri bir ekran olarak
  baslar.
