# Muhasebe Operasyon Otomasyonu

Zirve Masaustu kullanan muhasebe operasyonlari icin Faz 0 dogrulama paketi.

Bu repo, tam MVP'ye gecmeden once asagidaki teknik riskleri dogrulamak icin
baslatilmistir:

- Zirve hesap plani import edilebiliyor mu?
- Detay hesaplar guvenilir sekilde ayrilabiliyor mu?
- 120/320 cari adaylari hesap planindan cikarilabiliyor mu?
- 191/391 KDV hesaplari dogrulanabiliyor mu?
- Alis, satis, banka ve karisik KDV fis taslaklari dengeli uretilebiliyor mu?
- Zirve'ye aktarilabilir en az bir export rotasi bulunabiliyor mu?

## Yapı

```text
backend/    FastAPI iskeleti, domain prototipleri, testler
docs/       Urun kararlari, Faz 0 test plani, acik kararlar
frontend/   Next.js placeholder
samples/    Anonim veya sentetik test verileri
exports/    Lokal uretilen test ciktilari, repoya alinmaz
```

## Hızlı Doğrulama

```powershell
python -m unittest discover backend/tests
python backend/scripts/run_phase0_demo.py
```

`run_phase0_demo.py`, sentetik hesap plani ve fis ornekleriyle `exports/`
altinda test CSV dosyalari uretir. Gercek musteri verisi anonimlestirilmeden bu
repoya eklenmemelidir.

## GitHub Akışı

Yeni GitHub reposu private acilacak. Bu local scaffold ilk commit olarak
baglanacak. Gercek musteri belgeleri, vergi numaralari ve hesap planlari repoya
anonimlestirilmeden eklenmeyecek.
