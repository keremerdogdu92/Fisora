# Urun Karar Ozeti

Bu dokuman, Desktop'taki PRD ve guncel plan dosyalarindan sadeleştirilmiş Faz 0
karar ozetidir.

## Konumlandirma

Urun "tam otonom AI muhasebeci" olarak konumlandirilmamalidir. Dogru tanim:

> AI destekli muhasebe operasyon otomasyonu.

Muhasebe dogrulugu AI ile degil; parser, kural motoru, hesap plani, cari
eslestirme, guven skoru ve kontrol kuyrugu ile saglanir.

## Faz 0 Hedefi

Faz 0'in tek hedefi, tam MVP gelistirmeden once Zirve aktarim ve muhasebe fis
uretimi riskini dusurmektir.

Basari kriteri:

- En az bir export rotasiyla Zirve'de hatasiz ve dengeli fis olusmali.

## Teknik Yon

- Frontend: Next.js
- Backend API: FastAPI
- Domain prototipleri: Python
- Database hedefi: PostgreSQL
- Worker hedefi: Python worker
- Queue hedefi: Redis + RQ veya Celery
- Storage hedefi: S3-compatible object storage veya MinIO

Supabase production ana mimari olarak kullanilmayacak. Sadece demo veya hizli
prototip icin opsiyonel tutulabilir.

## Faz 0 Kapsaminda Olanlar

- Zirve hesap plani import denemesi
- Detay hesap tespiti
- 120/320 cari aday cikarimi
- 191/391 KDV hesap kontrolu
- Alis, satis, banka ve karisik KDV fis taslaklari
- Universal journal CSV export adayi
- Zirve test sonucu matrisi

## Faz 0 Kapsaminda Olmayanlar

- Tam kullanici giris sistemi
- Mükellef portali
- Dosya yukleme UI'i
- OCR pipeline
- OpenAI/AI entegrasyonu
- Production deployment
- Gercek Zirve otomasyonu veya COM/OLE entegrasyonu

## Veri Guvenligi

Gercek musteri verisi anonimlestirilmeden repoya eklenmeyecek. `samples/`
altindaki dosyalar sentetik veya anonimlestirilmis olmalidir.

