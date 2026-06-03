# Private Intake Manifest

## Amac

Mali mustavirden veya pilot mukelleften gelen gercek dosyalar repo disinda
kalacak. Fisora sadece dosyalarin hangi mukellefe, hangi doneme ve hangi belge
tipine ait oldugunu takip eden bir manifest uretecek.

Ham dosyalar GitHub'a eklenmez. Varsayilan cikti `private_samples/` altindadir
ve `.gitignore` tarafindan disarida tutulur.

## Onerilen Klasor Yapisi

```text
pilot_paket/
  mukellef_karti.xlsx
  zirve_hesap_plani.xlsx
  cari_liste_120_320.xlsx
  yevmiye_son_3_ay.xlsx
  banka_ekstresi_2026_05.csv
  faturalar/
    alan_ici_rexton.pdf
    supheli_urban_care.pdf
  zirve_import_ornegi.xlsx
```

## Manifest Uretme

```powershell
python backend/scripts/build_private_intake_manifest.py C:\path\pilot_paket `
  --client-id pilot-isitme-merkezi `
  --client-name "Pilot Isitme Merkezi" `
  --period 2026-05 `
  --privacy-level real
```

Uretilen dosyalar:

- `private_samples/intake_manifest.csv`
- `private_samples/intake_manifest.json`

Manifest su alanlari tutar:

- `client_id`, `client_name`, `period`, `privacy_level`
- `relative_path`, `file_name`, `extension`
- `document_kind`
- `size_bytes`, `sha256`

## Belge Tipi Tahmini

Script dosya adindan ve uzantidan su tipleri ayirir:

- `chart_accounts`
- `counterparty_list`
- `journal_history`
- `bank_statement`
- `pos_statement`
- `invoice`
- `zirve_import_sample`
- `archive`
- `spreadsheet_unknown`
- `unknown`

Bu siniflandirma kesin muhasebe karari degildir. Ama gercek veri geldigi gun
hangi dosyanin hangi islem hattina girecegini karistirmadan baslatir.

## Guvenlik

- Ham PDF/XML/ekstre dosyalari manifest tarafindan kopyalanmaz.
- Manifest hash ve dosya metadata'si uretir.
- Gercek veriler yalnizca lokal veya yetkili private ortamda kullanilir.
- Dis AI API'ye anonim olmayan veri gondermek icin ayrica mustavir/onay gerekir.
- Production'da ham belgeler 90 gun saklanir; metadata, fis taslagi, review
  karari, learning event ve export izi kalir.
