# Demo Oncesi Uygulama Plani

## Amac

Bu plan, Docker ve mali mustavirden gelecek dosyalar hazir olmadan once hangi
isleri ilerletebilecegimizi, Docker hazir olunca hangi testlere gececegimizi ve
mustavirden veri gelince hangi saha dogrulamalarini yapacagimizi ayirir.

## Su An Yapilabilecek Isler

Bu basliklar Docker veya gercek mustavir verisi beklemez.

1. AI assisted draft backend durumu
   - Simulation payload'ina `processing_mode` veya benzeri acik mod alani ekle.
   - `conservative`, `ai_assisted_draft`, `controlled_automation` ayrimini
     domain sonucunda tasinabilir hale getir.
   - Kabul: soguk baslangic kaydi AI taslagi olsa bile `review_required` veya
     onay bekleyen durumda kalir.

2. AI gerekce ve export gate UI ayrimi
   - Review ekraninda AI/kural gerekcesi, deterministic denge sonucu ve export
     kapisi nedeni ayri alanlarda gosterilir.
   - Kabul: mustavir bir kaydin neden export'a girmedigini tek ekranda gorur.

3. Sentetik AI benchmark case seti
   - Urban Care, Rexton, Phonak, elektrik, internet, GIB, SGK, POS, karma KDV,
     cari bulunamadi gibi case'ler standart benchmark setine eklenir.
   - Kabul: dis API baglamadan replay/static benchmark calisir.

4. Demo seed verisi
   - Gercek veri gelene kadar iki sentetik mukellef, hesap plani, fatura ve
     banka ekstresi senaryosu hazirlanir.
   - Kabul: mustavir ekraninda alan ici, supheli ve export-ready ornekler ayni
     anda gosterilebilir.

5. Intake manifest sozlesmesi
   - Mustavirden gelen dosyalar icin dosya tipi, mukellef, donem, kaynak ve
     gizlilik durumunu tutan manifest formatina karar verilir.
   - Kabul: gercek dosya geldigi gun hangi dosyanin ne icin kullanilacagi
     karismadan kaydedilebilir.

6. Auth provider karar notu
   - Mock header guard production icin yeterli degil; Clerk/Auth0/custom auth
     gibi seceneklerin artisi/eksisi yazilir.
   - Kabul: server hazir oldugunda login mimarisine baslamak icin karar zemini
     vardir.

## Docker Hazir Olunca Yapilacak Isler

Bu basliklar Docker Desktop veya production sunucu Docker ortami hazir olunca
calistirilir.

1. Compose smoke test
   - PostgreSQL, Redis, backend, worker, frontend ve Nginx container'lari ayaga
     kalkar.
   - Kabul: servisler birbirini network uzerinden gorebilir.

2. PostgreSQL migration smoke
   - `backend/scripts/apply_migrations.py` gercek Postgres'e uygulanir.
   - Kabul: `schema_migrations` tablosu dolu ve checksum kaydi vardir.

3. Production store smoke
   - `FISORA_STORE_BACKEND=postgres` ile client -> upload -> worker -> workspace
     akisi denenir.
   - Kabul: JSON store davranisi Postgres adapter uzerinden bozulmadan calisir.

4. Worker queue smoke
   - Upload sonrasi job olusur, worker parse sonucunu workspace'e yazar.
   - Kabul: job status ekranda gorunur.

5. Backup ve volume kontrolu
   - Document volume, export volume ve backup dizinleri container tarafindan
     yazilabilir olmalidir.
   - Kabul: ham belge database'e yazilmaz, sadece path/hash/metaveri tutulur.

## Mustavirden Veri Gelince Yapilacak Isler

Bu basliklar gercek veya anonimlestirilmis pilot dosyalar geldikten sonra
ilerler.

1. Hesap plani ve cari analizi
   - Zirve hesap plani import edilir.
   - 120/320 cari adaylari, VKN/TCKN, IBAN ve unvan kolonlari incelenir.
   - Kabul: sistem yeni hesap kodu uydurmadan aday secmeye baslar.

2. Gercek/anonim fatura batch kosusu
   - 20-50 fatura lokal ortamda parse edilir.
   - Kabul: tutar, KDV, belge no, tedarikci ve kalemler raporlanir.

3. Banka ekstresi batch kosusu
   - 1-2 Excel/CSV ekstresi GIB, SGK, POS, tahsilat/odeme ve belirsiz satir
     olarak ayrilir.
   - Kabul: riskli satirlar export'a girmez.

4. AI provider izinli benchmark
   - Dis AI API kullanilacaksa once veri onayi veya anonimlestirme netlesir.
   - Kabul: OpenAI/Gemini/Manus adaylari ayni case setinde maliyet ve dogruluk
     acisindan karsilastirilir.

5. Zirve export saha testi
   - Universal CSV veya mustavirin verdigi ornek import formati Zirve'de denenir.
   - Kabul: gercek Zirve testinde calismayan format production export sayilmaz.

## Onerilen Siradaki 3 Is

Bugun icin en mantikli sira:

1. AI assisted draft backend durumunu payload'a eklemek.
2. Review ekraninda AI gerekcesi, deterministic denge ve export gate nedenini
   daha net gostermek.
3. Sentetik AI benchmark/demo case setini genisletmek.

Bu uc is, Docker hazir oldugunda Postgres/worker smoke testine, mustavirden veri
geldiginde de gercek pilot batch kosusuna dogrudan baglanir.
