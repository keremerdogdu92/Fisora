# Auth ve Yetki Stratejisi

## Karar

Fisora MVP'de serbest uyelik olmayacak. Kullanici once mali musavir/ofis
tarafindan acilacak ve en az bir mukellefe baglanacak. Mukellef kullanicisi
sadece kendisine atanmis mukellefin belgelerini yukler; mustavir birden cok
mukellefi gorur.

## Auth Modlari

Backend `FISORA_AUTH_MODE` ile calisir.

| Mod | Kullanim | Davranis | Production |
|---|---|---|---|
| `mock_header_optional` | Local test | Header yoksa anonim gecis olabilir | Hayir |
| `mock_header_required` | Local demo | `X-Fisora-User-Id` zorunlu | Hayir |
| `trusted_header` | Production bootstrap | Gateway dogrulanmis user id header'i enjekte eder | Evet, gateway dogru kurulursa |

Varsayilan test modu `mock_header_optional` kalir. Production env orneginde
`trusted_header` kullanilir.

## Trusted Header Sarti

`trusted_header` modunda backend gelen `X-Fisora-User-Id` degerini dogrulanmis
portal kullanicisi olarak kabul eder. Bu ancak reverse proxy veya auth gateway
asagidakileri yaparsa guvenlidir:

- Tarayicidan gelen `X-Fisora-User-Id` header'ini siler.
- Session/JWT/OIDC kontrolunu kendisi yapar.
- Dogrulanmis kullanici id'sini backend'e yeniden header olarak ekler.
- Logout/session expire durumunda header gondermez.

Bu kosullar saglanmadan `trusted_header` canliya alinmaz.

## Ilk Gercek Login Yolu

MVP icin iki pratik rota var:

1. Custom session:
   - FastAPI login endpointleri.
   - HttpOnly secure cookie.
   - `portal_users` kayitlariyla rol ve mukellef yetkisi.
   - Tek sunucu kurulumuna uyumlu, dis servis maliyeti yok.

2. Harici provider:
   - Clerk/Auth0/Keycloak gibi provider.
   - Backend sadece dogrulanmis token veya trusted header alir.
   - Daha hizli guvenlik standardi, ancak ek maliyet/operasyon var.

Baslangic icin teknik onerim: demo ve pilotta `mock_header_required`, canliya
gecerken custom session veya provider kararini netlestirmek. Provider secilirse
backend `trusted_header` veya token dogrulama katmanina tasinir.

## Yetki Kurallari

- Belge upload: sadece atanmis `client_user`, `accountant` veya `admin`.
- Workspace goruntuleme: atanmis kullanici veya mustavir.
- Export paketi olusturma: sadece `accountant` veya `admin`.
- Export indirme: atanmis kullanici veya mustavir; ileride mustavir onayi
  gerektirebilir.
- Portal kullanicisi olmayan biri fatura yukleyemez.

## Acik Kararlar

- Custom session mi, provider mi secilecek?
- Mustavir ofisi altinda kullanici davet akisi nasil olacak?
- Sifre sifirlama ve 2FA zorunlu olacak mi?
- Header-based bootstrap yerine JWT dogrulama ne zaman eklenecek?
- Mukellef kullanicisi export dosyasini gorecek mi, yoksa sadece belge yukleme
  ve durum takibi mi gorecek?
