# Faz 0 Test Plani

## Amac

Zirve aktarim rotasi, hesap plani importu ve temel muhasebe fis uretimi tam
MVP'ye baslamadan once dogrulanacak.

## Girdi Paketi

Gercek veya anonimlestirilmis veriyle test hedeflenir:

- 3 adet Zirve hesap plani export dosyasi
- 1 alis faturasi
- 1 satis faturasi
- 1 karisik KDV faturasi
- 1 banka Excel/CSV ekstresi
- Varsa Zirve'nin kabul ettigi ornek import dosyasi

Gercek veri hazir degilse `samples/` altindaki sentetik dosyalar kullanilir.

## Test Senaryolari

### 1. Hesap Plani Import

- CSV veya Excel dosyasindan hesap kodu ve hesap adi okunur.
- Hesap kodlari normalize edilir.
- Detay hesaplar alt hesabi olmayan hesaplar olarak isaretlenir.
- 120 ve 320 ile baslayan hesaplardan cari adaylari cikarilir.
- 191 ve 391 KDV hesaplarinin varligi raporlanir.

### 2. Fis Uretimi

- Alis fisinde gider ve 191 KDV borc, 320 cari alacak olur.
- Satis fisinde 120 cari borc, gelir ve 391 KDV alacak olur.
- Banka odeme fisinde 320 cari borc, banka hesabi alacak olur.
- Karisik KDV senaryosu dengeli uretilir ama manuel kontrol riski tasir.

### 3. Export

- Universal journal CSV uretir.
- Zirve testinde hangi kolonlarin kabul edildigi kaydedilir.
- Calismayan formatlar hata mesaji ve eksik kolonla birlikte belgelenir.

## Kabul Kriterleri

- 3 hesap plani dosyasi parse edilebilir.
- Detay hesap ayrimi kontrol edilebilir.
- 120/320 cari adaylari raporlanir.
- Alis, satis ve banka fisleri dengelidir.
- Karisik KDV fisinde `mixed_vat_manual_review` risk bayragi vardir.
- En az bir Zirve import rotasi basarili sonuc verir.

