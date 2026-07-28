# Price Sentinel — provisioning e rotazione secret

## Architettura runtime

- Caddy è l'unico processo pubblico sulle porte 80/443 e conserva le chiavi TLS nel proprio storage protetto.
- Nginx espone HTTP soltanto su `127.0.0.1:8082` e non monta certificati o chiavi.
- FastAPI e PostgreSQL sono raggiungibili soltanto sulla rete Docker `ps_internal`.
- Il backend usa un ruolo PostgreSQL applicativo non-superuser. Il ruolo proprietario serve esclusivamente alle migration controllate.
- Il dominio root mantiene code-server; il solo percorso `/api/v1/integrations/liquidstock/*` viene inoltrato al backend Price Sentinel.
- L'interfaccia Price Sentinel sull'IP termina comunque TLS su Caddy mediante la CA interna di Caddy.

## File runtime non versionati

Creare come `root`, con directory `0700` e file `0600`:

- `/etc/price-sentinel/postgres.env`: `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB`.
- `/etc/price-sentinel/backend.env`: `DATABASE_URL` del ruolo applicativo e gli altri secret applicativi.
- `/etc/price-sentinel/migration.env`: `DATABASE_URL` del ruolo proprietario, usato solo durante le migration.

I valori devono essere generati con un CSPRNG e non devono essere passati in argomenti di comando, log, chat o file dentro il repository.

## Rotazione PostgreSQL

1. Eseguire e verificare un backup custom con restore list.
2. Generare password nuove per ruolo proprietario e ruolo applicativo.
3. Applicare `ALTER ROLE` tramite input standard protetto e aggiornare i file runtime atomically.
4. Ricreare database e backend mantenendo il volume dati.
5. Verificare health, letture/scritture applicative e Alembic con il ruolo proprietario.
6. Verificare esplicitamente che le credenziali precedenti non autentichino più.

Per verificare o applicare Alembic senza esporre il ruolo proprietario al backend
permanente, usare entrambi i file protetti nel container one-shot: prima
`backend.env`, poi `migration.env`, che sovrascrive esclusivamente `DATABASE_URL`.

## Rotazione TLS

1. Verificare DNS A/AAAA di root e www.
2. Validare il Caddyfile e la configurazione Nginx.
3. Ottenere nuove coppie ACME per root e `www` senza riusare le chiavi precedenti.
4. Verificare SAN, catena, scadenza e servizi prima di revocare il certificato compromesso.
5. Revocare il vecchio certificato con motivo `keyCompromise` e rimuovere ogni copia operativa precedente.

## Reset dati

L'endpoint e l'interfaccia di reset globale sono stati rimossi. Il precedente `RESET_PASSWORD` non è più letto dal processo e non abilita alcuna operazione.

## Verifiche minime dopo un riavvio

- `ps_db` e `ps_backend` devono risultare `healthy`.
- PostgreSQL non deve avere alcun binding host; Nginx deve essere pubblicato solo su `127.0.0.1:8082`.
- `nginx -t` e `caddy validate` devono passare.
- Root e `www` devono presentare certificati pubblici validi e diversi dalle coppie revocate.
- Il backend deve riportare `price_sentinel_app` come `current_user`, senza attributi superuser/createdb/createrole.
- Una ricerca catalogo HMAC senza risultati deve rispondere `200` senza creare eventi o dati operativi.
- L'endpoint storico `/api/v1/intelligence/reset-database` deve rispondere `404`.

## Rollback

Il rollback può ripristinare configurazioni e immagini precedenti, ma deve continuare a usare le credenziali e i certificati nuovi. Non ripristinare mai chiavi o password compromesse.
