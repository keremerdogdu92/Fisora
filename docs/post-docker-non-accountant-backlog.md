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

10. Real-data local import araclari ikinci dilim
    - `backend/scripts/import_private_intake_manifest.py` manifestten hesap
      plani, fatura, XML, banka ve POS dosyalarini store/upload job hattina
      aktarir.
    - Istenirse import sonrasi worker lokal olarak calistirilir.
    - Import summary `private_samples/intake_import_summary.json` altinda
      git disinda tutulur.

11. Backup/disk health sinyali ilk surumu
    - Readiness payload'i backup klasoru, son database backup'i, document
      manifest sayisi, belge/export/backup boyutlari ve disk doluluk oranini
      tasir.
    - Frontend admin panelinde Backup karti ve disk uyarisi gorunur.

12. Docker production hardening scriptleri ilk surumu
    - `deploy/scripts/fisora-prod.sh` check, deploy, migrate, smoke,
      backup-once, logs, ps, down ve restore-postgres komutlarini toplar.
    - `deploy/scripts/fisora-health.ps1` local/Windows health ve readiness
      kontrolu yapar.
    - `docs/production-ops-runbook.md` server gelince izlenecek sira olarak
      eklendi.

## Mustavir Beklemeden Kalan Isler

1. S3-compatible object storage hazirligi
   - Local adapter yanina object storage adapter sozlesmesi.
   - Presigned download URL veya backend proxy karari.
   - 90 gun retention ile object delete davranisi.

2. AI provider hazirligi ikinci dilim
   - OpenAI/Gemini provider adapter taslagi.
   - Synthetic ve real/anonymized benchmark komutlari.
   - Aylik cap asiminda provider cagrilarini durduran guard.

3. Auth/UI tamamlayici isler
   - Invite/reset token akisini admin panelinden yonetme.
   - Production bootstrap kapali oldugunda net UI durumu.
   - Mulkellef kullanicisi icin sifre degistirme ekrani.

4. Upload limit ve guvenlik kontrolleri
   - Dosya boyutu limiti.
   - Izinli uzanti/MIME kontrolu.
   - Buyuk/yanlis dosya tipi icin net hata payload'i.

5. Demo reset/seed akisi
   - Tek komutla sentetik mukellef, hesap plani, fatura ve banka ekstresi
     seed edilir.
   - Demo oncesi temiz ortam hazirlama kolaylasir.

## Mustavir veya Zirve Gerektiren Kilitler

- Zirve import formatinin gercek programda dogrulanmasi.
- Gercek hesap plani/cari kolonlarinin son formati.
- Hangi belge tiplerinin otomatik export'a alinabilecegi.
- AI provider benchmarkinin gercek/anonymized fatura setiyle kosulmasi.
- Production otomasyon esikleri.

Bu kilitler gelmeden sistem demo/pilot altyapisi olarak ilerleyebilir, ancak
`verified_in_zirve=true` veya tam otomatik export karari verilemez.
