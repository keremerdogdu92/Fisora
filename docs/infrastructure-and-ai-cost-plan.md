# Infrastructure and AI Cost Plan

## Karar

Fisora ilk canli kurulumda kendi kiralik sunucu uzerinde baslayabilir. Bu
modelde ham belgeler sunucudaki ayrilmis storage volume'da, metaveri ve isleme
sonuclari PostgreSQL'de tutulur. AI ise ilk etapta zorunlu dependency degil;
statik kural motoru ve parser kapali devre calismaya devam eder.

## Onerilen Ilk Kurulum

Baslangic icin GPU'suz dedicated veya guclu VPS yeterlidir:

- Nginx
- Docker Compose
- Next.js frontend
- FastAPI backend
- PostgreSQL
- Redis
- Python worker
- Local encrypted document volume
- Harici/gece backup

Bu kurulum fatura yukleme, hesap plani, cari eslestirme, fis taslagi, review ve
export paketi icin yeterlidir. Offline model zorunlu degildir.

## Offline AI Kullanimi

Kucuk offline model su isler icin kullanilabilir:

- Marka/model satirindan urun kategorisi adayi cikarma.
- Belirsiz kaleme kisa uygunluk gerekcesi yazma.
- Banka aciklamasini genel kategoriye ayirma.
- Tedarikci/aciklama metnini normalize etme.

Offline model su isleri yapmayacak:

- Nihai muhasebe hesabina karar verme.
- Belgenin gider yazilip yazilamayacagina kesin karar verme.
- KDV, tevkifat, iade, istisna gibi riskli kararlar.
- Zirve export formatini kesinlestirme.

## Maliyet Politikasi

Ilk hedef aylik AI maliyetini dusuk tutmaktir:

1. Statik kural eslesirse AI cagrisi yok.
2. Bilinen tedarikci ve bilinen kategori varsa AI cagrisi yok.
3. Belirsiz marka/modelde once offline kucuk model denenir.
4. Offline model guveni dusukse online provider veya mustavir review devreye girer.
5. Her mukellef/ofis icin aylik AI cagrisi ve karakter/token cap'i tutulur.

## Sunucu Secimi

Ilk canli deneme icin pratik karar:

- GPU'suz sunucu: ana uygulama, PostgreSQL, dosya saklama ve worker icin yeterli.
- Saatlik GPU veya online API: sadece belirsiz/benchmark isleri icin kullanilir.
- Dedicated GPU: ancak belge hacmi arttiginda ve offline model surekli calisacaksa
  degerlendirilir.

Bu nedenle ilk satin alma karari GPU'suz sunucu olmalidir. Dedicated GPU,
baslangic icin maliyet hedefini gereksiz zorlar.

## Sonraki Teknik Adim

Belge upload modeli once local storage adapter ile dogrulanacak. Sonra ayni
davranis production'da sunucu volume'u veya S3-compatible object storage'a
tasinarak korunacak.
