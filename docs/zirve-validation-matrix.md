# Zirve Import/Export Dogrulama Matrisi

Bu tablo Zirve makinesinde yapilan testlerle doldurulacak. Bos alanlar
bilerek birakilmistir.

| Test ID | Format Adayi | Dosya | Sonuc | Zirve Hata Mesaji | Zorunlu Kolonlar | Not |
|---|---|---|---|---|---|---|
| ZRV-001 | Universal Journal CSV | exports/universal_journal.csv | TBD | TBD | TBD | Ilk aday format |
| ZRV-002 | Zirve Trial Voucher CSV | exports/generated/{client}-zirve_trial_csv.csv | TBD | TBD | fis_tarihi, fis_turu, hesap_kodu, borc, alacak | Yeni saha eslestirme adayi; dogrulanmadi |
| ZRV-003 | Fis listesi Excel | TBD | TBD | TBD | TBD | Alternatif rota |
| ZRV-004 | Fatura Excel | TBD | TBD | TBD | TBD | Fis seviyesi yeterli olmazsa |
| ZRV-005 | Banka Excel | TBD | TBD | TBD | TBD | Banka hareketleri icin |

## Testte Kaydedilecek Bilgiler

- Zirve versiyonu
- Sirket/donem ayari
- Import ekraninin adi
- Dosya uzantisi ve ayiraci
- Tarih formati
- Tutar decimal formati
- Hesap kodu format beklentisi
- Fis no/seri zorunlulugu
- Basarili import sonrasi Zirve'de olusan fis goruntusu

## Yeni Trial CSV Adayi

`zirve_trial_csv` adapter'i gercek Zirve import formati olarak isaretlenmez.
Amaci, mustavirle saha testinde kolonlari hizli eslestirmektir.

Kolonlar:

```text
fis_tarihi
fis_turu
fis_aciklama
satir_no
hesap_kodu
satir_aciklama
borc
alacak
belge_no
vergi_no
kaynak_belge
```

Dosya `;` ayiraci ve UTF-8 BOM ile yazilir. Zirve testinde ayirac, tarih
formati, tutar formati ve zorunlu fis alanlari dogrulanmadan `verified_in_zirve`
degeri `false` kalir.
