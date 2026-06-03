# Mali Mustavir Demo Gorusmesi Paketi

## Hedef

Yarinki gorusmede hedef, mustavirden uzun kural listesi istemek degil; Fisora'nin
"taslak + risk + mustavir onayi + export paketi" akisini gostermek ve pilot icin
gereken minimum dosyalari netlestirmektir.

## 10 Dakikalik Anlatim Akisi

1. Fisora otomatik muhasebeci gibi davranmaz.
2. Mukellef kullanicisi sadece yetkili oldugu mukellefe belge yukler.
3. Sistem belgeyi okur, cari ve hesap plani adaylarini mevcut Zirve hesap
   planindan secer.
4. Gecmis veri yoksa AI destekli taslak modu bos sayfa yerine ilk fis onerisi
   ve gerekce hazirlar.
5. Fis taslagi deterministic motorla dengeli uretilir.
6. Riskli, faaliyet disi veya cari belirsiz kayit export'a girmez.
7. Mustavir onaylar veya duzeltir.
8. Duzeltme sonraki benzer belgelerde ogrenme adayi olur.
9. Export paketi Zirve testinden gecen format kesinlesene kadar kontrollu kalir.

## Canli Demo Sirasi

1. Portalda mustavir moduna gec.
2. Mukellef secimini goster.
3. Export hazir ve review gerekli belgeleri ayri goster.
4. Rexton gibi alan ici kalemde fis taslagini goster.
5. Urban Care gibi supheli kalemde export kapisinin kapali kaldigini goster.
6. AI/kural gerekcesinin mustavire nasil yardim ettigini goster.
7. Cari/hesap duzeltme alanina ornek kod gir.
8. "Duzelt ve onayla" kararinin learning event'e donustugunu anlat.
9. Export paketi olustur ve manifest mantigini anlat.

## Mustavirden Istenen Minimum Dosyalar

Demo oncesi gonderilecek daha net talep listesi icin
`docs/accountant-pre-demo-request.md` kullanilir.

Zorunlu:

- 1 pilot mukellef karti: unvan, VKN/TCKN, faaliyet/NACE veya faaliyet aciklamasi.
- Isyeri adresi.
- Zirve hesap plani exportu.
- 20-50 adet fatura veya anonimlestirilmis fatura.
- 1 banka Excel/CSV ekstresi.

Varsa:

- Cari liste veya 120/320 detaylari.
- Son 1-3 ay yevmiye, muavin veya fis listesi.
- Zirve'nin kabul ettigi ornek import dosyasi.

## Sorulacak Net Sorular

- Zirve'de fis importu icin en guvenilir ekran hangisi?
- Hesap plani ve cari liste exportunda VKN/TCKN veya IBAN kolonlari var mi?
- Export paketi mukellef bazli mi, donem bazli mi hazirlanmali?
- Hangi kayit tipleri ilk etapta kesinlikle review'da kalmali?
- Mustavir onayi olmadan export'a girebilecek en dusuk riskli islem tipi var mi?
- Pilot icin hangi iki mukellef daha uygun: biri genel isletme, biri sektor hassasiyeti yuksek?

## Alinacak Kararlar

- Ilk pilot mukellef.
- Zirve hesap plani export dosyasi formati.
- Cari liste/yevmiye aliniyor mu, alinmiyorsa blokaj sayilmiyor.
- Ilk export denemesi icin hedef format.
- Mustavir review politikasinda otomasyonun ne zaman acilabilecegi.

## Kapanis Mesaji

```text
Bu sistem sizin yerinize kesin kayit atmak icin degil,
size kontrol edilebilir fis taslagi ve guvenli export paketi hazirlamak icin
tasarlandi. Ilk pilotta tum kritik kararlar sizden onay alacak.

Gecmis veri olmayan yeni mukellefte AI size ilk taslagi hazirlar.
Siz duzelttikce sistem sizin kararlarinizi ogrenir ve tekrar eden dusuk riskli
islerde daha az mudahale gerektirir.
```
