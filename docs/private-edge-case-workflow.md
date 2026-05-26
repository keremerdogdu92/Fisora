# Gercek Fatura Edge-Case Akisi

Gercek fatura dosyalari repoya eklenmez. Bu dosyalar lokal makinede kalir ve
yalnizca git disi `private_samples/` ciktisi uretilir.

## Lokal Klasor

Ilk test klasoru:

```text
C:\Users\kerem\Desktop\Yeni klasör
```

## Manifest Uretimi

```powershell
python backend/scripts/scan_invoice_folder.py "C:\Users\kerem\Desktop\Yeni klasör"
```

Varsayilan cikti:

```text
private_samples/manifest.csv
```

Bu dosya git tarafindan yok sayilir.

## Manifest Kolonlari

- `file_name`
- `extension`
- `size_bytes`
- `sha256`
- `page_count`
- `text_extractable`
- `extracted_char_count`
- `provider_hint`
- `invoice_no`
- `ettn`
- `detected_keywords`
- `risk_flags`
- `suggested_expected_behavior`
- `notes`

## Beklenen Kullanım

1. Manifest uretilir.
2. Her satir icin beklenen edge case ve beklenen sonuc insan tarafindan
   netlestirilir.
3. Ham PDF yerine anonimlestirilmis JSON fixture olusturulur.
4. Testler anonim fixture uzerinden yazilir.

## Guvenlik Kurali

Ham PDF, gercek VKN/TCKN, IBAN, unvan ve belge numaralari commit edilmez.

