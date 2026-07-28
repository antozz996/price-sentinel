# Price Sentinel — stato TLS di produzione

Verifica eseguita il 28 luglio 2026 direttamente sulla porta pubblica 443.

## Endpoint canonici

| Hostname | Issuer | Subject/SAN | Seriale | Validità |
| --- | --- | --- | --- | --- |
| `guadagnarefacileonline.it` | Let's Encrypt `YE2` | `guadagnarefacileonline.it` | `06D901168ADC07CEF751493600331B033625` | 26 luglio 2026 14:42:43 UTC — 24 ottobre 2026 14:42:42 UTC |
| `www.guadagnarefacileonline.it` | Let's Encrypt `YE2` | `www.guadagnarefacileonline.it` | `06CAA80C7CF966BE60915FADBC19D98B1CBB` | 26 luglio 2026 14:42:44 UTC — 24 ottobre 2026 14:42:43 UTC |

La catena inviata è verificata correttamente fino alla trust anchor pubblica:

`leaf → Let's Encrypt YE2 → ISRG Root YE → ISRG Root X2 → ISRG Root X1`.

La validazione hostname e la verifica OpenSSL restituiscono `Verify return code: 0
(ok)` per entrambi gli hostname. HTTP viene reindirizzato automaticamente a HTTPS e
`https://www.guadagnarefacileonline.it` reindirizza permanentemente al dominio root.

## Terminazione TLS

Caddy è l'unico listener pubblico sulle porte 80 e 443 e gestisce emissione e rinnovo
automatico dei certificati pubblici. Le richieste `/api/v1/*` vengono inoltrate a
Nginx su `127.0.0.1:8082`. Nginx espone soltanto HTTP su loopback e inoltra le API al
container FastAPI; non termina TLS.

L'endpoint HTTPS sull'IP `46.225.81.66` è distinto dagli hostname canonici e utilizza
un certificato della CA privata di Caddy con SAN IP. Non è un certificato pubblico,
non viene presentato per `guadagnarefacileonline.it` o `www`, e non deve essere usato
da client o integrazioni. Gli endpoint pubblici supportati sono esclusivamente quelli
basati sul dominio.

## Verifiche operative

- certificati pubblici root e www: validi;
- hostname validation: valida;
- catena pubblica: valida;
- redirect HTTP → HTTPS: attivo;
- redirect www → root: attivo;
- HSTS: `max-age=31536000; includeSubDomains`;
- API health: `healthy`.
