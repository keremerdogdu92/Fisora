# Docker Sonrasi Mustavirsiz Kalan Isler

Bu liste Docker smoke testleri gectikten sonra, mali mustavirden gercek veri
ve Zirve saha testi beklemeden ilerletilebilecek teknik isleri ayirir.

## Tamamlanan Dilimler

1. Gercek session/auth MVP altyapisi
   - `portal_users` kaydi korunur.
   - Parola hash'i ve session token hash'i store'a yazilir.
   - `X-Fisora-Session` header'i workspace, upload, review ve export
     yetkilerinde kullanilabilir.
   - `trusted_header` ve session bootstrap ayni anda desteklenir.

2. Storage adapter ilk surumu
   - Local document storage davranisi adapter arkasina alindi.
   - Upload path/hash/retention metaverisi ayni kalir.
   - S3-compatible storage daha sonra ayni adapter kontratina eklenebilir.

3. Production readiness self-check
   - `/phase0/store/system/readiness` endpoint'i eklendi.
   - Auth modu, document/export storage yazilabilirligi, store backend, AI
     provider ve export adapter durumlari tek payload'da gorulur.

4. Frontend login/session ekrani
   - Ust panelde kullanici id/sifre ile login, demo sifre atama ve logout
     aksiyonlari eklendi.
   - Session varsa API istekleri `X-Fisora-Session` ile gider.
   - Session yoksa demo/mock header fallback calisir.

5. Kullanici davet ve sifre reset iskeleti
   - Invite token, invite accept, password reset token ve reset confirm
     endpointleri eklendi.
   - Token raw hali sadece response'ta doner; store'da hash tutulur.
   - Mail gonderimi henuz yoktur; ilk surum manuel token/link akisi icindir.

6. AI provider maliyet ledger ilk surumu
   - Product classification client_id ile cagrilirsa AI usage event kaydi
     olusur.
   - Provider, operation, input karakteri, AI kullanildi mi, skip nedeni ve
     tahmini maliyet tutulur.
   - Monthly cap summary endpoint'i eklendi.

7. Observability ve operasyon loglari ilk surumu
   - Upload, review karari, export package, export download, retention ve
     processing run olaylari operation event olarak kaydedilir.
   - `/phase0/store/operation-health/{client_id}` worker job sayilari, son olay
     ve hata/uyari durumunu ozetler.
   - JSON store ve PostgreSQL adapter ayni operation log yuzeyini destekler.

8. Frontend readiness/admin paneli ilk surumu
   - Auth, storage, worker, AI cap, Zirve adapter ve son operasyon olayi tek
     bandda gosterilir.
   - Workspace yenilenince operation health ve AI usage summary de yenilenir.

9. Real-data local intake manifest araci
   - `backend/scripts/build_private_intake_manifest.py` pilot klasoru tarar.
   - `private_samples/intake_manifest.csv` ve `.json` uretir.
   - Ham dosyalari kopyalamaz; sadece dosya tipi, hash, boyut ve mukellef/donem
     metadata'si yazar.

## Mustavir Beklemeden Kalan Isler

1. S3-compatible object storage hazirligi
   - Local adapter yanina object storage adapter sozlesmesi.
   - Presigned download URL veya backend proxy karari.
   - 90 gun retention ile object delete davranisi.

2. Docker production hardening scriptleri
   - Sunucu ilk kurulum komutlari.
   - `.env` template kopyalama ve secret checklist.
   - `docker compose pull/build/up` runbook.
   - Backup restore deneme komutlari.

3. Real-data local import araclari ikinci dilim
   - Manifestten hesap plani/fatura/ekstre upload job'u olusturma.
   - Private sample ciktilarini store'a kontrollu baglama.
   - Gercek veriyi anonim/public demo hattindan ayri tutan runbook.

4. Backup/disk health sinyali
   - Son backup zamani ve backup path manifesti API'de gorunur.
   - Disk doluluk orani veya belge volume boyutu readiness'e eklenir.

## Mustavir veya Zirve Gerektiren Kilitler

- Zirve import formatinin gercek programda dogrulanmasi.
- Gercek hesap plani/cari kolonlarinin son formati.
- Hangi belge tiplerinin otomatik export'a alinabilecegi.
- AI provider benchmarkinin gercek/anonymized fatura setiyle kosulmasi.
- Production otomasyon esikleri.

Bu kilitler gelmeden sistem demo/pilot altyapisi olarak ilerleyebilir, ancak
`verified_in_zirve=true` veya tam otomatik export karari verilemez.
