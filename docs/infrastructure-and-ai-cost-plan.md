# Infrastructure and AI Cost Plan

## Karar

Fisora ilk canli kurulumda kendi kiralik sunucu uzerinde baslayabilir. Bu
modelde ham belgeler sunucudaki ayrilmis storage volume'da, metaveri ve isleme
sonuclari PostgreSQL'de tutulur. Kendi sunucuda AI modeli calistirma baslangic
kapsamindan cikarilmistir; AI sadece dis API veya batch sorgu maliyeti makul
oldugunda devreye girer.

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
export paketi icin yeterlidir. AI modeli calistirmak icin GPU, Ollama, vLLM veya
benzeri bir runtime kurulmayacak.

## AI Kullanim Karari

Baslangic karari:

- Kendi sunucuda model calistirma yok.
- Kucuk sorgular icin bile once kural motoru ve parser calisir.
- Belirsiz kalemlerde dis AI API'ye dusuk hacimli, kontrollu batch istek atilir.
- Her istek JSON schema ile sinirlanir ve muhasebe karari yerine sadece
  kategori/gerekce uretir.

AI API'ye uygun isler:

- Marka/model satirindan urun kategorisi adayi cikarma.
- Belirsiz kaleme kisa uygunluk gerekcesi yazma.
- Banka aciklamasini genel kategoriye ayirma.
- Tedarikci/aciklama metnini normalize etme.

AI API su isleri yapmayacak:

- Nihai muhasebe hesabina karar verme.
- Belgenin gider yazilip yazilamayacagina kesin karar verme.
- KDV, tevkifat, iade, istisna gibi riskli kararlar.
- Zirve export formatini kesinlestirme.

## Maliyet Politikasi

Ilk hedef aylik AI maliyetini dusuk tutmaktir:

1. Statik kural eslesirse AI cagrisi yok.
2. Bilinen tedarikci ve bilinen kategori varsa AI cagrisi yok.
3. Belirsiz marka/modelde dusuk tokenli API sorgusu atilir.
4. API guveni dusukse sonuc mustavir review'a duser.
5. Her mukellef/ofis icin aylik AI cagrisi ve karakter/token cap'i tutulur.

## Sunucu Secimi

Ilk canli deneme icin pratik karar:

- GPU'suz sunucu: ana uygulama, PostgreSQL, dosya saklama ve worker icin yeterli.
- Online API: sadece belirsiz/benchmark isleri icin kullanilir.
- Dedicated GPU veya saatlik GPU: baslangic kapsaminda yok.

Bu nedenle ilk satin alma karari GPU'suz sunucu olmalidir. Model calistirma
maliyeti ve operasyon karmasasi, baslangic hacminde API batch sorgularindan daha
avantajli gorunmuyor.

## Normal Sunucu Kisa Liste

Baslangic icin iki pratik secenek:

- Ekonomik root/VPS: 8-12 dedicated vCPU, 16-32 GB RAM, 512 GB-1 TB NVMe.
- Daha kontrollu dedicated: 64 GB RAM, 2 x NVMe, ayrilmis belge volume'u.

Ilk pilotta 2-5 mukellef ve dusuk belge hacmi icin ekonomik root/VPS yeterli
olur. Gercek belge hacmi ve storage ihtiyaci belirginlesince dedicated sunucuya
gecmek daha saglikli olur.

## Sonraki Teknik Adim

Belge upload modeli once local storage adapter ile dogrulanacak. Sonra ayni
davranis production'da sunucu volume'u veya S3-compatible object storage'a
tasinarak korunacak.
