# Fisero Yedekleme Yaşam Döngüsü Tasarımı

**Tarih:** 2026-07-23  
**Durum:** Kullanıcı tasarımı onayladı; yerel uygulama ve doğrulama tamamlandı  
**Kapsam:** Pilot öncesi geçici veriler, korumalı corpus kontrol noktası ve gerçek pilot yedeklemesinin etkinleştirilmesi

## 1. Mevcut Gerçek

Fisero şu anda pilot öncesi hazırlık aşamasındadır. Operasyon faturaları ve test
kayıtları bilinçli olarak sık sık temizlenmektedir. Henüz sürekli geri
kazanılabilir olması gereken müşteri verisi bulunmamaktadır.

Canlıya alınmış yedekleme servisi bu yaşam döngüsüyle uyumlu değildir:

- sürekli çalışan bir production servisi olarak başlamaktadır;
- canlı sunucuda `FISORA_BACKUP_AGE_RECIPIENT` eksiktir;
- servis yerel ara dosyaları ürettikten sonra hata verip yeniden başlama
  döngüsüne girmektedir;
- tanımlı kopya dizini aynı sunucudaki bir bind mount'tur ve bu nedenle gerçek
  bir off-host kurtarma hedefi değildir;
- normal belgelerin PDF/XML byte'ları pakete alınmamakta, yalnızca dosya
  adı/boyut manifesti tutulmaktadır;
- readiness herhangi bir `postgres-*.sql` dosyasının varlığını başarılı yedek
  kabul etmekte; servis durumu, şifreleme, off-host kopya güncelliği veya restore
  kanıtını kontrol etmemektedir.

Mevcut uygulama ve yerel restore testleri, yedekleme araçlarının geliştirilebilir
ve test edilebilir olduğunu kanıtlar. Güncel canlı yedeğin geri yüklenebilir
olduğunu kanıtlamaz.

## 2. Karar

Yedekleme her zaman açık bir servis değil, yaşam döngüsüne bağlı bir yetenektir.

Fisero üç açık mod kullanacaktır:

1. `disabled`: pilot öncesi geçici veri çalışmaları;
2. `checkpoint`: korumalı corpus için tek ve kontrollü kurtarma noktası;
3. `scheduled`: gerçek pilot verilerinin periyodik tam koruması.

Yetkili runtime ayarı:

```text
FISORA_BACKUP_MODE=disabled|checkpoint|scheduled
```

Boş değer yalnızca gerçek veri pilotu kapalıyken `disabled` kabul edilir.
Bilinmeyen değer bir configuration error'dır.
`FISORA_REAL_DATA_PILOT_ENABLED=true` olduğunda hem `disabled` hem de boş değer
readiness'i bloklar. Sistem yalnız production Compose stack çalışıyor diye
periyodik yedek gerektiğini varsaymamalı; aynı zamanda gerçek verinin yedekleme
yanlışlıkla kapalıyken çalışmasına da izin vermemelidir.

## 3. Yaşam Döngüsü Modları

### 3.1 `disabled` — pilot öncesi

Mevcut aşamanın modu budur.

- Periyodik yedekleme container'ı başlamaz.
- Düzenli PostgreSQL dump, belge manifesti, arşiv veya şifreli paket üretilmez.
- Readiness `backup.status=not_required` raporlar.
- Eksik yedek dosyası, recipient veya remote hedef pilot öncesi readiness'i
  bloklamaz.
- Test reset ve geçici veri temizliği normal biçimde devam eder.
- Manuel checkpoint komutu kullanılabilir kalır; ancak periyodik planı sessizce
  etkinleştiremez.

Yedekleme servisi açık bir Compose profile arkasına alınacaktır. `disabled`
modunda normal `up` veya deploy komutları servisi başlatmamalıdır. Böylece
restart döngüsü retry'larla gizlenmek yerine ortadan kaldırılır.

### 3.2 `checkpoint` — dondurulmuş korumalı corpus

Muhasebeci referans corpus'u tam freeze kapısına ulaştıktan sonra Fisero tek bir
kontrollü kurtarma noktası üretir.

Checkpoint şunları içerir:

- tutarlı bir PostgreSQL dump;
- tüm protected-corpus kaynak byte'ları;
- PostgreSQL içinde tutulan canonical evidence, muhasebeci reference version'ları
  ve protected rule verileri;
- SHA-256 hash'lerini içeren manifest;
- timestamp, schema migration seviyesi, corpus ID, corpus version/digest ve
  backup format version bilgilerini içeren metadata.

Checkpoint geçici normal test belgelerini içermez. Public `age` recipient ile
şifrelenir. Private identity repository, sunucu environment'ı, container veya
backup paketi içinde tutulmaz.

İlk checkpoint için off-host hedef operatörün çalışma bilgisayarıdır. Şifreli
paket sunucudan indirilir, digest'i yerelde doğrulanır ve ayrı bir PostgreSQL
database ile ayrı protected root'a restore edilir. Checkpoint yalnızca
uygulama-seviyesi corpus verifier başarılı olduğunda tamamlanmış sayılır.

Başarılı checkpoint sonrasında:

- periyodik yedekleme kapalı kalır;
- şifreli checkpoint, gerçek pilot yedeklemesi açılıp bağımsız restore testi
  geçene kadar saklanır;
- corpus reset/upload çalışmaları yalnız protected-corpus kapıları geçmeye devam
  ediyorsa sürdürülür.

### 3.3 `scheduled` — gerçek pilot

Bu mod ilk gerçek pilot faturası kabul edilmeden önce etkinleştirilir.

Her günlük yedek şunları içerir:

- PostgreSQL;
- protected-corpus byte'ları;
- 90 günlük saklama süresi içinde bulunan aktif normal PDF/XML belgeleri;
- paketi doğrulamak için gereken hash'ler ve backup metadata.

Türetilmiş export dosyaları, kalıcı approved accounting state üzerinden yeniden
üretilebiliyorsa kurtarma paketine alınmak zorunda değildir. Pilot
etkinleştirilmeden önce bu yeniden üretim varsayımı hedefli bir export recovery
testiyle doğrulanmalıdır. Yeniden üretilemeyen export artefact'ı varsa pakete
eklenmelidir.

İlk kurtarma hedefleri:

- **RPO:** en fazla 24 saat;
- **RTO:** bir iş günü içinde restore;
- **yerel saklama:** 14 günlük backup generation;
- **off-host saklama:** 30 günlük şifreli generation;
- **restore tatbikatı:** pilot açılmadan önce ve pilot sırasında en az 30 günde
  bir.

Off-host hedef uygulama sunucusundan farklı bir failure domain içinde olmalıdır.
Aynı sunucudaki bir dizin, adı `offhost` olsa bile yeterli değildir.
Kod bir bind mount'un fiziksel konumunu kendi başına kanıtlayamadığı için
`checkpoint` ve `scheduled` modlarında operatör ayrıca
`FISORA_BACKUP_OFFHOST_ATTESTED=true` verir. Bu teyit yoksa kopya receipt'i
bulunsa bile readiness `offhost_target_unattested` ile bloklanır.

## 4. Runtime ve Komut Tasarımı

Yedekleme Compose servisi açık bir backup profile kullanır.

- `disabled`: profile etkin değildir; servis tasarım gereği yoktur.
- `checkpoint`: operatör one-shot komutu açıkça çalıştırır.
- `scheduled`: deploy/operation wrapper profile'ı etkinleştirir ve günlük çalışan
  servisi başlatır.

One-shot ve scheduled yolları aynı packaging implementation'ını kullanır.
Böylece checkpoint, daha sonra production yedeklemesinde kullanılacak koddan
farklı bir yolu test etmez.

Yedekleme işi tam generation'ı geçici dizinde hazırlar, gereken tüm girdileri
doğrular, paketi üretip şifreler, hedefe kopyalar ve ancak bundan sonra başarı
receipt'i yayımlar. Yarım generation başarılı olarak raporlanamaz.

Packaging başarısız olsa bile geçici temizlik çalışır. Yalnızca şunları
silebilir:

- geçici staging dizinleri;
- tanımlı retention policy kapsamındaki süresi dolmuş ve eksiksiz
  generation'lar.

En son doğrulanmış generation veya tek protected-corpus checkpoint'i
silinmemelidir.

## 5. Readiness Sözleşmesi

Readiness `not_required`, `missing`, `failing` ve `recoverable` durumlarını
birbirinden ayırmalıdır.

Backup payload en az şu alanları taşımalıdır:

```text
mode
required
status
service_state
latest_attempt_at
latest_success_at
latest_encrypted_generation
latest_generation_digest
offhost_copy_status
offhost_target_attested
restore_verified_at
blocking
warnings
```

Mod kuralları:

- `disabled`: `required=false`, `status=not_required`, backup blocker yok;
- `checkpoint`: eksik veya doğrulanmamış checkpoint corpus recovery kapısını
  bloklar, fakat geçici pilot öncesi çalışmayı bloklamaz;
- `scheduled`: eksik recipient, farklı failure domain'de olmayan off-host hedef,
  hatalı servis, 26 saatten eski backup, tamamlanmamış şifreli kopya veya 30
  günden eski restore kanıtı gerçek pilot readiness'ini bloklar.

`FISORA_REAL_DATA_PILOT_ENABLED=true` ayrıca `scheduled` modu zorunlu kılar. Bu
çapraz kontrol, eksik veya eski backup-mode ayarının gerçek veri açıldıktan sonra
korumayı sessizce kapatmasını engeller.

Yerel bir SQL dosyasının varlığı tek başına hiçbir zaman
`backup_available=true` üretemez.

Off-host copy başarısı, şifreli generation'ın tanımlı hedefe yazıldığını
kanıtlar. Hedefin gerçekten sunucunun failure domain'i dışında olduğu
`FISORA_BACKUP_OFFHOST_ATTESTED=true` ile ayrıca kaydedilir; yerel path adı bu
gerçeği kanıtlayamaz.

## 6. Mevcut Üretilmiş Dosyalar

Restart döngüsü geçici yerel SQL dump'ları, boş document manifest'leri ve boş
protected-corpus archive'ları üretmiştir.

Temizlik ayrı bir destructive operation'dır:

1. hatalı scheduled runtime durdurulur veya değiştirilir;
2. kesin Docker volume ve file pattern'ları çözülür;
3. frozen corpus checkpoint veya gerçek pilot generation bulunmadığı doğrulanır;
4. file count, date range ve toplam size kullanıcıya gösterilir;
5. yalnız doğrulanan restart-loop artefact'ları açık operasyon onayından sonra
   silinir.

Implementation ve deployment bu silme işlemini kendiliğinden yetkilendirmez.

## 7. Dokümantasyon Durumu

Dokümantasyon backup konusunu yalnızca `kapandı` diye tanımlamayı bırakmalıdır.

Operasyon durumu ayrı ayrı kaydedilir:

- backup mechanism uygulandı;
- pilot öncesi schedule bilinçli olarak kapalı;
- protected-corpus checkpoint bekleniyor veya doğrulandı;
- periyodik pilot backup bekleniyor veya aktif;
- son restore tatbikatı tarihi.

`docs/current-handoff.md`, `docs/open-questions.md` ve
`docs/production-ops-runbook.md` bu ayrı durumları kullanmalıdır.

## 8. Hata Yönetimi

- Eksik encryption recipient: success yayımlanmadan one-shot generation
  başarısız olur; scheduled mod blocking duruma geçer.
- Copy failure: retry için en fazla eksiksiz şifreli yerel generation tutulur,
  off-host copy failed olarak işaretlenir ve success receipt üretilmez.
- PostgreSQL dump veya document archive failure: eksik staging generation
  silinir; secret veya document content göstermeden başarısız stage raporlanır.
- Restore verification failure: şifreli kaynak generation teşhis için korunur,
  non-recoverable işaretlenir ve ilgili checkpoint/pilot kapısı bloklanır.
- Disk pressure: PostgreSQL veya document storage'ı tehlikeye atmadan yeni yerel
  generation üretimi durur ve blocking storage warning raporlanır.

## 9. Kabul Kriterleri

### Pilot öncesi

- `FISORA_BACKUP_MODE=disabled`.
- Normal deploy backup servisini başlatmaz.
- 15 dakikalık gözlem boyunca yeni backup generation oluşmaz.
- Readiness `missing` veya `available` yerine `not_required` raporlar.
- Mevcut restart-loop artefact'larına ayrı temizlik onayı gelene kadar
  dokunulmaz.

### Corpus checkpoint

- Protected corpus freeze kapısı geçer.
- Tek şifreli generation PostgreSQL ve gerçek protected byte'ları içerir.
- Şifreli paket operatörün çalışma bilgisayarında bulunur.
- Paket ve content hash'leri doğrulanır.
- Restore ayrı database ve protected root kullanır.
- Uygulama-seviyesi protected-corpus restore kontrollerinin tamamı geçer.

### Gerçek pilot

- İlk gerçek faturadan önce backup mode `scheduled` olur.
- Günlük şifreli off-host generation'lar PostgreSQL, protected byte'lar ve aktif
  90 günlük PDF/XML byte'larını içerir.
- Son başarılı generation 26 saatten eski değildir.
- Off-host hedefin farklı failure domain olduğu doğrulanır.
- Pilot etkinleştirilmeden önce full restore tatbikatı geçer.
- Zorunlu recovery koşullarından biri false olduğunda readiness gerçek pilotu
  bloklar.

## 10. Doğrulama Planı

Yerel doğrulama:

- backup mode ve Compose-profile contract testleri;
- disabled-mode no-start testi;
- one-shot package/hash/encryption testleri;
- failure cleanup ve no-false-success testleri;
- üç mod için readiness testleri;
- ham PDF/XML dahil etme ve 90 günlük boundary testleri;
- export regeneration recovery testi;
- full backend ve frontend regression suite'leri;
- production Compose config ve shell syntax kontrolleri.

İzole kurtarma doğrulaması:

- synthetic PostgreSQL, protected-corpus ve normal-document fixture'ları
  oluştur;
- şifreli checkpoint ve scheduled-mode backup üret;
- ikisini farklı local test target'a kopyala;
- ayrı PostgreSQL instance ve filesystem root'larına restore et;
- hash'leri, corpus invariant'larını, normal document byte'larını ve export
  regeneration'ı doğrula.

Canlı doğrulama normal release approval sınırını gerektirir. Deploy sonrasında:

- `disabled` modda backup servisinin bulunmadığını kanıtla;
- yeni generation oluşmadığını gözle;
- readiness semantics'i doğrula;
- ayrı cleanup approval olmadan mevcut artefact'ları silme.

## 11. Kapsam Sınırları

Bu tasarım:

- bugün gerçek pilot backup'ını etkinleştirmez;
- bugün ücretli off-host provider seçmez;
- gerçek fatura yüklemez;
- accounting-quality kapıları geçmeden corpus'u freeze etmez;
- production verisini resetlemez;
- mevcut backup artefact'larını silmez;
- commit, push, deploy veya canlı configuration değişikliğini yetkilendirmez.

Bir sonraki implementation plan; code, test, documentation, local verification
ve kesin release preflight kapsamını belirleyecektir. Commit, push, deploy ve
canlı temizlik ayrı approval sınırları olarak kalır.
