# LANEFACTOR

Versione corrente: **0.10.0**.

LANEFACTOR è un piccolo progetto per raccogliere dati da League of Legends:
scarica gli ID dei match ranked solo/duo, le relative timeline e il dettaglio
della partita tramite le API Riot, così da avere una base dati da cui poi tirare fuori statistiche e analisi
sulle partite. Tutto finisce in PostgreSQL; timeline e dettaglio vengono salvati come
JSON compresso con gzip per non far esplodere il database. Ogni run e ogni
batch di ingestion tengono anche traccia di esiti, errori HTTP e tempi, utile
per capire cosa è successo senza dover rileggere i log.

## Struttura del progetto

- `src/lanefactor/infrastructure/`: client Riot, connessione PostgreSQL e repository per dati e metriche.
- `src/lanefactor/services/ingestion/`: servizi per registrare gli ID dei match e scaricare timeline e dettaglio.
- `src/lanefactor/utils/telemetry.py`: accumulo delle metriche di run e batch.
- `scripts/ingestion/`: runner di ingestione e comandi CLI.
- `scripts/db-init/`: creazione iniziale degli schemi `core` e `metrics`.
- `config/`: template `.env.*.example` e `kestra-config.example.yaml` da copiare e adattare.
- `data/`: file di input locali, montati in sola lettura nel container Kestra.
- `docs/`: guide operative, TODO, miglioramenti noti e il [glossario](docs/glossario.md) dei termini del progetto (seed, partizione, cooldown, run radice...).
- `compose.yaml` e `Dockerfile.*`: servizi e immagini per l'esecuzione con Docker.
- `pyproject.toml` e `uv.lock`: configurazione del package e dipendenze Python.

Gli import del package partono da `lanefactor.*`. Per ora non c'è una suite di
test automatizzati.

## Avvio con Docker Compose

Il modo più comodo per far girare tutto è Docker Compose. Servono Docker e
Docker Compose installati. Prima del primo avvio, segui la
[guida Docker Compose](docs/docker-compose.md) per preparare `.env.db`,
`.env.riot`, `kestra-config.yaml` e i quattro volumi esterni.

La configurazione Riot richiede `RIOT_API_KEY`, `REGION`, `RIOT_TIMEOUT`,
`RIOT_MAX_ATTEMPTS`, `RIOT_MAX_SLEEP`, `RIOT_MIN_REQUEST_INTERVAL` e `RIOT_MAX_404_ATTEMPTS`. Le prime tre variabili numeriche sono
obbligatorie e devono contenere interi: timeout in secondi e tentativi maggiori
di zero, attesa massima in secondi maggiore o uguale a zero. Ad esempio:

```dotenv
RIOT_TIMEOUT=15
RIOT_MAX_ATTEMPTS=5
RIOT_MAX_SLEEP=600
RIOT_MIN_REQUEST_INTERVAL=1.2
RIOT_MAX_404_ATTEMPTS=3
```

`RIOT_MIN_REQUEST_INTERVAL` è un numero decimale di secondi non negativo: il client
aggiunge una pausa dopo la richiesta per raggiungere la durata minima configurata,
utile per stare larghi con i rate limit di Riot. Il valore `0` disattiva questa
pausa aggiuntiva; le attese entrano comunque in `total_sleep_seconds`.

`RIOT_MAX_404_ATTEMPTS` è un intero obbligatorio: quando un download riceve 404 a
questo numero di tentativi (e anche il tentativo precedente era un 404), timeline o
dettaglio passano a `UNAVAILABLE`, senza retry, e il match esce dalla sync e dalle
selezioni di download. Un 404 dopo errori di altro tipo (5xx, timeout) resta
`FAILED` con retry. La variabile è letta all'import dei repository, quindi serve
a ogni runner che li usa, `update_seed` compreso: se manca, il job non parte.

Questi sono valori di esempio, non default automatici: vanno impostati a mano.
Aggiorna anche i file `.env.riot` già esistenti prima di eseguire i runner.

Dalla root del progetto, dopo la configurazione:

```bash
docker compose up -d --build
docker compose build ingest_player_game match_sync match_timeline_sync match_detail_sync update_seed snowball
```

Compose avvia PostgreSQL applicativo, CloudBeaver, Kestra e il database
separato di Kestra. Il servizio `init-db` crea gli schemi e termina;
non applica migrazioni alle tabelle già esistenti. I runner di ingestione
si lanciano su richiesta, quando servono.

CloudBeaver è disponibile su <http://localhost:8978> e Kestra su
<http://localhost:8080>. Configurazione, persistenza e arresto dei servizi
sono descritti nella guida.

## Ingestione

Per recuperare fino a 100 ID di un giocatore e scaricare timeline e dettaglio dei match elaborabili:

```bash
docker compose run --rm ingest_player_game --game-name "Nome" --tag-line "TAG" --count 100
```

`--start` indica l'offset iniziale nella lista Riot e vale 0 per default.
`--count` limita gli ID richiesti a Riot, non il numero di nuove associazioni.
Il servizio registra tutti i match globali e le associazioni mancanti, poi
seleziona timeline e dettagli elaborabili, in due liste distinte, tra tutti gli
ID ricevuti. Il comando apre una run radice `ingest_player_game`, senza metriche
proprie, con tre run figlie: `ingest_ranked_match_ids` (le sue metriche contano
le nuove associazioni), `ingest_timelines` e `ingest_details` (batch di massimo
20 match, esiti dei download). Le fasi condividono lo stesso client Riot e le
figlie sono collegate alla radice da `parent_run_id`. Se per una fase non ci
sono match da scaricare, la sua run figlia non viene aperta e la radice si
chiude comunque `DONE`.

Rieseguire il comando permette di ritentare anche match già associati al giocatore,
quando il cooldown è scaduto. I match completati vengono esclusi e un fallimento
successivo non sovrascrive una timeline già in stato `FETCHED`. Il recupero è
limitato alla finestra `--start`/`--count`; il runner globale può elaborare anche
match pendenti fuori da questa finestra.

Per recuperare i payload mancanti nel database (download falliti con retry
scaduto, run interrotte) ci sono tre job di sync, facoltativi e fuori dal ciclo
dello snowball. Dividono i match in una partizione in base ai due flag
indipendenti, così un match appartiene a un solo job:

| Job | Match che prende | Scarica |
|---|---|---|
| `match_sync` | né timeline né dettaglio | timeline e poi dettaglio |
| `match_timeline_sync` | dettaglio già scaricato, timeline mancante | timeline |
| `match_detail_sync` | timeline già scaricata, dettaglio mancante | dettaglio |

```bash
docker compose run --rm match_sync --limit 100
docker compose run --rm match_timeline_sync --limit 100
docker compose run --rm match_detail_sync --limit 100
```

Ogni job apre una run radice e, a ogni giro, seleziona fino a `--limit` match
scaricabili ora (flag FALSE, stato né `FETCHED` né `UNAVAILABLE`, `next_retry_at`
assente o scaduto), li passa a `ingest_timelines`/`ingest_details` come run figlie e
si ferma quando non resta nulla di elaborabile, senza attendere i retry futuri:
un match scaricato, in cooldown o `UNAVAILABLE` esce dalla selezione, quindi il
ciclo termina sempre. Un match con un payload già `UNAVAILABLE` e l'altro mancante
non è preso da nessun job (non entrerebbe comunque nelle analisi). I job non vanno
lanciati in parallelo: il pacing verso Riot è per processo, quindi due job insieme
raddoppiano il ritmo e provocano 429. Il piano è farli orchestrare da Kestra in
sequenza. Con `Ctrl+C` la run figlia chiude `STOPPED`, il dettaglio di `match_sync`
non parte e la radice chiude `STOPPED`; il processo termina comunque con codice 0.

Per estrarre nuovi punti di partenza dalle timeline già scaricate (snowball):

```bash
docker compose run --rm update_seed --batch-size 500
```

`update_seed` non chiama Riot. Legge a blocchi le timeline `FETCHED` con
`seeds_extracted_at` NULL, estrae i PUUID dei partecipanti, li inserisce in
`core.puuid_seed` (quelli già presenti restano invariati) e marca le timeline
nella stessa transazione. Termina quando non restano timeline da leggere;
rilanciarlo non duplica nulla.

Per far crescere il pool a partire dai seed (la valanga):

```bash
docker compose run --rm snowball --limit 10 --matches-per-seed 100
```

`snowball` apre una run radice, senza metriche proprie, seleziona fino a
`--limit` seed da `core.puuid_seed` (prima i mai ingeriti, poi i meno recenti)
e per ciascuno registra i match con `ingest_matches` in modalità PUUID, poi
scarica timeline e dettaglio con `ingest_timelines` e `ingest_details`: tre
run figlie per seed, con un solo client Riot condiviso. Un seed è segnato come
ingerito (`last_ingested_at`) solo quando le due run figlie finiscono senza
stop; i singoli download falliti non lo impediscono, perché restano registrati
con il loro cooldown e li riprendono i job di sync. Un seed senza match
ranked è segnato comunque. Un `InputError` fa saltare il seed con un log di
errore e senza segnarlo. Con `Ctrl+C` il ciclo si ferma subito, anche se
l'interruzione arriva durante le timeline (il dettaglio di quel seed non parte)
e il seed in corso non viene segnato. Resta tra i mai ingeriti e viene ripreso
quando la rotazione lo raggiunge (tra i seed scoperti nello stesso istante
l'ordine non è definito); i match già registrati ma senza payload li recuperano
i job di sync. `snowball` non scopre
seed nuovi: per questo si alterna con `update_seed`.

I runner delle timeline e dei dettagli usano `BatchService` per avviare e chiudere
i batch, aggregare le metriche e comunicare lo stop al chiamante. Selezione degli
ID, indice dei batch e stato della run restano nei runner. Il runner su lista
esplicita mostra una barra di avanzamento e attende cinque secondi tra batch,
esclusi ultimo batch e stop. Un `Ctrl+C` interrompe la run in modo pulito: il
lavoro già salvato resta salvato, e il batch in corso viene chiuso senza
lasciare a metà una scrittura sul database.

Le CLI configurano il logging a livello INFO. I retry HTTP 429 riportano endpoint,
tentativo, identificativi run/batch quando disponibili e header dei limiti Riot; gli
errori di connessione (con tipo di eccezione e durata) e i 5xx con retry loggano un
warning analogo. I job di sync sono registrati con le pipeline `match_sync`,
`match_timeline_sync` e `match_detail_sync`.

Per consultare le opzioni dei comandi, usa `--help`. Dopo modifiche al
codice, ricostruisci le immagini dei runner con il comando `build` sopra.

## Ambiente Python locale

Il progetto richiede Python >= 3.12; `.python-version` seleziona Python 3.12.
Con `uv` installato, sincronizza l'ambiente dalla root:

```bash
uv sync --locked
```

Per eseguire i runner fuori da Docker servono un PostgreSQL raggiungibile,
gli schemi inizializzati e le variabili `POSTGRES_HOST`, `POSTGRES_PORT`,
`POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD`, `RIOT_API_KEY`, `REGION`,
`RIOT_TIMEOUT`, `RIOT_MAX_ATTEMPTS`, `RIOT_MAX_SLEEP`,
`RIOT_MIN_REQUEST_INTERVAL` e `RIOT_MAX_404_ATTEMPTS` esportate nell'ambiente prima dell'avvio. Compose carica `.env.db` e
`.env.riot` nei container; l'esecuzione locale non li carica automaticamente.
Il PostgreSQL applicativo di Compose è raggiungibile dall'host su
`127.0.0.1:5432`: per runner e notebook locali usa `POSTGRES_HOST=127.0.0.1`
e `POSTGRES_PORT=5432`. Nei container il nome del servizio resta `postgres`.

Con questi prerequisiti configurati:

```bash
uv run --module scripts.ingestion.ingest_player_game --game-name "Nome" --tag-line "TAG" --count 100
uv run --module scripts.ingestion.match_sync --limit 100
uv run --module scripts.ingestion.match_timeline_sync --limit 100
uv run --module scripts.ingestion.match_detail_sync --limit 100
uv run --module scripts.ingestion.update_seed --batch-size 500
uv run --module scripts.ingestion.snowball --limit 10 --matches-per-seed 100
```

## Schema e aggiornamenti

`core.match` contiene i match globali, con primary key `match_id` e i flag di
download `timeline_fetched` e `detail_fetched`, indipendenti. `core.puuid_match` contiene le associazioni dei giocatori e una foreign
key verso `core.match`. I tentativi e i payload restano in `core.match_timeline`.

`core.match_detail` è la tabella gemella per il dettaglio della partita (payload
in `detail_bytea` e colonne estratte `game_version`, `queue_id`,
`game_duration_s`, `end_of_game_result`), con gli stessi stati e CHECK. Su un
database esistente va applicata prima la migrazione
`scripts/db-init/migrations/2026-10-01_match_detail.sql`, poi `init-db`.

Anche `core.match_timeline` referenzia `core.match`. I CHECK limitano gli
stati ammessi, impediscono contatori negativi e retry precedenti o uguali
all'ultimo tentativo; `last_attempt_at` è obbligatorio. Una timeline `FETCHED`
deve avere payload, data di download e HTTP 200, senza retry pendente.

`core.puuid_seed` è la coda dei PUUID da visitare per lo snowball: `puuid` come
primary key, `discovered_at` e `last_ingested_at` (NULL = match mai richiesti).
La alimenta `update_seed` e la consuma `snowball`, che a ogni seed completato
aggiorna `last_ingested_at`. La colonna `seeds_extracted_at` di
`core.match_timeline` (NULL = timeline non ancora letta) è ammessa solo su
righe `FETCHED`.

La cache `core.riot_id_cache` usa `puuid` come primary key e mantiene unica la
coppia `(game_name, tag_line)`. `upsert_account` aggiorna nome e tag quando viene
salvata una nuova risoluzione dello stesso PUUID; non introduce scadenza o
rivalidazione automatica della cache.

Le run sono organizzate ad albero tramite `metrics.ingestion_run_metrics.parent_run_id`:
NULL per una run radice, per le figlie il `run_id` della run che le ha avviate
(FK sulla stessa tabella, con CHECK che impedisce l'auto-riferimento). Una
singola esecuzione si ricostruisce con una CTE ricorsiva a partire dalla radice.

Le metriche di run e batch ammettono gli stati `RUNNING`, `DONE`, `FAILED`,
`STOPPED` e `MISSING`. I vincoli controllano coerenza tra stato e fine esecuzione,
ordine delle date, contatori e durate non negativi, attese finite e dimensioni
dei batch coerenti.

I flag `timeline_fetched` e `detail_fetched` restano memorizzati per distinguere un risultato perso
da un download mai completato. L'assenza della riga timeline con flag FALSE è
normale backlog.

Gli script di inizializzazione creano solo oggetti mancanti: non trasformano
uno schema precedente. Per l'ambiente di sviluppo attuale è prevista la
ricreazione dello schema e il successivo download dei dati; la release non
esegue automaticamente reset e non include una migrazione dei dati esistenti.

La cronologia è nel [changelog](CHANGELOG.md). Le verifiche locali non includono
un'esecuzione completa su PostgreSQL e Riot.
