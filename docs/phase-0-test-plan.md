# Faz 0 Test Plani

## Amac

Zirve aktarim rotasi, hesap plani importu ve temel muhasebe fis uretimi tam
MVP'ye baslamadan once dogrulanacak. Faz 0 halen urun portali degil, muhasebe
motoru ve export gercekligi testidir.

Yeni MVP kararlarina gore Faz 0 testleri su soruya da cevap vermelidir:

- Mukellef karti + Zirve hesap plani ile guvenli fis taslagi ve kontrollu export
  uretilebiliyor mu?
- Marka/model iceren fatura satirlari kategoriye cevrilip is alani uygunluk
  riskine baglanabiliyor mu?
- Supheli veya is alani disi belgeler export paketinden dislanabiliyor mu?

## Girdi Paketi

Gercek veya anonimlestirilmis veriyle test hedeflenir:

- 2 pilot mukellef karti
- Her pilot icin VKN/TCKN, faaliyet/NACE veya faaliyet aciklamasi
- Her pilot icin isyeri adresi veya sube adresleri
- 3 adet Zirve hesap plani export dosyasi
- Varsa cari liste, yevmiye, muavin veya fis exportu
- 20-50 adet fatura ornegi
- Marka/model iceren alan ici ve alan disi fatura satirlari
- 1-2 banka Excel/CSV ekstresi
- Varsa Zirve'nin kabul ettigi ornek import dosyasi

Gercek veri hazir degilse `samples/` altindaki sentetik veya anonimlestirilmis
dosyalar kullanilir. Gercek musteri verisi repoya eklenmez.

## Test Senaryolari

### 1. Mukellef ve Hesap Plani Import

- Mukellef karti olmadan belge islenmez.
- CSV veya Excel dosyasindan hesap kodu ve hesap adi okunur.
- Hesap kodlari normalize edilir.
- Detay hesaplar alt hesabi olmayan hesaplar olarak isaretlenir.
- 120 ve 320 ile baslayan hesaplardan cari adaylari cikarilir.
- 191 ve 391 KDV hesaplarinin varligi raporlanir.
- Sistem mukellef ozel detay hesap kodu uydurmaz.

### 2. Belge ve Kalem Cikarimi

- Text PDF, XML, Excel ve CSV kaynaklarinda OCR kullanmadan once parser denenir.
- Fatura tarihi, belge no, VKN/TCKN, tutar ve KDV oranlari cikarilir.
- Fatura kalemleri ham satir olarak saklanir.
- Marka/model satirlari kategoriye cevrilir. Ornek: `Urban Care` kisisel
  bakim/kozmetik, `Rexton RLi 20` isitme cihazi adayi.

### 3. Is Alani Uygunluk Kontrolu

- Mukellef faaliyet/NACE bilgisi ve isyeri adresi uygunluk sinyali olarak
  kullanilir.
- Elektrik, su, internet, kira, e-fatura servisi gibi genel giderler ayri
  siniflandirilir.
- Kisisel bakim, market veya faaliyetle zayif iliskili belgeler supheli olarak
  isaretlenir.
- Supheli veya is alani disi belgelerde fis taslagi uretilir ama export'a
  alinmaz.

### 4. Fis Uretimi

- Alis fisinde gider ve 191 KDV borc, 320 cari alacak olur.
- Satis fisinde 120 cari borc, gelir ve 391 KDV alacak olur.
- Banka odeme fisinde 320 cari borc, banka hesabi alacak olur.
- Karisik KDV senaryosu dengeli uretilir ama manuel kontrol riski tasir.
- Tevkifat, iade, istisna, OIV/OTV ve eksik cari senaryolari kontrol kuyruğuna
  duser.

### 5. Export

- Universal journal CSV uretir.
- Zirve testinde hangi kolonlarin kabul edildigi kaydedilir.
- Calismayan formatlar hata mesaji ve eksik kolonla birlikte belgelenir.
- Export paketine sadece risk bayraksiz veya mustavir politikasiyla izinli
  kayitlar girer.
- Gercek Zirve testinden gecmeyen format tamam sayilmaz.

## Kabul Kriterleri

- Mukellef karti ve hesap plani olmadan canli belge yukleme/isleme yapilmaz.
- 3 hesap plani dosyasi parse edilebilir.
- Detay hesap ayrimi kontrol edilebilir.
- 120/320 cari adaylari raporlanir.
- Alis, satis ve banka fisleri dengelidir.
- Karisik KDV fisinde `mixed_vat_manual_review` risk bayragi vardir.
- Marka/model iceren satirlar gerekceli kategori adayina cevrilir.
- Is alani disi veya supheli belgeler export paketine girmez.
- Mustavir duzeltmeleri sonraki benzer kayitlarda oneriyi etkileyebilir.
- En az bir Zirve import rotasi basarili sonuc verir.
