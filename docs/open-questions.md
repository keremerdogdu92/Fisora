# Acik Kararlar

Bu liste Faz 0 sirasinda mustavirle, pilot mukelleflerle ve Zirve testleriyle
netlestirilecek.

## Zirve ve Export

1. Zirve'de en saglam fis seviyesi aktarim rotasi hangisi?
2. Fis/seri fis/fis listesi aktarimi gercek kullanimda yeterli mi?
3. Zirve yevmiye, muavin veya fis listesi exportu hangi kolonlarla alinabiliyor?
4. Gecmis yevmiye/muavin exportu tedarikci -> hesap kodu ogrenmesi icin yeterli
   mi?
5. Belge PDF/XML dosyasini Zirve'ye eklemek gerekli mi?
6. Export dosyasi donem sonunda tek paket mi, mukellef bazli ayri paket mi
   olmali?
7. Dogrudan Zirve entegrasyonu ne zaman ele alinacak, hangi import formati
   sahada dogrulanmadan kapali kalacak?

## Mukellef Onboarding

8. Minimum mukellef kartinda hangi alanlar zorunlu olmali?
9. NACE/faaliyet kodu yoksa faaliyet aciklamasi kim tarafindan girilecek?
10. Isyeri adresleri nasil dogrulanacak ve fatura adresiyle nasil eslestirilecek?
11. Hesap plani ne siklikla yeniden import edilmeli?
12. Cari bulunamadiginda yeni cari acma sureci ne zaman otomatiklesmeli?

## Risk, Uygunluk ve Otomasyon

13. Varsayilan yuksek tutar limiti ne olmali?
14. Istisna, tevkifat ve iade belgelerinde ilk otomasyon politikasi ne olmali?
15. OIV/OTV, karma KDV ve eksik belge no durumlari her zaman kontrol kuyruğuna mi
    dusmeli?
16. Is alani disi veya supheli belge icin mustavir karar secenekleri nasil
    adlandirilmali?
17. Elektrik, internet, kira ve akaryakit gibi genel giderlerde adres/plaka
    eslesmesi zorunlu mu olmali?
18. AI'in marka/modelden urun kategorisi cikarma guveni hangi esigin altinda
    kontrol kuyruğuna dusmeli?
19. Ayni mustavir karari kac tekrar sonra otomasyon adayi sayilmali?
20. Genel ogrenme adayi, mustavir/ofis politikasi ve mukellef ozel kural ayrimi
    urunde nasil gosterilmeli?

## Operasyon ve Veri

21. Ham belge saklama politikasi 90 gun olarak belirlendi; metadata/audit
    saklama suresi mustavir/ofis politikasina gore netlestirilecek.
22. Maliyet kontrolu icin hangi durumlarda AI cagrisi atlanacak?
23. OCR fallback hangi belge tipleri ve hangi guven esiklerinde calisacak?
24. Iptal ve duzeltme istekleri mustavir operasyonunda nasil karsilanmali?
25. Mustavir onay izi, reddetme gerekcesi ve export paketi denetim icin ne kadar
    saklanmali?

## Sunucu ve AI API

26. Ilk production kendi kiralik sunucuda mi, yoksa cloud app/object storage
    kombinasyonunda mi baslayacak?
27. Ham belge storage volume'u sifreli olacak mi, dis backup hangi Turkiye
    lokasyonunda tutulacak?
28. Dis AI API sadece kategori/gerekce icin mi kullanilacak, yoksa banka
    aciklamasi siniflandirma da kapsama girecek mi?
29. API sonucunun dusuk guven esigi kac olacak ve hangi durumlarda mustavir
    review'a zorunlu donderecek?
30. Aylik AI maliyet cap'i ofis bazinda mi, mukellef bazinda mi uygulanacak?
31. Gercek fatura metni dis AI API'ye gonderilecekse mustavir ve veri sahibi
    onayi hangi metinle alinacak?
32. AI assisted draft modunda minimum confidence esigi kac olacak?
33. AI'in hesap onerisi yalnizca mevcut hesap plani adaylariyla mi sinirli
    kalacak, yoksa "hesap bulunamadi" durumunda aciklama mi uretecek?
34. Soguk baslangic demo basarisi ile production otomasyon basarisi raporda
    nasil ayrilacak?
35. OpenAI/Gemini/Manus benchmarkinda hangi 20-50 marka/model ve genel gider
    case seti standart kabul edilecek?
