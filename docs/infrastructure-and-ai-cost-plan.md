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

Alinan ilk sunucu:

- 4 Core 2.70 GHz
- 4 GB DDR4 RAM
- 100 GB NVMe SSD
- GPU yok

Bu kurulum hafif pilot icin kabul edilir. Worker sayisi, backup saati ve disk
kullanim uyari esikleri bu kaynak sinirina gore temkinli ayarlanmalidir. AI
modeli calistirmak icin GPU, Ollama, vLLM veya benzeri bir runtime kurulmayacak.

## AI Kullanim Karari

Baslangic karari:

- Kendi sunucuda model calistirma yok.
- Kucuk sorgular icin bile once kural motoru ve parser calisir.
- Belirsiz kalemlerde dis AI API'ye dusuk hacimli, kontrollu batch istek atilir.
- Her istek JSON schema ile sinirlanir ve mustavir politikasina yardimci olacak
  kategori/gerekce, fis taslagi aciklamasi veya politika sablonu uretir.
- Gecmis veri olmayan yeni mukellefte AI, `ai_assisted_draft` modunda ilk fis
  taslagini hazirlamaya yardim edebilir; bu sonuc export yetkisi vermez.

AI API'ye uygun isler:

- Marka/model satirindan urun kategorisi adayi cikarma.
- Belirsiz kaleme kisa uygunluk gerekcesi yazma.
- Banka aciklamasini genel kategoriye ayirma.
- Tedarikci/aciklama metnini normalize etme.

AI API su isleri yapmayacak:

- Nihai muhasebe hesabina karar verme.
- Belgenin gider yazilip yazilamayacagina kesin karar verme.
- KDV, tevkifat, iade, istisna gibi riskli kararlar icin nihai politika koyma.
- Zirve export formatini kesinlestirme.

## Maliyet Politikasi

Ilk hedef aylik AI maliyetini dusuk tutmaktir:

1. Statik kural eslesirse AI cagrisi yok.
2. Bilinen tedarikci ve bilinen kategori varsa AI cagrisi yok.
3. Belirsiz marka/modelde dusuk tokenli API sorgusu atilir.
4. API guveni dusukse sonuc mustavir review'a duser.
5. Her mukellef/ofis icin aylik AI cagrisi ve karakter/token cap'i tutulur.
6. Soguk baslangic demo/pilot istekleri ayri izlenir; satis demosu icin yapilan
   AI cagrilari production otomasyon basarisi gibi raporlanmaz.

Kalite olcumu:

- Eski OpenAI/Gemini/Manus benchmark sorusu urun kararindan cikarildi.
- Ana basari `draft_success`: AI/motor gerekli fis taslagini uretebiliyor mu.
- `automation_success`: mustavir politikasiyla dogrudan export-ready olabilen
  islem oranidir ve ayri izlenir.

Usage ledger ilk surumu:

- `POST /phase0/store/ai-usage` manuel usage event kaydi yazar.
- `POST /phase0/store/ai-usage/summary` client bazinda tahmini toplam maliyet,
  kullanilan/atlanmis cagri sayisi ve aylik cap kalanini dondurur.
- `POST /phase0/classification/product` `client_id` ile cagrilirsa usage event
  otomatik kaydedilir.
- Bu rakamlar provider faturasinin yerine gecmez; erken MVP'de maliyet cap'i ve
  karar izi icin ic tahmindir.

## Sunucu Secimi

Ilk canli deneme icin pratik karar:

- GPU'suz sunucu: ana uygulama, PostgreSQL, dosya saklama ve worker icin yeterli.
- Online API: sadece belirsiz/benchmark isleri icin kullanilir.
- Dedicated GPU veya saatlik GPU: baslangic kapsaminda yok.

Bu nedenle ilk satin alma karari GPU'suz sunucu olmalidir. Model calistirma
maliyeti ve operasyon karmasasi, baslangic hacminde API batch sorgularindan daha
avantajli gorunmuyor.

## Normal Sunucu Kisa Liste

Mevcut paket 4 Core / 4 GB RAM / 100 GB NVMe oldugu icin ilk pilot dusuk
hacimli tutulur. Ek disk/storage ve RAM, belge hacmi veya worker concurrency
artarsa ilk buyutulecek kaynaklardir.

## 90 Gun Ham Belge Saklama

Ham PDF/XML/ekstre dosyalari 90 gun aktif kalir. 90. gun sonunda sistem
musavire indirme/arsivleme linki, silme onayi ve 90 gun uzatma secenegi sunar.
Sessiz otomatik silme uygulanmaz. Metadata, fis taslagi, mustavir karari,
learning event ve export izi korunur.

Bu karar:

- Storage maliyetini dusurur.
- Server tasimasini kolaylastirir.
- 100 GB diskle baslayan pilotta disk baskisini kontrol altinda tutar.
- Backup politikasini ham belge yerine metadata/dump agirlikli hale getirir.

## Sonraki Teknik Adim

Sonraki teknik adim mevcut 4 GB RAM / 100 GB diskli sunucu icin manuel backup
plani yazmak, backup'i ayni makine disina tasimak, env secret/TLS/firewall
ayarlarini tamamlamak ve disk kullanim uyarilarini operasyon ekranina
baglamaktir.
