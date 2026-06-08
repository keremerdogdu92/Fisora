# Private Pilot Arayuz Plani

Bu fazda halka acik demo acilmaz. Ilk denemeler gercek veya pilot veriyle, Git
disi local snapshot veya yetisirse private login arkasindaki server uzerinden
gosterilir. Ama hedef aynidir: mali musavir belgeleri, uretilen fis taslagini,
AI/kural gerekcesini ve cikti listesini calisir bir arayuzde gorebilmelidir.

## Veri Kuralı

- Gercek PDF/XML/CSV/XLSX dosyalari GitHub'a eklenmez.
- Local deneme verileri `private_samples/` veya ignored frontend snapshot
  dosyalarinda tutulur.
- Frontend once backend workspace API'sini okur:
  - `GET /phase0/store/clients`
  - `GET /phase0/store/workspace/{client_id}`
- Backend bos, kapali veya yetkisizse arayuz sirasiyla su local kaynaklara
  duser:
  - `frontend/public/local-pilot-data.json`
  - `frontend/public/local-workspace-data.json`
  - `frontend/public/local-review-data.json`
- Bu dosyalar yoksa arayuz private pilot fallback verisiyle acilir.
- Upload ve musavir karar kaydi basarili oldugunda frontend backend workspace'i
  yeniden okuyarak kuyruk, belge ve export durumunu ekrana geri yansitir.

## Ekranlar

- Mukellef portali: ay filtresi, yuklenen/islemde/isleme alinan belge sayilari,
  belge yukleme, sade belge listesi, iptal veya duzeltme talebi ve cikis.
- Musavir masasi: mukellef arama/secme, secili mukellef sabit ozeti, belge
  listesi, iptal talepleri, iki panelli belge + muhasebe fisi review alani.
- Cikti listesi: musavir tamamladigi mukellefleri listeye ekler; tek toplu paket
  veya mukellef bazli paket secimi arayuzde temsil edilir.
- Operasyon: hangi private/local veri kaynaginin okundugunu ve Git disi veri
  kuralini gosterir.

## Ayni Domain Path Sozlesmesi

Tanitim sitesindeki iki giris butonu ayni domain altindaki uyelikli portal
path'lerine gider:

- `https://siteadi.com/portal/mukellef`: mukellef kullanicisi icin sade yukleme
  ve belge durum ekrani.
- `https://siteadi.com/portal/musavir`: musavir icin review masasi.

Musavir link ailesinin alt ekranlari ayni portal icinde kalir:

- `/portal/cikti`: tamamlanan mukelleflerin cikti listesi.
- `/portal/operasyon`: private veri kaynagi ve sistem durumu ekrani.

Server tarafinda ayni domain kullanildiginda `/portal/*` frontend'e, `/api/*`
backend'e gider. Production Nginx sozlesmesi bu ayrimi korumalidir.

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
