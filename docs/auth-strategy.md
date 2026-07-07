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
| `trusted_header` | Gateway/JWT sonrasi opsiyon | Gateway dogrulanmis user id header'i enjekte eder | Evet, gateway dogru kurulursa |
| `session_required` | Kontrollu ofis kullanimi | Uygulama session cookie'si zorunlu; tarayici user header'i yok sayilir | Evet, TLS ile |

Varsayilan test modu `mock_header_optional` kalir. Production env orneginde
ilk MVP hedefi `session_required` olmalidir. `trusted_header` ancak ayri bir
auth gateway/JWT/OIDC katmani tarayici header'larini temizleyip dogrulanmis user
id enjekte ettiginde kullanilir.

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

MVP icin karar verilen rota custom session'dir:

- FastAPI login endpointleri.
- HttpOnly secure cookie.
- `portal_users` kayitlariyla rol ve mukellef yetkisi.
- Tek sunucu kurulumuna uyumlu, dis auth provider maliyeti yok.
- Davet ve sifre sifirlama free-tier mail servisiyle gonderilir.

Harici provider veya `trusted_header`, ilk MVP sonrasi guvenilir gateway/JWT/OIDC
katmani secilirse yeniden degerlendirilir.

## Eklenen MVP Session Akisi

Backend artik custom session icin ilk MVP endpointlerini tasir:

- `POST /phase0/store/auth/password`: portal kullanicisi icin parola hash'i
  kaydeder.
- `POST /phase0/store/auth/login`: dogru parola ile session token uretir.
- `GET /phase0/store/auth/session`: `X-Fisora-Session` header'ini dogrular.
- `POST /phase0/store/auth/logout`: session token'i revoke eder.
- `POST /phase0/store/auth/invite`: portal kullanicisi icin davet token'i
  uretir, `FISORA_PORTAL_BASE_URL` varsa davet linki kurar ve mail delivery
  sonucunu dondurur.
- `POST /phase0/store/auth/invite/accept`: davet token'iyle ilk sifreyi
  belirler.
- `POST /phase0/store/auth/password-reset`: sifre reset token'i uretir,
  `FISORA_PORTAL_BASE_URL` ve alici email varsa reset mail delivery sonucunu
  dondurur.
- `POST /phase0/store/auth/password-reset/confirm`: reset token'iyle yeni sifre
  yazar.

Session token'in kendisi database'e yazilmaz; sadece SHA-256 hash'i saklanir.
Login cevabi geriye uyum icin token'i JSON'da dondurur, kontrollu canli
kullanimda ayni token `HttpOnly` cookie olarak tasinir. Parolalar PBKDF2-SHA256
ile salt'li hash olarak tutulur.

`trusted_header` modunda parola bootstrap endpoint'i varsayilan olarak kapali
kalir. Sadece kapali pilot ortaminda `FISORA_AUTH_PASSWORD_BOOTSTRAP_ENABLED=true`
ile acilmalidir. Davet/reset akisi icin `FISORA_EMAIL_PROVIDER` kullanilir.
Mail kapaliysa endpoint token/link uretmeye devam eder ve UI manuel paylasim
fallback'ini gosterir.

Bir sonraki adimda token rate limit ve yeniden gonderme kurallari sertlestirilir.
2FA ilk MVP kapsami disinda kalabilir.

## Mail Ayarlari

Ilk canli kurulum icin maliyetsiz baslangic modu `dry_run` olabilir; bu mod
network'e cikmaz, ama UI davet/reset linkinin hazir oldugunu gosterir. Mail
gonderimi acilacaksa once free-tier provider secilir:

- `FISORA_EMAIL_PROVIDER=resend`: `FISORA_RESEND_API_KEY` ve
  `FISORA_EMAIL_FROM` gerekir.
- `FISORA_EMAIL_PROVIDER=smtp`: `FISORA_SMTP_HOST`, `FISORA_SMTP_PORT`,
  `FISORA_SMTP_USERNAME`, `FISORA_SMTP_PASSWORD` ve `FISORA_EMAIL_FROM`
  gerekir.
- `FISORA_EMAIL_PROVIDER=disabled`: mail gondermez, manual link fallback'i
  kullanilir.

## Yetki Kurallari

- Belge upload: sadece atanmis `client_user`, `accountant` veya `admin`.
- Workspace goruntuleme: atanmis kullanici veya mustavir.
- Export paketi olusturma: sadece `accountant` veya `admin`.
- Export indirme: mustavir veya admin. Mukellef kullanicisi kendi yukledigi
  belgeyi ve durumunu onizleyebilir, varsayilan olarak ham dosya/export indirmez.
- Portal kullanicisi olmayan biri fatura yukleyemez.

## Acik Kararlar

- Free-tier mail provider secimi: Resend, Brevo veya SMTP2GO kisa listesi.
- 2FA ilk MVP sonrasi mustavir/ofis politikasina gore degerlendirilecek.
- `trusted_header`/JWT gecisi ancak gercek gateway ihtiyaci dogarsa tekrar
  acilacak.
