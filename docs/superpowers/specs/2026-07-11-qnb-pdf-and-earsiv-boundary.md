# QNB PDF Kaniti ve e-Arsiv Servis Siniri

## Dogrulanan PDF kontrati

QNB'nin guncel resmi API teknik sayfasinda gelen e-Fatura PDF'i ayri bir
servis degil, `connectorService.gelenBelgeleriIndirExt` metodudur.
`belgeTuru=FATURA`, `belgeFormati=PDF`, ETTN, VKN/TCKN ve ERP kodu gonderilir.
Dokuman `UBL`, `HTML` ve `PDF` formatlarini destekledigini ve bir cagrida en
fazla 100 belge indirilebildigini belirtir.

Fisora PDF'i canonical UBL'nin yerine gecirmez. PDF ayni ETTN ve parent UBL
document ref ile `qnb_pdf` evidence olarak tutulur; SHA-256 ve cekilme zamani
kaydedilir. ZIP path traversal, boyut, dosya sayisi, tek PDF ve `%PDF-` header
kontrolleri zorunludur. Tekrar istek ikinci evidence kaydi olusturmaz.

Kaynak: https://www.qnbesolutions.com.tr/api-docs-tr-final.html

## e-Arsiv siniri

Guncel kamuya acik QNB teknik sayfasi e-Arsiv icin `faturaOlustur`/
`faturaOlusturExt` gonderim akisini ve `earsivtest.../EarsivWebService` ailesini
ornekliyor. Ancak gelen e-Arsiv listeleme, indirme ve status kontrati bu teknik
sayfada yayimlanmiyor. e-Fatura `connectorService` metodlari e-Arsiv'e
varsayimla uygulanmayacak.

e-Arsiv source-adapter uygulamasindan once QNB'den su kanitlar gerekir:

- Gelen e-Arsiv urun/yetki aktivasyonu.
- Test WSDL ve servis endpoint'i.
- Listeleme, UBL/PDF indirme, iptal/itiraz ve status metodlari.
- Ornek request/response veya test belgesi.

Bu kanit gelene kadar yalniz ortak source/evidence modeli yeniden kullanilir;
uydurma SOAP metodu veya production davranisi eklenmez.

## 2026-07-13 e-Arsiv WSDL ve gonderim spike sonucu

QNB mailindeki gercek test endpoint'leri ve `portaltest` hesabi ignored
`.env.qnb.local` dosyasina alindi. Canli WSDL/XSD tekrar okundu:

- `connectortest.../userService` yalniz `wsLogin` ve `logout` sunuyor.
- `earsivtest.../EarsivWebService` icinde `faturaOlusturExt`,
  `faturaSorgulaExt`, `faturaListeSorgula`, `faturaIptalEt`, `faturaItirazEt`,
  taslak ve onizleme metotlari var.
- `faturaOlusturExt` request'i JSON `input` ile base64 `belge` aliyor. JSON'da
  `islemId`, `vkn`, `sube`, `kasa`, `erpKodu` ve `donenBelgeFormati`; belgede
  `UBL` ve `belgeIcerigi` bulunuyor.
- Basarili response `AE00000`, `uuid`, `faturaNo`, `faturaURL` ve istenirse
  UBL/HTML/PDF output donuyor.

Bu kontratla `backend/app/domain/qnb_earsiv.py` ve dis islem icin acik
`--confirm-send` isteyen `backend/scripts/run_qnb_earsiv_sandbox_smoke.py`
eklendi. Arac yalniz QNB test hostlarini kabul eder, `EARSIVFATURA` profilli
UBL ister ve secret degerlerini output'a yazmaz.

Gercek cookie login denemesi parolanin kabul yoluna ulasti fakat QNB
`EF0556` ile firma kullanicisinin portal uzerinden mali muhur/e-imza ile
dogrulanmasini istedi. SOAP Header denemesi de mevcut portal kullanicisini WS
kullanicisi olarak kabul etmedi. Bu nedenle siradaki dis bagimlilik portal
dogrulamasi ve QNB'nin tavsiye ettigi ayri WS kullanicisidir. Bu adim olmadan
gercek fatura olusturma cagrisi yapilmadi.

WSDL'deki `faturaListeSorgula` QNB e-Arsiv ortaminda olusturulan faturalarin
listesidir; bunu dis kaynaktan "gelen e-Arsiv" akisi olarak yorumlamayiz.
Gelen/source adapter siniri bu nedenle aynen korunur.
