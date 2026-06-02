# Infrastructure and AI Cost Plan

## Karar

Fisora ilk canli kurulumda kendi kiralik sunucu uzerinde baslayabilir. Bu
modelde ham belgeler sunucudaki ayrilmis storage volume'da, metaveri ve isleme
sonuclari PostgreSQL'de tutulur. Kendi sunucuda AI modeli calistirma baslangic
kapsamindan cikarilmistir; AI sadece dis API veya batch sorgu maliyeti makul
oldugunda devreye girer.

## Onerilen Ilk Kurulum

Baslangic icin GPU'suz cloud server yeterlidir:

- Nginx
- Docker Compose
- Next.js frontend
- FastAPI backend
- PostgreSQL
- Redis
- Python worker
- Local encrypted document volume
- Harici/gece backup

Varsayilan ilk sunucu:

- Turkiye lokasyon
- Radore Cloud Server Infinity varsayimi
- 8 vCPU
- 24 GB RAM
- 250 GB disk
- GPU yok

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

Benchmark altyapisi:

- `POST /phase0/classification/batch-benchmark` statik kural ve provider
  payload'larini ayni kategori/guven/gerekce schema'siyla karsilastirir.
- Ilk benchmark dis API'ye cikmadan replay payload ile yapilir.
- OpenAI/Gemini/Manus adaylari baglandiginda ayni case seti uzerinde dogruluk,
  AI kullanildi mi ve tahmini input karakteri raporlanir.

## Sunucu Secimi

Ilk canli deneme icin pratik karar:

- GPU'suz sunucu: ana uygulama, PostgreSQL, dosya saklama ve worker icin yeterli.
- Online API: sadece belirsiz/benchmark isleri icin kullanilir.
- Dedicated GPU veya saatlik GPU: baslangic kapsaminda yok.

Bu nedenle ilk satin alma karari GPU'suz sunucu olmalidir. Model calistirma
maliyeti ve operasyon karmasasi, baslangic hacminde API batch sorgularindan daha
avantajli gorunmuyor.

## Normal Sunucu Kisa Liste

Baslangic icin pratik secenek:

- 8 vCPU / 24 GB RAM / 250 GB disk: ilk pilot ve dusuk hacimli canli kullanim.
- 16 vCPU / 32 GB RAM: daha fazla worker ve daha rahat PostgreSQL payi.
- Ek disk/storage: belge hacmi arttiginda ilk buyutulecek kaynak.

Ilk pilotta 2-5 mukellef ve text PDF/XML/CSV agirlikli akis icin 8 vCPU / 24 GB
RAM yeterli olur. Ham belgeler 90 gun sonra silinecegi icin uzun vadeli disk
yuku metadata ve export izinden cok daha dusuk kalir.

## 90 Gun Ham Belge Saklama

Ham PDF/XML/ekstre dosyalari 90 gun indirilebilir kalir. 75. gunden sonra
uyari, 90. gun sonunda silme uygulanir. Metadata, fis taslagi, mustavir karari,
learning event ve export izi korunur.

Bu karar:

- Storage maliyetini dusurur.
- Server tasimasini kolaylastirir.
- 250 GB diskle baslamayi daha gercekci yapar.
- Backup politikasini ham belge yerine metadata/dump agirlikli hale getirir.

## Sonraki Teknik Adim

Belge upload modeli once local storage adapter ile dogrulanacak. Sonra ayni
davranis production'da sunucu volume'u veya S3-compatible object storage'a
tasinarak korunacak.
