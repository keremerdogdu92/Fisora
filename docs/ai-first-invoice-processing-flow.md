# AI-first mukellef ve fatura isleme akisi

Durum: Taslak, 2026-07-03

Bu dokuman mukellef olusturmadan fatura taslaginin onaya gelmesine kadar sistemin nasil calismasi gerektigini netlestirir. Ana hedef, musavirin isini azaltan AI-first bir akis kurmak; ama kanitli ogrenme, yasal kurallar ve ihrac/aktarim guvenligi varken bunlari AI'in onune dogru sirayla koymaktir.

## Temel kararlar

1. Vergi levhasi alanlari pilot icin zorunlu kabul edilir.
   Parser TCKN/VKN, unvan, NACE/faaliyet ve adres alanlarini okumaya calisir. Okuyamazsa bu "normal kabul edilen eksik veri" degil, onboarding eksigi olarak gorulur ve musavir ekranda tamamlar. AI-first fatura isleme icin en az vergi kimligi, unvan/gorunen ad, NACE/faaliyet ve hesap plani tamamlanmis olmalidir.

2. NACE/faaliyet contexte zorunlu girer.
   NACE bir kere normalize edilip arastirildiktan sonra sonuc yerel bilgi havuzunda saklanir. Ayni NACE baska mukellefte gelirse tekrar internet arastirmasi yapmadan kayitli profil kullanilir. Yeniden arastirma sadece manuel refresh, cache boslugu veya dusuk kaliteli eski kayit varsa calismalidir.

3. AI-first varsayimdir.
   Yeterince guvenilir ogrenilmis kural veya birebir eslesen yuksek guvenli gecmis karar yoksa sistem statik motor dusuk guven verdi diye durmamalidir. AI'a yon, faaliyet, NACE ozeti, hesap plani adaylari, fatura satirlari ve cari adaylari verilerek cozum istenir. Gerekirse arastirma AI'i devreye girer.

4. Yasal/muhasebesel sert kurallar onde gelir.
   KDV ayrimi, belge yonu, ihrac/aktarim hazirligi, borc-alacak dengesi, indirilemez gider gibi sert riskler AI sonucu ne olursa olsun kontrol edilir. Guven yoksa taslak olusur ama review gate acik kalir.

5. Ogrenme AI'i azaltir, denetimi kaldirmaz.
   Musavirin onaylari ve duzeltmeleri ayni cari, ayni urun/hizmet, ayni hesap mantigi icin sonraki onerileri guclendirir. Tek bir karar kalici otomasyon icin yeterli sayilmamalidir; tekrarli ve tutarli onaylar yuksek guvenli ogrenme haline gelince AI/research maliyeti azaltilabilir.

## Uctan uca akis

### 1. Mukellef olusturma

Musavir mukellef olusturma ekranina gelir ve vergi levhasini yukler. Sistem vergi levhasi dosyasini saklar, metin/OCR katmanindan parser calistirir ve su alanlari doldurmaya calisir:

- TCKN/VKN veya normalize vergi kimligi
- Unvan, ticari unvan veya gorunen ad
- Vergi dairesi
- NACE kodu ve faaliyet aciklamasi
- Isyeri adresleri

Bu alanlar eksikse musavir ayni ekranda tamamlar. Dokumanin ham hali de parse sonucu da mukellef onboarding kaydinin parcasi olarak kalmalidir.

### 2. NACE/faaliyet arastirmasi

Buradaki NACE bizim mukellefin faaliyetidir, karsi firmanin NACE'i degildir.

Sistem normalize NACE kodu ve faaliyet aciklamasini arastirma ajanina verir. Ajanin gorevi sadece guzel bir metin yazmak degil; faaliyeti muhasebe diliyle anlasilir hale getirmek, faaliyet tagleri uretmek, hangi belge/urun tiplerinin normal veya supheli olduguna dair context olusturmaktir.

Beklenen cikti:

- Musavir ve ofis calisani icin sade Turkce faaliyet ozeti
- Faaliyet tagleri
- Sektor/alt sektor sinyali
- Fatura satiri yorumlamada kullanilacak faaliyet contexti
- Belge siniflandirmada review sebebi uretebilecek risk notlari

NACE arastirmasi fatura tarafinda yeniden ayni NACE icin internete cikmamalidir. Fatura islemede bu profil context olarak kullanilir.

### 3. Hesap plani yukleme

Vergi levhasi isi tamamlandiktan sonra hesap plani yuklenir. Ham hesap plani dosyasi saklanir, parser hesap kodlarini ve yardimci bilgileri normalize eder:

- Hesap kodu ve hesap adi
- Detay hesap olup olmadigi
- Cari hesaba ait olabilecek VKN/TCKN, IBAN, vergi dairesi gibi ipuclari
- Hesabin semantik rolu: stok, gider, satis geliri, KDV, musteri, satici vb.
- KDV orani veya kullanim tagleri gibi yardimci sinyaller

Hesap plani sadece dosya olarak saklanmaz; fatura islemede AI'a verilecek aday havuzunun ana kaynagi haline gelir.

### 4. Dosyalari mukellef ayarlarinda gosterme

Yapilacak is: Mukellefe tiklaninca mukellef ayarlari icinde vergi levhasi ve hesap plani gorulebilmeli/indirilebilmeli. Bu acil degil ama onboarding guveni icin backlog'a girmelidir.

### 5. Belge yukleme yetkisi

Fatura yukleme iki yoldan olur:

- Mukellef kendi sifresiyle kendi ekranina girer ve belge yukler.
- Musavir mukellef listesinden mukellefi secer, "bu mukellefe git" ile delegated client session acar ve o mukellef adina belge yukler.

Bu iki akis ayni belge isleme motorunu kullanir. Kritik fark audit bilgisidir. Belge kaydinda sunlar net tutulmalidir:

- Belge hangi mukellef workspace'ine yuklendi
- Etkin kullanici kimdi
- Yukleyen gercek aktor mukellef mi, musavir mi
- Musavir delegated session ile girdiyse `delegated_by_user_id`
- `delegated_client_id`
- Yukleme zamani ve kaynak ekrani/intake category

Mevcut auth akisi delegated session bilgisini tasiyor; dokuman metadata tarafinda bunun acik ve sorgulanabilir sekilde kalici hale getirilmesi gereksinimdir. Sonradan "bu belgeyi kim yukledi" sorusu tartismasiz cevaplanmalidir.

### 6. Fatura yukleme ve yon secimi

Faturalar yon secilerek yuklenir:

- Alis faturasi alis ekranindan
- Satis faturasi satis ekranindan

Bu secim ilk intake sinyalidir. Sistem yine de faturanin iceriginden yon kontrolu yapar. Belgedeki duzenleyen/alici vergi kimligi, mukellef unvani, fatura tipi ve intake category birlikte degerlendirilir. Secilen yon ile icerik catismasi varsa taslak uretilse bile review gate acilir.

### 7. Parse sonucu

Fatura PDF, text PDF, XML veya benzeri formatla gelebilir. Parse adimi su bilgileri cikarmaya calisir:

- Duzenleyen/satici bilgileri
- Alici bilgileri
- Vergi kimlikleri
- Fatura tarihi, numarasi, senaryo/tip bilgisi
- Satir aciklamalari, miktar, birim, tutar
- KDV oranlari ve KDV tutarlari
- Genel toplamlar
- Metin kaynaklari ve parse guven sinyalleri

Yani amac sadece birkac alana bakmak degildir; muhasebe onerisi icin yeterli bir yapisal fatura modeli olusturmaktir. Ancak her faturada tum alanlar ayni kalitede gelmez. Elektrik, dogal gaz, internet, telefon ve su faturalarinda satir/ozet alanlari genel e-fatura tiplerinden farkli olabilir. Bu belgelerde sistem satir aciklamasi, saglayici adi, belge tipi ve tutar/KDV yapisini birlikte kullanmali; format farki dusuk guven veya review sebebi olarak gorulebilmelidir.

### 8. Yon kontrolu ve hesap adayi daraltma

Parse sonrasinda sistem fatura yonunu tekrar kontrol eder. AI'a hesap plani tum karmasik haliyle verilmemelidir; yon ve belge tipiyle daraltilmis adaylar verilmelidir.

Ornek:

- Satis tarafinda: 600 satis gelirleri, 391 hesaplanan KDV, 120 musteri hesaplari ve ilgili detaylar
- Alis tarafinda: 153 stok, 7xx gider, 191 indirilecek KDV, 320 satici hesaplari ve ilgili detaylar
- Ozel durumlarda: indirilemeyen KDV, sabit kiymet, kanunen kabul edilmeyen gider veya review gerektiren hesap gruplari

Bu daraltma deterministik motorun gorevidir. AI bu aday havuzundan secim yapar veya adaylar yetersizse bunu gerekceyle belirtir.

### 9. AI-first karar patikasi

Sistem once elindeki kesin bilgileri ve yuksek guvenli ogrenmeleri kontrol eder:

1. Birebir ve yuksek guvenli ogrenilmis kural var mi?
2. Ayni cari + ayni urun/hizmet + ayni yon icin tekrarli tutarli onay var mi?
3. Sert muhasebe kuralinin sonucu acik mi?

Bu sorularin cevabi guvenliyse sistem bu bilgiyi one alir ve AI/research maliyetini azaltabilir. Degilse AI-first akis calisir.

AI'a verilen context:

- Mukellef unvani, vergi kimligi ve faaliyet bilgisi
- NACE kodu, NACE arastirma ozeti ve faaliyet tagleri
- Fatura yonu ve yon guven sinyali
- Parse edilmis fatura satirlari
- Satici/alici/cari adaylari
- Yonle filtrelenmis hesap plani adaylari
- Gecmis ogrenme sinyalleri

AI'dan beklenen cikti:

- Fatura kategori/oneri sinifi
- Uygun hesap veya hesap aday secimi
- Cari esleme onerisi
- Gerekce
- Guven skoru
- Risk flag'leri
- Gerekirse `needs_research` ve arastirma sorgusu

### 10. Urun/marka/faaliyet arastirmasi

Fatura satirindaki "urun adi" her zaman gercek urun adi olmayabilir; marka, model, hizmet paketi, abonelik aciklamasi veya teknik kod olabilir. Arastirma ajaninin fatura tarafindaki isi karsi firmanin NACE'ini kesin bulmak degildir. Burada ana soru sudur:

"Bu satir veya marka/hizmet neye benziyor ve mukellefin faaliyeti icinde hangi muhasebe davranisina daha yakin?"

Arastirma ajanina genelde su bilgiler gider:

- Satir aciklamasi/urun-hizmet ifadesi
- Satici unvani veya marka ipucu
- Mukellefin NACE/faaliyet contexti
- Fatura yonu

Bu adim su durumlarda calismalidir:

- AI satira yeterince guvenemiyorsa
- Urun/marka ilk kez goruluyorsa
- Statik siniflandirma ile faaliyet contexti uyusmuyorsa
- Belge tipi genel faturadan farkliysa
- Sabit kiymet, stok, gider, hizmet, indirilemez gider ayrimi belirsizse

Arastirma sonucu da cache'lenmelidir. Ayni marka/urun/hizmet tekrar geldiginde once bilgi havuzu kullanilir.

### 11. NACE ile urun arastirmasi catismasi

NACE/faaliyet contexti ile urun/marka arastirmasi farkli yone isaret ederse otomatik "biri kazanir" kuralimiz olmamali. Siralama soyle olmalidir:

1. Sert yasal/muhasebesel kural
2. Birebir, yuksek guvenli ve ilgili kapsamli ogrenilmis kural
3. Fatura yonu ve hesap plani aday uygunlugu
4. AI + urun/marka arastirmasi gerekcesi
5. NACE/faaliyet contextiyle uyum

Catismada sistem taslak uretmeli ama review sebebi yazmalidir. Ornek: "Satir arastirmasi stok gibi gorunuyor, ancak mukellef faaliyet profili hizmet agirlikli; hesap secimi onay gerektiriyor."

### 12. Cari esleme ve yeni cari onerisi

Parse sonucu cari bilgisi cikarsa sistem once hesap planindaki cari adaylarla eslestirir:

- Vergi kimligi birebir eslesiyorsa en guclu sinyal
- IBAN birebir eslesiyorsa cok guclu sinyal
- Unvan benzerligi tek basina daha riskli sinyal

Karsi firma ismini her zaman cok dogru cikaramayabiliriz. Bu nedenle sadece unvan benzerligiyle sessiz otomasyon yapilmamali; review sebebi kalabilir. Uygun cari bulunamazsa deterministik motor yeni cari onerir. Alis icin genelde 320, satis icin 120 grubu kullanilir. AI burada hangi cari mantiginin uygun oldugunu gerekcelendirir, ama yeni hesap kodu uretme standardi deterministik olmalidir.

### 13. Taslak fis ve UI

Sistem sonucunda musavirin onune bir taslak gelir:

- Belge yonu
- Secilen gider/stok/satis hesabi
- Secilen veya onerilen cari
- KDV hesaplari
- Satir gerekceleri
- AI guveni
- Arastirma ozeti
- Review sebepleri
- Export/aktarim hazirlik durumu

Musavir taslagi aynen onaylayabilir veya manuel degistirebilir. Degisiklik hem o belge kararina yazilir hem de ogrenme olayina donusur.

### 14. Ogrenme

Ogrenme iki seviyede dusunulur:

1. Dogal ogrenme:
   Musavir belgeyi duzelttikce sistem ayni cari, ayni urun/hizmet, ayni yon ve benzer faaliyet baglaminda sonraki onerileri iyilestirir.

2. Acik kural:
   Musavir bilerek "bu cariden gelenler her zaman stoktur" gibi bir kural yazabilir. Bu kural kapsam, kosul ve istisna mantigiyla saklanmalidir. Cok farkli durum olursa yine review gate acilabilmelidir.

Yuksek guvenli ogrenme olusmadan AI/research devreden cikarilmamalidir. Ogrenme guveni yeterince birikince sistem once o kurali uygular, AI'i sadece audit/gerekce veya dusuk guven durumunda cagirir.

### 14.1 Musavir ogrenme UX plani

Bu akisin hedefi musavire cok butonlu bir "programi egit" ekrani acmak
degil; normal review isini yaparken sistemin ne ogrendigini netlestirmektir.
Buton sayisi az tutulmali, asil guven "sistem bunu nasil anladigini" gosteren
onay formundan gelmelidir.

Iki ayri ogrenme yolu vardir:

1. Otomatik tekrar sinyali:
   Musavir hic not yazmasa bile ayni mukellef, ayni cari/VKN, ayni belge yonu
   ve ayni urun/hizmet mantiginda tutarli kararlar birikirse sistem bunu
   "kural adayi" olarak fark eder. Ornek: ayni stok faturasi 3 kez ayni sekilde
   onaylandiysa 4. benzer belgede veya 3. onaydan hemen sonra musavire
   "Bu faturadaki islemi kural olarak kaydetmek ister misiniz?" uyarisi
   gosterilebilir.

2. Acik musavir notu:
   Musavir bilincli olarak "bundan sonra bu VKN'den gelen faturalar kargo
   gideridir" veya "bu mukellefte Kolay Soft e-fatura hizmeti 770.05'e gider"
   gibi bir not yazar. Bu not tek alan olmali: `Karar notu` veya
   `Egitim notu`. Sistem notu, fis uzerindeki son degisikliklerle birlikte
   yorumlar ve yapilandirilmis kural adayina cevirir.

Otomatik tekrar sinyalinde onerilen karar secenekleri:

- `Evet`: Bu karari kural adayi olarak ac ve onay formunu goster.
- `Hayir`: Bu belge icin kural olusturma, normal review akisiyle devam et.
- `Tekrar onerme`: Bu benzerlik anahtari icin ayni uyariyi bastir.

Acik musavir notu akisi:

1. Musavir fisi duzeltir veya onaylar.
2. Tek not alanina gerekcesini yazar.
3. `Egitim notunu kaydet` aksiyonu notu ve fis farkini birlikte inceler.
4. Sistem bir modal/form acar ve "bunu boyle anladim" diye yapilandirilmis
   kural adayini gosterir.
5. Musavir form alanlarini gerekirse duzeltir.
6. Musavir sonucu `Kural olarak kaydet` veya `Benzerlerde oner` olarak secer.

Formun temel alanlari:

```text
Kapsam: Bu mukellefe ozel / Musavir ofisi geneli / Firma geneli aday
Tetikleyici: Yurtiçi Kargo / VKN 9860008925 / alis faturasi
Uygulama: Bu caride 320.01.888 kullanilacak; gider hesabi 760.03.010 olacak
Guvenlik: Ilk uygulamalarda musavir kontrolu iste
Durum: Kural adayi
```

Kapsam karari keskin olmalidir:

- Mukellefe ozel: Ayni mukellef icinde uygulanir. Varsayilan guvenli secim budur.
- Musavir/ofis geneli: Ayni musavir ofisinin diger mukelleflerinde once oneri
  olarak cikar; yeterli guven ve celiskisiz tekrar olmadan otomasyon olmaz.
- Firma geneli aday: Urun/hizmet veya kanuni muhasebe mantigi genelse sadece
  merkezi kural kutuphanesine aday olur; tek musavir karariyla aktif olmaz.

`Kural olarak kaydet` ile `Benzerlerde oner` farki:

- `Kural olarak kaydet`: Kapsam, tetikleyici ve uygulama yeterince netse daha
  guclu kural adayi olusur. Pilot boyunca ilk uygulamalarda yine musavir onayi
  istenir; direkt export ready verilmez.
- `Benzerlerde oner`: Sistem sonraki benzer belgelerde fisi bu mantikla hazirlar
  veya one cikarir, ama baska bir guvenli kural ya da yeterli skor yoksa export
  ready yapmaz.

Export guvenlik karari:

- Pilot icinde yeni ogrenilen kural tek basina direkt export ready yapmamalidir.
- Kural aktif olsa bile ilk uygulamalarda musavir kontrolu istenir.
- Pilot cikisinda, tekrarli ve celiskisiz kural icin ayrica onay alinarak
  otomasyon seviyesi artirilabilir.
- Direction conflict, dusuk parse/OCR guveni, eksik VKN/cari kimligi, KDV
  tutarsizligi veya faaliyet-urun catismasi varsa kural otomasyon degil, sadece
  oneri olur.

UI prensibi:

- Yeni buton sayisi artirilmaz; ana ekranda tek not/egitim aksiyonu yeterlidir.
- Ayrintili secimler ana review ekraninda degil, sadece modal/form icinde
  gosterilir.
- Form dili "kural JSON'u" gibi degil, musavirin okuyacagi muhasebe cumleleriyle
  yazilir.
- Sistem sadece "not kaydedildi" dememeli; "bu nottan sunu anladim" diyerek
  tetikleyici, kapsam ve uygulamayi gostermelidir.

## AI kalite farkini nasil anlayacagiz?

Mevcut sistemde bazi sinyaller zaten var: statik siniflandirma guveni, AI kullanildi bilgisi, provider, AI guveni, risk flag'leri, review reason'lari, research confidence, hesap aday uygunlugu, export hazirligi, musavir duzeltmesi ve learning event.

Ama kaliteyi gercekten olcmek icin her belge icin su karsilastirma katmani gerekir:

- Statik motor ne onerdi?
- AI ne onerdi?
- Arastirma sonrasi sonuc degisti mi?
- Musavir finalde neyi onayladi veya degistirdi?
- Hangi alan degisti: cari, ana hesap, KDV, yon, satir aciklamasi?
- AI dogru aday havuzundan mi secti?
- AI gerekcesi NACE/faaliyet ve fatura satiri ile uyumlu muydu?
- Review sebebi gercekten musavir duzeltmesine denk geldi mi?
- Ayni karar kac kez tekrar onaylandi?

Bu metrikler olmadan "AI iyi calisiyor mu" sorusuna sadece tekil orneklerle cevap veririz. Hedef, statik motor, AI, arastirma ve final musavir karari arasindaki farki kaydedip zamanla hangi durumda AI'a, hangi durumda ogrenilmis kurala guvenebilecegimizi olcmektir.

### Karar kalitesi paneli

Belge detayinda teknik JSON gostermek yerine sade bir "Karar kalitesi" paneli olmali. Bu panel pasif kalmali; musavire tekrar AI calistirma butonu gibi davranmamalidir.

Panelde su katmanlar kisa sekilde gorunmelidir:

- Statik motor: urun/hizmet satirini klasik kurallar ne sandi?
- AI: AI hangi kategori, hesap ve cari onerdi?
- Research: arastirma karari guclendirdi mi veya review sebebi mi uretti?
- Sistem final taslagi: musavire gelen hesap/cari/KDV/yon ne?
- Musavir finali: karar aynen onaylandi mi, yoksa hangi alanlar degisti?

Catismalar sade cumleyle yazilmalidir. Ornek: "Faaliyet context'i hizmet agirlikli, urun arastirmasi stok gibi goruyor" veya "Cari unvan benzerligi dusuk; VKN/IBAN eslesmesi yok."

### Musavir final karari ve quality delta

AI'in ilk onerisi sonradan ezilmemelidir. Aksi halde kaliteyi olcemeyiz. Her review/onay sonrasinda belge sonucunda su alanlar kalmalidir:

- `proposal_snapshot`: sistemin review oncesi hesap/cari/yon/KDV taslagi
- `ai_quality_scorecard`: statik, AI, research, context ve sistem final taslagi
- `accountant_final_decision`: musavirin onayladigi nihai karar
- `quality_delta`: musavir neyi degistirdi?

Ornek `quality_delta`:

```json
{
  "changed_fields": ["selected_account_code", "counterparty_account"],
  "account_changed_from": "770.01",
  "account_changed_to": "153.01",
  "counterparty_changed_from": "320.NEW",
  "counterparty_changed_to": "320.01.015",
  "decision": "corrected",
  "learning_candidate": true
}
```

Bu sayede AI'in hesapta mi, caride mi, yonde mi, KDV'de mi yanildigi olculebilir. Research sonrasi karar iyilesiyor mu, statik motor bazi durumlarda AI'dan daha mi iyi, musavir sadece kucuk duzeltme mi yapti yoksa taslagi komple mi degistirdi sorularina veriyle cevap verilir.

### Ogrenilmis kural ne zaman AI'in onune gecer?

Baslangic policy:

- 1 tutarli onay: sadece sinyal. Sonraki belgede "benzer gecmis karar var" diye gosterilir, AI-first devam eder.
- 2 tutarli onay: guclu aday. AI yine calisir ama ogrenilmis karar aday havuzunda one cikar.
- 3 tutarli onay: ayni client + ayni cari + ayni urun/hizmet + ayni yon icin kural AI/research onune gecebilir.
- Acik musavir kurali: kapsam netse direkt one gecer; conflict varsa review gate kalir.

Kuralin AI/research onune gecmesi icin en az su kosullar aranmalidir:

- Ayni mukellef kapsaminda veya acikca ofis politikasi olarak isaretlenmis olmali
- Ayni yon olmali: alis/satis farkliysa uygulanmaz
- Cari guveni yuksek olmali: VKN/IBAN veya ayni counterparty identity key
- Urun/hizmet anahtari benzer olmali: normalize satir, kategori veya research product key
- Hesap/KDV davranisi ayni kalmis olmali
- Sonraki musavir duzeltmeleriyle bozulmamis olmali

Direction conflict, dusuk OCR/parse guveni, eksik VKN/cari kimligi veya faaliyet-urun catismasi varsa kural otomasyon degil, sadece guclu oneri olur.

Kisa karar: AI-first defaulttur. Ogrenilmis kural sadece dar kapsamli, tekrarli ve celiskisizse AI/research maliyetini azaltir. Musavir acik kural yazarsa daha hizli one gecer ama conflict gate kalkmaz.

## Mevcut durum ve eksikler

Su an uygulamada olan ana parcalar:

- Vergi levhasi onboarding attachment olarak saklaniyor.
- Vergi levhasi parse edilip mukellef profiline yazilabiliyor.
- Hesap plani yuklenip parse edilerek hesap adaylari olusuyor.
- NACE arastirmasi cache'li calisacak sekilde tasarlanmis.
- Fatura yuklemesi processing job uretir.
- Onboarding dosyalari processing job uretmez.
- Belge yonu intake ve fatura icerigiyle kontrol edilir.
- AI'a faaliyet/NACE, hesap adaylari ve cari adaylari context olarak verilebilir.
- AI ciktisi aday listeleriyle sinirlanir.
- Marka/urun arastirmasi ihtiyaca gore devreye girebilir ve cache kullanir.
- Musavir onayi/duzeltmesi review ve learning event olarak kaydedilebilir.
- Export/aktarim icin denge ve review gate kontrolleri vardir.

Net eksikler / yapilacaklar:

- Vergi levhasi core alanlari eksikse musavire tamamlatan zorunlu onboarding gate keskinlestirilmeli.
- Vergi levhasi ve hesap plani mukellef ayarlarinda gorulebilir/indirilebilir olmali.
- Delegated upload metadata belge kaydinda acik alanlar olarak saklanmali.
- NACE cache kullanimi UI/operasyon seviyesinde gorulebilir olmali; ayni NACE icin gereksiz internet arastirmasi engellenmeli.
- Urun/marka satiri parse guveni ve karsi firma kimligi guveni ayri ayri gosterilmeli.
- NACE/faaliyet ile urun/marka arastirmasi catismasi UI'da anlasilir review sebebi olarak cikmali.
- AI kalite scorecard'i eklenmeli: statik, AI, research ve final musavir karari karsilastirilmali.
- Yuksek guvenli ogrenme kurallarinin ne zaman AI/research yerine gececegi net esiklerle belirlenmeli.

## Kisa ozet

Senin anlattigin ana akis dogru: vergi levhasi ve hesap plani mukellefin muhasebe contextini kuruyor; fatura parse ediliyor; yon kontrol ediliyor; hesap plani yone gore daraltiliyor; AI satir, faaliyet ve hesap adaylarini birlikte degerlendiriyor; gerekirse urun/marka arastirmasi yapiliyor; cari eslesiyor veya yeni cari oneriliyor; musavir onay/duzeltme ile sistemi ogretiyor.

En kritik farklar sunlar:

- Vergi levhasi parser "kesin okur" diyemeyiz; ama eksik kalmasini kabul etmeyip musavire tamamlatmaliyiz.
- NACE arastirmasi karsi firmanin NACE'i degil, bizim mukellefin faaliyet contextidir.
- Urun/marka arastirmasi karsi firma kimligini kanitlamaz; satirin muhasebe davranisini anlamaya yardim eder.
- NACE ile urun arastirmasi catistiginda sessiz kazanan yoktur; taslak + review reason gerekir.
- AI'a hesap plani yone gore filtrelenmis verilmelidir.
- AI kalitesini anlamak icin statik/AI/research/final musavir karari birlikte kaydedilmelidir.
