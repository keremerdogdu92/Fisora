# Urun Karar Ozeti

Bu dokuman Faz 0 dogrulama paketini, yeni MVP urun kararlarina baglayan
ana karar ozetidir. Faz 0 halen muhasebe motoru ve Zirve export riskini
azaltir; MVP ise bu motoru uyelikli musteri portali, mustavir kontrolu ve
ogrenen kural katmaniyla urune donusturur.

## Konumlandirma

Urun "tam otonom AI muhasebeci" olarak konumlandirilmamalidir. Dogru tanim:

> AI destekli, mali mustavir kontrollu muhasebe operasyon otomasyonu.

Muhasebe dogrulugu AI'a tek basina birakilmaz. Dogruluk su katmanlarin
birlesimiyle saglanir:

- text/XML/parser katmani
- hesap plani ve cari eslestirme
- deterministik muhasebe fis motoru
- uygulama geneli kural kutuphanesi
- NACE/faaliyet uygunluk kontrolu
- marka/modelden urun kategori siniflandirmasi
- mustavir politikasi ve onay izi
- mustavir duzeltmelerinden ogrenme

AI nihai "gider yazilir/yazilmaz" veya "kesin kayit at" karari vermez. AI'in
rolu belge/urun siniflandirmasi, belirsizlik aciklamasi, guven skoru ve gerekce
uretmekle sinirlidir.

## MVP Urun Kararlari

- Serbest uyelik olmayacak; kullanicilar mustavir/ofis tarafindan acilacak.
- Her kullanici bastan en az bir mukellefe baglanacak. Mukellef eslesmesi yoksa
  fatura yukleme izni olmayacak.
- Minimum mukellef paketi: mukellef karti, VKN/TCKN, faaliyet/NACE veya faaliyet
  aciklamasi, isyeri adresi ve Zirve hesap plani.
- Gecmis yevmiye, muavin veya fis exportu zorunlu degil; varsa baslangic
  ogrenmesini hizlandirir.
- Faturadaki karsi taraf ayrica 120/320 cari olarak eslestirilir. Bulunamazsa
  belge kontrol kuyruguna duser.
- Sistem mukellef ozel detay hesap kodu uydurmaz; mevcut Zirve hesap planindan
  secer veya kontrol ister.
- Marka/model satirlari urun kategorisine cevrilir. Ornek: `Urban Care` kisisel
  bakim/kozmetik, `Rexton RLi 20` isitme cihazi adayi.
- Supheli veya is alani disi belgelerde fis taslagi uretilir fakat export
  listesine alinmaz.
- Ilk canli otomasyon politikasi `export kontrollu`: sistem otomatik taslak
  uretir; export'a yalnizca net, dengeli, risk bayraksiz veya mustavir
  politikasinca izinli kayitlar girer.

## Faz 0 Hedefi

Faz 0'in tek hedefi, tam MVP gelistirmeden once Zirve aktarim ve muhasebe fis
uretimi riskini dusurmektir.

Basari kriteri:

- En az bir export rotasiyla Zirve'de hatasiz ve dengeli fis olusmali.
- Risk bayrakli veya is alani disi supheli kayitlar export paketine girmemeli.

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
- Mukellef karti ve hesap planiyla kontrollu pilot denemesi

## MVP Kapsaminda Olanlar

- Uyelikli mukellef portali
- Belge yukleme ve belge durum takibi
- Mustavir review ekrani
- Product classification ve business relevance kontrolu
- Genel kural kutuphanesi + mukellef ozel kurallar
- Mustavir duzeltmelerinden ogrenme
- Kontrollu Zirve export paketi

## Ilk Canli Kapsaminda Olmayanlar

- Tam otonom kesin kayit
- Mustavir onayi olmadan riskli belge exportu
- AI'in tek basina vergi/hukuk yorumu yapmasi
- Dogrulanmamis Zirve direkt entegrasyonu veya COM/OLE otomasyonu
- Gercek musteri verisinin anonimlestirilmeden repoya eklenmesi

## Veri Guvenligi

Gercek musteri verisi anonimlestirilmeden repoya eklenmeyecek. `samples/`
altindaki dosyalar sentetik veya anonimlestirilmis olmalidir. Canli sistemde
belge, fis taslagi, mustavir karari ve export paketleri mukellef bazli yetkiyle
ayrilmalidir.
