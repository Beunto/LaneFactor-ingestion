# Avvio con Docker Compose

Eseguire i comandi dalla root del progetto con Docker Compose disponibile.

## Configurazione iniziale

Creare `.env.db` con le variabili del database applicativo:

```dotenv
POSTGRES_DB=lanefactor
POSTGRES_USER=lanefactor
POSTGRES_PASSWORD=<password-locale>
POSTGRES_HOST=postgres
POSTGRES_PORT=5432
```

Creare `.env.riot` per i job di ingestion con tutte le seguenti variabili:

```dotenv
RIOT_API_KEY=<chiave-riot>
REGION=europe
RIOT_TIMEOUT=15
RIOT_MAX_ATTEMPTS=5
RIOT_MAX_SLEEP=600
RIOT_MIN_REQUEST_INTERVAL=1.25
RIOT_MAX_404_ATTEMPTS=3
```

I valori numerici sono esempi, non default: tutte le variabili sono
obbligatorie (`RIOT_MIN_REQUEST_INTERVAL` è un decimale, le altre interi). Timeout (secondi) e tentativi devono essere
positivi; l'attesa massima (secondi) può essere zero. Aggiungerle anche alle
configurazioni `.env.riot` esistenti.

Compose carica questi file tramite `env_file`; host e porta del database
vanno definiti in `.env.db` come sopra.

Preparare la configurazione locale di Kestra:

```bash
cp config/kestra-config.example.yaml kestra-config.yaml
mkdir -p data
```

Impostare username e password dell'accesso web in `kestra-config.yaml`.
Le credenziali della datasource PostgreSQL devono corrispondere a quelle del
servizio `kestra-postgres` in `compose.yaml`. Il database di Kestra è separato
da quello applicativo. La directory locale `data/` viene montata in sola lettura
in `/app/lanefactor-data`; gli eventuali file di input vanno copiati anche sul
nuovo computer. Kestra utilizza inoltre il socket Docker dell'host per i runner.

Il volume PostgreSQL applicativo si chiama `lanefactor-postgres-data`. Il precedente
volume `lanefactor-data` non viene riutilizzato e i dati non vengono trasferiti
automaticamente.

Creare i volumi esterni prima del primo avvio su ciascun computer:

```bash
docker volume create lanefactor-postgres-data
docker volume create lanefactor-cloudbeaver-config
docker volume create lanefactor-kestra-storage
docker volume create lanefactor-kestra-postgres-data
```

## Avvio

```bash
docker compose up -d --build
```

Avvia PostgreSQL applicativo, CloudBeaver, PostgreSQL per Kestra e Kestra.
Il servizio `init-db` inizializza gli schemi `core` e `metrics` e termina con
codice 0. Gli script sono destinati alla creazione iniziale dello schema:
non aggiornano la struttura di tabelle già esistenti.
I runner con profilo `manual` non partono automaticamente.
I volumi locali non importano automaticamente dati da un altro computer.

Aprire http://localhost:8978 e configurare CloudBeaver con host `postgres`,
porta `5432` e database/credenziali di `.env.db`. CloudBeaver attende che
PostgreSQL sia healthy; per consultare le tabelle attendere anche `init-db`.
PostgreSQL applicativo è esposto solo su `127.0.0.1:5432` per client e notebook
locali; dall'host usare `POSTGRES_HOST=127.0.0.1` e `POSTGRES_PORT=5432`.
CloudBeaver è esposto solo su
`127.0.0.1:8978`; per cambiare porta modificare il mapping in `compose.yaml`.

Kestra è disponibile su http://localhost:8080, con le credenziali definite
in `kestra-config.yaml`. Anche questa porta è vincolata a `127.0.0.1`.

## Job su richiesta

Costruire le immagini dei runner, anche dopo modifiche al codice:

```bash
docker compose build ingest_player_game match_sync match_timeline_sync match_detail_sync update_seed snowball
```

Ingestion di un giocatore:

```bash
docker compose run --rm ingest_player_game --game-name "Nome" --tag-line "TAG" --count 100
```

Recupero dei payload mancanti, con tre job che dividono i match in una
partizione (`match_sync`: né timeline né dettaglio; `match_timeline_sync`:
dettaglio già scaricato; `match_detail_sync`: timeline già scaricata):

```bash
docker compose run --rm match_sync --limit 100
docker compose run --rm match_timeline_sync --limit 100
docker compose run --rm match_detail_sync --limit 100
```

I job vanno lanciati uno alla volta: il pacing verso Riot è per processo e due
job insieme raddoppiano il ritmo. Ognuno termina quando non restano match
scaricabili ora, senza attendere i retry futuri.

Estrazione dei nuovi seed dalle timeline già scaricate (non chiama Riot, ma il
servizio carica anche `.env.riot` perché importa i repository, che leggono
`RIOT_MAX_404_ATTEMPTS`):

```bash
docker compose run --rm update_seed --batch-size 500
```

Valanga: scarica match, timeline e dettaglio dei seed in `core.puuid_seed`, in
ordine di rotazione (prima i mai ingeriti):

```bash
docker compose run --rm snowball --limit 10 --matches-per-seed 100
```

Il servizio richiesto viene abilitato automaticamente anche senza specificare
`--profile manual`. I job attendono il database e il completamento di `init-db`.
Per consultarne le opzioni, sostituire gli argomenti con `--help`.

`--limit` imposta quanti seed elabora `snowball` in una run e `--matches-per-seed`
quanti ID chiede a Riot per ciascuno. Per un primo test conviene `--limit 2`:
un seed con 100 match nuovi costa circa 200 richieste, cioè qualche minuto con
il pacing di esempio.

`--count` limita gli ID recuperati per il giocatore. Il relativo runner timeline
usa batch di massimo 20 ID. `--batch-size` imposta invece il limite del job di
sincronizzazione, con valore predefinito 100. In entrambi i flussi,
`requested_size` registra il numero effettivo di ID passati al batch.

## Arresto e persistenza

```bash
docker compose down
```

I dati applicativi, il workspace CloudBeaver e i dati di Kestra rimangono nei
volumi esterni. Anche `docker compose down -v` conserva i volumi dichiarati
esterni; la loro eliminazione richiede un'operazione esplicita separata.
Per riprendere su un altro computer, ricreare i file di configurazione locali
e i volumi; trasferire separatamente eventuali dati persistenti necessari.

I runner `ingest_player_game`, `snowball`, `match_sync`, `match_timeline_sync`, `match_detail_sync` e `update_seed` intercettano il
`SIGTERM` inviato da `docker stop`/`docker compose down` e lo rimandano come
`SIGINT` al proprio processo, così batch e run in corso vengono chiusi in
modo ordinato invece di terminare a metà scrittura. La chiusura ordinata deve
comunque completarsi entro lo *stop grace period* di Docker (10 secondi di
default): oltre quel limite arriva un `SIGKILL`, non intercettabile.
