# Demo Oncesi Mali Mustavirden Istenenler

## Kullanim Amaci

Bu dosya, demo veya ilk pilot oncesi mali mustavire gonderilecek net talep
listesidir. Amac mustavirden uzun kural dosyasi doldurmasini istemek degil,
sistemin ilk taslaklari hazirlayabilmesi icin gerekli minimum veriyi almaktir.

## Gonderilecek Kisa Mesaj

```text
Merhaba,

Fisora demosunu gercege yakin gosterebilmemiz icin sizden 1 pilot mukellef
uzerinden asagidaki dosyalari rica ediyoruz. Amacimiz bu dosyalarla kesin kayit
atmak degil; sistemin fatura/ekstreleri okuyup size kontrol edilebilir fis
taslagi, risk gerekcesi ve export paketi hazirlayabildigini gostermek.

Gercek musteri verisi paylasmak istemezseniz dosyalari anonimlestirilmis sekilde
alabiliriz. Gercek veriyle test yaparsak bunu sadece lokal test ortaminda
kullanacagiz; public demo veya GitHub'a eklemeyecegiz.
```

## 1. Zorunlu Minimum Paket

Demo oncesi mutlaka istenecekler:

- 1 pilot mukellef secimi.
- Mukellef unvani.
- VKN/TCKN.
- Faaliyet/NACE kodu veya kisa faaliyet aciklamasi.
- Isyeri adresi ve varsa sube adresleri.
- Zirve hesap plani exportu.
- 20-50 adet fatura veya anonimlestirilmis fatura.
- 1 adet banka Excel/CSV ekstresi.
- Mukellef adina portal kullanacak kisi adi/e-posta bilgisi veya demo icin
  varsayilacak kullanici bilgisi.

Bu paket gelirse sistem sunlari gosterebilir:

- Mukellef eslesmeli belge yukleme.
- Fatura okuma ve fis taslagi.
- Cari/hesap adayi.
- Risk ve faaliyet uygunlugu.
- Mustavir onayi/duzeltmesi.
- Kontrollu export paketi.

## 2. Varsa Cok Degerli Ek Dosyalar

Olursa pilotu ciddi hizlandirir, olmazsa blokaj degildir:

- Cari liste exportu veya 120/320 detay hesap listesi.
- Cari listede VKN/TCKN, vergi dairesi, IBAN veya unvan kolonlari.
- Son 1-3 aya ait yevmiye exportu.
- Muavin dokumu.
- Fis listesi.
- Zirve'nin kabul ettigi ornek import dosyasi.
- Daha once Zirve'ye basariyla aktarilmis bir ornek CSV/XLSX.

Bu dosyalarla sistem sunlari daha iyi yapar:

- Tedarikciyi dogru 320 cari hesaba baglama.
- Aliciyi dogru 120 cari hesaba baglama.
- "Bu tedarikci gecmiste hangi hesaba islenmis?" bilgisini cikarma.
- Zirve export formatini sahada hizli dogrulama.

## 3. Ozel Olarak Istenen Fatura Ornekleri

Demo icin sadece kolay faturalar yetmez. Asagidaki cesitlilik istenir:

- Alan ici uygun fatura.
- Genel gider faturasi: elektrik, internet, kira, e-fatura servisi, kargo.
- Supheli veya faaliyet disi fatura: kisisel bakim, market, alakasiz urun.
- Marka/model yazan fatura: urun adi acik kategori olarak yazmayan ornek.
- Tek KDV oranli fatura.
- Varsa karma KDV, tevkifat, iade veya istisna ornegi.
- Cari bilgisi net olan fatura.
- Cari bilgisi belirsiz veya yeni tedarikci faturasi.

Ornek hedef:

```text
Isitme merkezi icin:
- Rexton, Phonak, Oticon gibi alan ici urunler.
- Urban Care veya benzeri kisisel bakim urunu gibi supheli kalem.
- Internet/elektrik gibi adres kontrolu gerektirebilecek genel gider.
```

## 4. Banka Ekstresi Icin Istenenler

En az 1 Excel/CSV ekstresi istenir. Mumkunse sunlari icermeli:

- GIB odemesi.
- SGK odemesi.
- POS hareketi veya POS bloke.
- Tedarikci odemesi.
- Musteri tahsilati.
- Aciklamasi belirsiz bir satir.
- IBAN veya karsi taraf bilgisi olan satir.

Bu verilerle banka/POS modulu ve cari eslestirme test edilir.

## 5. Zirve Icin Sorulacak Net Sorular

Mustavire dosya disinda su sorular sorulur:

1. Zirve'de fis importu icin hangi ekran veya format en guvenilir?
2. Hesap plani exportunda VKN/TCKN, vergi dairesi veya IBAN kolonu var mi?
3. Cari listeyi ayri export alabiliyor muyuz?
4. Yevmiye, muavin veya fis listesini Excel/CSV olarak alabiliyor muyuz?
5. Zirve'ye disaridan fis aktarirken kabul ettigi ornek dosya var mi?
6. Export paketi mukellef bazli mi, donem bazli mi hazirlanmali?
7. Hangi belge tipleri ilk etapta kesinlikle mustavir kontrolunde kalmali?
8. Dis AI API'ye anonim olmayan fatura metni gondermek uygun mu, yoksa sadece
   anonim/lokal test mi yapalim?

## 6. Veri Guvenligi Notu

Gercek veriler alinacaksa varsayilan politika:

- Ham PDF/XML/ekstre sadece lokal veya yetkili private ortamda kullanilir.
- GitHub'a, public demo linkine veya sentetik sample klasorune eklenmez.
- Public demo icin sentetik veya anonim veri kullanilir.
- Dis AI API kullanimi icin ayrica onay veya anonimlestirme gerekir.
- Production sistemde ham belgeler 90 gun saklanir; metadata, fis taslagi,
  review karari, learning event ve export izi korunur.

## 7. Mustavirden Beklenen Efor

Mustavirden beklenen is:

- Bir pilot mukellef secmek.
- Yukaridaki dosyalari mumkunse tek klasorde paylasmak.
- Demo sirasinda sistemin onerdigi fisleri onaylamak veya duzeltmek.
- Zirve export testinde bir ornek dosyanin iceri aktarimini denemek.

Mustavirden beklenmeyen is:

- Bos kural tablosu doldurmak.
- Tum mevzuat kurallarini bastan anlatmak.
- Her tedarikci icin tek tek hesap kodu yazmak.
- Ilk gunden otomasyona onay vermek.

## 8. Dosya Adlandirma Onerisi

Dosyalar mumkunse su mantikla adlandirilir:

```text
pilot_mukellef_karti.xlsx
zirve_hesap_plani.xlsx
cari_liste_120_320.xlsx
yevmiye_son_3_ay.xlsx
banka_ekstresi_2026_05.csv
faturalar.zip
zirve_import_ornegi.xlsx
```

Bu adlandirma zorunlu degildir; sadece dosyalari karistirmamak icindir.

## 9. Bizim Lokal Intake Adimimiz

Dosyalar geldikten sonra ilk yapilacak is ham dosyayi repoya eklemek degil,
lokal manifest uretmektir:

```powershell
python backend/scripts/build_private_intake_manifest.py C:\path\pilot_paket `
  --client-id pilot-mukellef `
  --client-name "Pilot Mukellef" `
  --period 2026-05 `
  --privacy-level real
```

Bu komut `private_samples/intake_manifest.csv` ve
`private_samples/intake_manifest.json` uretir. Manifest dosya tipi, boyut, hash,
mukellef, donem ve gizlilik bilgisini saklar; ham belgeyi GitHub'a eklemez.
