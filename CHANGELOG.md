# Changelog
Tutte le modifiche rilevanti a questo progetto verranno documentate qui.

## [Unreleased]

### Added
- `docs/glossario.md`: glossario di 45 termini del progetto (dati di Riot, snowball, stati e recupero, run e metriche, rate limit e arresto, cose pianificate), che è anche la scheda Glossario della Documentazione nell'artifact (con filtro).
- Tre job di sync di recupero, facoltativi e fuori dal ciclo dello snowball: `match_sync` (match senza né timeline né dettaglio), `match_timeline_sync` (dettaglio già scaricato) e `match_detail_sync` (timeline già scaricata), in `scripts/ingestion/`, opzione `--limit` (default 100). Dividono i match in una partizione in base ai due flag, così un match ha un solo job. Ognuno apre una radice, seleziona i match scaricabili ora con `MatchRepository.fetch_match_sync_ids`, `fetch_timeline_sync_ids` o `fetch_detail_sync_ids`, li passa a `ingest_timelines`/`ingest_details` come run figlie e termina a selezione vuota; una run figlia `STOPPED` ferma il job (le timeline `STOPPED` di `match_sync` impediscono il dettaglio). Pensati per essere orchestrati da Kestra in sequenza, non in parallelo. Provati con un client Riot finto e, per `match_timeline_sync` e `match_detail_sync`, su Riot reale; `match_sync` su dati reali è ancora da provare.
- Stato terminale `UNAVAILABLE` per `core.match_timeline` e `core.match_detail`: `insert_timeline` e `insert_detail` lo scrivono (con `next_retry_at` NULL) quando arriva un 404, il tentativo precedente era già un 404 e `attempt_count + 1 >= max_404_attempts` (default da `RIOT_MAX_404_ATTEMPTS`, nuova variabile obbligatoria in `.env.riot`); le quattro query di selezione dei match da scaricare lo escludono, un 200 successivo può sovrascriverlo. Un 404 dopo errori 5xx o timeout resta `FAILED`. Il CHECK sullo stato è aggiornato in `init_db_postgres.py`: lo schema va ricreato (nessuna migrazione).
- Job valanga `snowball` (`scripts/ingestion/snowball.py`, servizio Compose omonimo, opzioni `--limit` e `--matches-per-seed`): apre una run radice `snowball` e, per ciascun seed scelto da `PuuidSeedRepository.select_seeds_to_ingest`, esegue `ingest_matches` in modalità PUUID, `ingest_timelines` e `ingest_details` come run figlie con un solo `RiotClient`. `mark_ingested([puuid])` segna il seed a fine giro, dentro `block_sigint()`, solo se le due run figlie non sono `STOPPED`; un `InputError` fa saltare il seed con log di errore e senza segnarlo. Verificato su 2 seed reali (295 match, nessun duplicato); stop durante le timeline verificato; percorsi di errore e stop durante il dettaglio ancora da provare.
- Ingestion del dettaglio della partita (match-v5 `/matches/{id}`) come concetto separato dalla timeline: tabella gemella `core.match_detail` (payload gzip in `detail_bytea` e colonne estratte `game_version`, `queue_id`, `game_duration_s`, `end_of_game_result`), flag `detail_fetched` su `core.match`, `MatchDetailRepository`, `DetailIngestionService`, runner `ingest_details`, `RiotClient._get_match_detail`. `ingest_ranked_match_ids` e `ingest_matches` restituiscono anche gli ID con dettaglio elaborabile e `ingest_player_game` apre una terza run figlia `ingest_details`. Il recupero dal database (`MatchRepository.fetch_pending_detail_match_ids`) è pronto ma non ancora collegato a un runner di sync.
- Migrazione `scripts/db-init/migrations/2026-10-01_match_detail.sql` (idempotente, da eseguire prima di `init-db` su un database esistente).
- `PayloadIngestionService`: classe madre con il ciclo di download e salvataggio; `TimelineIngestionService` e `DetailIngestionService` implementano solo i quattro hook `_make_repo`, `_fetch`, `_store`, `_mark`. Il metodo comune si chiama `fetch_and_store`.
- Colonna `parent_run_id` su `metrics.ingestion_run_metrics` (FK sulla stessa tabella, CHECK anti-auto-riferimento, indice parziale) che organizza le run ad albero: NULL per la radice, per le figlie l'UUID della run che le ha avviate. `RunMetricsRepository.start_run` accetta `parent_run_id`. Lo schema va ricreato: `init-db` non migra tabelle esistenti.
- `ingest_player_game` apre una run radice `ingest_player_game` (senza metriche proprie, chiusa nel `finally` con `DONE`/`FAILED`/`STOPPED`) e passa il suo `run_id` come `parent_run_id` alle run `ingest_ranked_match_ids` e `fetch_and_store_timelines`, che condividono lo stesso `RiotClient`.
- `ingest_matches` accetta `puuid`, `client` e `parent_run_id`; `ingest_timelines` accetta `client` e `parent_run_id`. Un client passato dall'esterno resta del chiamante e le sue metriche sono azzerate all'inizio di ogni run (in `ingest_timelines` a ogni batch).
- `PuuidSeedRepository.select_seeds_to_ingest(limit)`: rotazione dei seed `ORDER BY last_ingested_at NULLS FIRST, discovered_at`, senza cooldown né flag.
- Logging INFO nelle CLI e contesto run/batch tramite `ContextVar`; diagnostica dei retry HTTP 429 con endpoint, tentativo e header dei limiti Riot.
- Barra di avanzamento dei batch nel runner su lista esplicita, con dipendenza `tqdm` e lockfile aggiornato.
- Configurazione obbligatoria `RIOT_MIN_REQUEST_INTERVAL` in secondi decimali per la pausa minima per richiesta, inclusa nelle metriche di attesa; zero disattiva la pausa aggiuntiva.
- Aggiunto `signal_guard.block_sigint()`, un context manager che sospende temporaneamente `SIGINT` durante le scritture critiche su database, in modo che un Ctrl+C non interrompa mai un commit a metà.
- Aggiunto `signal_guard._forward_sigterm_as_sigint()`, registrato come handler di `SIGTERM` nell'entrypoint di `ingest_player_game`, `timelines_matches_sync` e `update_seed`: rimanda SIGTERM come SIGINT allo stesso processo, così `docker stop`/`docker compose down` riusano la stessa chiusura ordinata già prevista per Ctrl+C, incluso il rispetto di `block_sigint()` durante le scritture critiche.
- Tabella `core.puuid_seed` (coda dei PUUID noti da visitare nello snowball: `puuid`, `discovered_at`, `last_ingested_at`) e `PuuidSeedRepository` con `insert_seeds` (`ON CONFLICT DO NOTHING`, `last_ingested_at` da `MAX(seen_at)` di `core.puuid_match` se il PUUID è già noto) e `mark_ingested`.
- Colonna `seeds_extracted_at` su `core.match_timeline_fetch` (NULL = timeline non ancora letta per estrarre i seed), con CHECK sulle sole righe `FETCHED` e indice parziale; `MatchTimelineRepository.fetch_pending_seed_timelines` e `mark_seeds_extracted` per il futuro job `update_seed`.
- Job `update_seed` (`scripts/ingestion/update_seed.py`, opzione `--batch-size`, default 500) e `SeedExtractionService`: legge a blocchi le timeline `FETCHED` con `seeds_extracted_at` NULL, estrae i PUUID da `metadata.participants`, li inserisce in `core.puuid_seed` e marca le timeline nella stessa transazione (dentro `block_sigint()`, marcatore per ultimo). Non chiama Riot; registra la run in `metrics.ingestion_run_metrics` e mostra una barra `tqdm` con totale stimato da `MatchTimelineRepository.count_pending_seed_timelines`. Il runner avvolge ogni blocco e il relativo aggiornamento delle metriche in `block_sigint()`: `Ctrl+C` e `SIGTERM` attendono la fine del blocco in corso e la run chiude come `STOPPED` con totali coerenti con le timeline marcate.

### Changed
- Documentate la partizione dei job di sync, la regola «mai in parallelo» (il pacing è per processo) e il codice di uscita 0 di un `STOPPED` assorbito dal servizio; aggiornata la guida Compose con i tre nuovi servizi (da definire in `compose.yaml`) e il TODO (punto 6).
- Il servizio Compose `update_seed` carica anche `.env.riot`, perché importa i repository che leggono `RIOT_MAX_404_ATTEMPTS`; documentate la nuova variabile (README, guida Compose, `config/.env.riot.example`) e la mancante `RIOT_MIN_REQUEST_INTERVAL` nell'esempio della guida.
- `RiotClient.request` scrive un `logger.warning` a ogni errore di connessione (tipo di eccezione, durata del tentativo, tentativo su massimo, pausa; anche all'ultimo tentativo, prima di rilanciare) e a ogni 5xx con retry, con `run_id` e `batch_id`. Prima solo i 429 erano loggati e un batch da 101 s senza 429 né 5xx non era spiegabile.
- `ingest_timelines` e `ingest_details` restituiscono lo stato finale della run (`"DONE"` o `"STOPPED"`) invece di `None`, perché uno stop assorbito dal servizio non solleva eccezioni e il chiamante deve poterlo vedere. `snowball` e `ingest_player_game` lo usano: uno `STOPPED` delle timeline impedisce l'avvio del dettaglio e la radice chiude `STOPPED`.
- Documentato in TODO il throughput misurato (1,4 s per timeline, 89% pacing) e la decisione di non usare il threading tra timeline e dettaglio.
- `core.match_timeline_fetch` rinominata `core.match_timeline` (indici e vincoli allineati) per simmetria con `core.match_detail`; la migrazione sopra la applica. Le etichette `pipeline` delle run diventano `ingest_timelines` (prima `fetch_and_store_timelines`) e `ingest_details`; le run già salvate mantengono il vecchio nome.
- `TimelineBatchService` rinominato `BatchService` (`batch_service.py`) e reso indipendente dal tipo di payload.
- Docstring di `signal_guard` in italiano e con type hint; corretti `RiotClient.__init__`/`_validate_config` (ora citano `RIOT_MIN_REQUEST_INTERVAL`), l'indentazione di `_validate_response` e due typo.
- In `PayloadIngestionService.fetch_and_store` il controllo dello stop non sta più dentro il `finally`, dove un `break` può inghiottire un'eccezione in corso.
- `ingest_matches` e `update_seed` impostano `run_id_var` (reset del token a fine run) e registrano con `logger.exception` un errore nella chiusura della run quando c'è già un'eccezione attiva, come gli altri runner. I `params` di `ingest_player_game` usano `game_name`/`tag_line`, come `ingest_matches`.
- La funzione CLI di `timelines_matches_sync.py` si chiama ora `timelines_matches_sync` (prima `ingest_timelines`, in conflitto di nome con il runner omonimo); il comando non cambia.
- Documentati `update_seed`, `core.puuid_seed` e `seeds_extracted_at` in README e guida Compose. `timelines_matches_sync` è descritto come ramo di recupero facoltativo, fuori dal ciclo dello snowball (vedi `docs/TODO.md`); precisato che `ingest_matches` e `ingest_timelines` sono funzioni chiamate da `ingest_player_game`, non comandi CLI.
- `MatchIngestionService.ingest_ranked_match_ids` accetta ora in alternativa la coppia `gameName`/`tagLine` oppure un `puuid` già noto (saltando la risoluzione via cache/Riot); `_validate_input_identity` solleva la nuova `InputError(ValueError)` (in `lanefactor/exceptions.py`) se è passato un solo elemento della coppia, nessun identificativo o entrambe le modalità. Il runner `ingest_matches` chiama il servizio con keyword argument.
- Completati i type hints mancanti nelle firme di funzioni e metodi Python, inclusi servizi batch, metriche e context manager del database.
- Documentate le nuove funzioni di logging e gestione batch nello stile Parameters/Returns; rimosse le docstring di modulo dai file Python, mantenendo quelle di funzioni e metodi.
- Centralizzati avvio, chiusura e metriche dei batch in `TimelineBatchService`, condiviso dai due runner timeline. Il servizio restituisce azione e stato; i runner mantengono selezione, indice, pause e chiusura della run.
- Rinominata la pipeline della sync globale da `ingest_timelines_until_done` a `timelines_matches_sync`.
- Aggiunti vincoli SQL per stati, payload e retry delle timeline, con foreign key verso `core.match` e `last_attempt_at` obbligatorio.
- Aggiunti CHECK alle metriche per stati, coerenza temporale, contatori, durate e dimensioni dei batch.
- Cache Riot identificata dalla primary key `puuid`, mantenendo unica la coppia nome/tag; `upsert_account` aggiorna nome e tag del PUUID esistente e sostituisce `insert_account` nel servizio.
- Esposta la porta PostgreSQL applicativa solo su `127.0.0.1:5432` per client e notebook locali.
- Aggiornato `MIGLIORAMENTI.md` con audit periodico, riconciliazione dei flag e gestione degli esiti non recuperabili, ancora da implementare; mantenuto `timeline_fetched`.
- Rinominato il volume esterno PostgreSQL applicativo in `lanefactor-postgres-data` e allineata la guida di creazione; nessun trasferimento automatico dal precedente volume `lanefactor-data`.
- Rinominata in `timelines_to_fetch` la lista elaborata dalla CLI `ingest_player_game`, per riflettere gli ID effettivamente selezionati per il download.
- `RiotClient` legge timeout, tentativi e attesa massima dalle variabili d’ambiente obbligatorie `RIOT_TIMEOUT`, `RIOT_MAX_ATTEMPTS` e `RIOT_MAX_SLEEP`, convertite in interi; rimossi i parametri e i default del costruttore. Le configurazioni esistenti devono fornire tutte e tre le variabili.
- Aggiornate le docstring del client e rimossi da `MIGLIORAMENTI.md` i due punti P2 risolti.
- Protette con `block_sigint()` le scritture di chiusura di batch, run e cache PUUID nei servizi di ingestion (`start_batch`, `finish_batch`/`delete_batch`, `finish_run`, `insert_timeline`, `mark_seen`), lasciando sempre le chiamate HTTP con retry fuori da qualunque sezione bloccata.

### Removed
- Il comando, il servizio Compose e la pipeline `timelines_matches_sync`, sostituiti dai tre job di sync (le run storiche restano con il vecchio nome di pipeline), e le query `MatchRepository.fetch_pending_timeline_match_ids` e `fetch_pending_detail_match_ids`, sostituite dalle `fetch_*_sync_ids` con un perimetro che forma una partizione.
- `PuuidMatchRepository.fetch_match_ids` (non usato e basato su un criterio diverso dal backlog globale) e `infrastructure/paths.py` (residuo SQLite non importato da nessuno).

### Fixed
- Protetto con `block_sigint()` l'upsert della cache dei Riot ID in `MatchIngestionService._resolve_puuid`: la voce sulle scritture protette lo dava già per fatto, ma un Ctrl+C prima del commit annullava il salvataggio del PUUID appena ottenuto da Riot.
- Protetta con `block_sigint()` anche la chiusura della run (`finish_run`) in `ingest_matches` e `update_seed`, già protetta negli altri due runner: un secondo Ctrl+C durante la scrittura lasciava la run in `RUNNING`.
- Preservato l’errore primario di ingestion quando fallisce anche la chiusura delle metriche del batch in entrambi i runner timeline; gli errori secondari di batch e run vengono registrati con traceback e identificativo. Gli errori della telemetria senza un errore primario continuano a essere propagati.
- Validati i limiti della configurazione Riot prima delle richieste: timeout e tentativi positivi, attesa massima non negativa.
- Usato il backoff di fallback per header `Retry-After` assenti, non numerici, negativi o non finiti; accettato zero e mantenuto il limite `max_sleep`.
- Corretti i link relativi in `README.md` e `docs/MIGLIORAMENTI.md`, che puntavano a percorsi inesistenti.

### Notes
- I nuovi vincoli e la chiave della cache richiedono uno schema ricreato o una migrazione esplicita: `CREATE TABLE IF NOT EXISTS` non modifica tabelle esistenti. Nessun reset automatico.
- Verifiche locali con dipendenze simulate per configurazione, retry e fallimenti della telemetria; nessuna chiamata Riot o prova su database reali.
- Il forwarding di `SIGTERM` come `SIGINT` non è stato ancora verificato con `docker stop` reale né con una suite di test automatizzati.

## [0.10.0] - 2026-09-26

### Added
- Aggiunti Kestra e il database dedicato `kestra-postgres` a Compose, con volumi esterni, accesso web locale sulla porta 8080, socket Docker e directory di input montata in sola lettura.
- Aggiunto `kestra-config.example.yaml` per preparare la configurazione locale; escluso da Git `kestra-config.yaml`, contenente le credenziali locali.
- Introdotti `core.match` e `MatchRepository` con primary key `match_id`, stato globale delle timeline e selezione dei retry consentiti.
- Aggiunta la foreign key dalle associazioni `core.puuid_match` ai match globali, inseriti prima delle associazioni nella stessa transazione.

### Changed
- Aggiornato il servizio PostgreSQL di Compose all'immagine `postgres:18`, con volume esterno `lanefactor-data` montato su `/var/lib/postgresql` anziché `/var/lib/postgresql/data`.
- Riorganizzato Compose con il servizio database `postgres` e configurazione caricata da `.env.db`; i job di ingestion caricano anche `.env.riot`.
- Rinominati i servizi di ingestion in `ingest_player_game` e `timelines_matches_sync`, spostati dal profilo `jobs` a `manual` e configurati con entrypoint espliciti in Compose; disabilitato l'entrypoint specifico in `Dockerfile.ingestion`.
- Limitata l’esposizione dei servizi Compose: rimossa la pubblicazione della porta PostgreSQL `5432` sull’host e vincolata la porta CloudBeaver a `127.0.0.1:8978:8978`; rimossa la variabile `CLOUDBEAVER_PORT`.
- CloudBeaver attende ora il database healthy anziché il completamento di `init-db`; ridotti a tre i tentativi dell'healthcheck PostgreSQL, rimosso lo start period e rimosse le policy di riavvio automatico di PostgreSQL e CloudBeaver.
- Separati conteggio delle nuove associazioni e selezione dei download: tutti gli ID ricevuti vengono valutati per recuperare timeline fallite a cooldown scaduto.
- Spostata la selezione del backlog globale in `MatchRepository`; filtro diretto e backlog escludono match completati e retry futuri.
- Protetti i record `FETCHED` da successivi upsert, conservando payload, contatore e provenienza del download completato.
- Reso obbligatorio `run_id` nel servizio timeline e allineati i tipi degli identificativi tra servizio e repository.
- Sostituita l’interpolazione degli URL PostgreSQL con `URL.create` nel modulo database e in entrambi gli script di inizializzazione.
- Uniformate le docstring di moduli e metodi al formato descrizione, Parameters, Returns; aggiornati README e documento degli interventi aperti.
- Allineati `pyproject.toml` e `uv.lock` alla versione 0.10.0.

### Fixed
- Le metriche `requested_size` dei batch timeline registrano ora il numero effettivo di ID selezionati, anche per batch più piccoli del limite configurato.
- Allineato il binding Click di `--batch-size` al parametro interno `max_batch_size`, aggiornando anche docstring e parametri registrati nelle run.
- Allineato il risultato di `ingest_ranked_match_ids` a `tuple[list[str], list[str]]`: nuove associazioni e timeline elaborabili; il runner `ingest_matches` restituisce la seconda lista.
- Allineata la guida Docker a servizi, profilo `manual`, file ambiente, porte, configurazione Kestra e gestione dei volumi esterni; documentata la preparazione su un nuovo computer.

### Notes
- Cambiamento di schema: l’inizializzazione non migra tabelle preesistenti. Per i dati di sviluppo attuali è prevista la ricreazione dello schema e il download; nessun reset automatico incluso.
- Verifiche locali con Riot simulato e SQLite in memoria; integrazione completa su PostgreSQL e Riot non eseguita. Limiti residui documentati in `MIGLIORAMENTI.md`.

## [0.9.0] - 2026-09-22

### Added
- Runner `ingest_matches` e CLI Click `ingest_player_game` per recuperare gli ID ranked solo/duo di un giocatore e scaricarne le timeline.
- CLI `timelines_matches_sync` per recuperare in batch le timeline pendenti dal database fino a esaurimento dei match elaborabili al momento.
- Metodo `fetch_pending_timeline_match_ids` con filtro su `timeline_fetched = FALSE`, esclusione delle timeline già `FETCHED` e rispetto di `next_retry_at`.
- `Dockerfile.ingestion` e configurazione Compose con PostgreSQL, CloudBeaver, inizializzazione degli schemi e runner opzionali nel profilo `jobs`; riutilizzo dei volumi esterni `lanefactor-data` e `lanefactor-cloudbeaver-config`.
- Guida di avvio dei servizi e dei job in `docs/docker-compose.md`.
- Dipendenze dirette `click` e `requests`, con aggiornamento del lockfile.

### Changed
- L'ingestion dei match restituisce gli ID ricevuti; il servizio timeline accetta una lista esplicita di ID anziché selezionarli autonomamente dal database.
- `ingest_timelines` suddivide gli ID in batch configurabili (20 di default), con una transazione per batch, metriche di batch aggregate in una sola run e pausa di cinque secondi tra batch, esclusi ultimo batch e stop.
- Aumentato da 120 a 600 secondi il limite di attesa predefinito dei retry di `RiotClient`.
- Reso facoltativo `batch_id` nello schema iniziale delle timeline e preservato `None` nel servizio; la modifica dello schema non migra le tabelle già esistenti.

### Fixed
- Corretto il Dockerfile di inizializzazione per installare le dipendenze senza tentare di installare il progetto prima della copia dei sorgenti.
- Allineato `last_attempt_at` agli altri timestamp della timeline, passando un `datetime` UTC a SQLAlchemy anziché una stringa ISO.

## [0.8.0] - 2026-09-21

### Added
- Engine SQLAlchemy condiviso in `infrastructure/database.py`, configurato tramite le variabili d’ambiente PostgreSQL.

### Changed
- Migrata la persistenza applicativa da SQLite a PostgreSQL, usando gli schemi `core` e `metrics` già introdotti nella versione 0.7.0.
- `DbSession` acquisisce la connessione all’ingresso nel `with` e gestisce commit, rollback e rilascio della connessione.
- Tutte le repository ricevono una connessione SQLAlchemy obbligatoria; query eseguite tramite `text()` e parametri nominati, con liste di dizionari per le operazioni multiple.
- Adattate query e valori allo schema PostgreSQL, inclusi booleani, timestamp UTC, colonna `timeline_bytea` e gestione dei duplicati tramite `ON CONFLICT`.
- Runner delle timeline aggiornato a `DbSession`, con transazioni separate per avvio e conclusione dei batch e per le metriche della run.
- Uniformate le docstring in italiano alle convenzioni PEP 257, chiarendo valori restituiti, stati e comportamento dei retry.
- Esclusi dal versionamento l’archivio locale `old/` e i notebook di prova corrispondenti ai nuovi pattern di `.gitignore`.
- Allineata la versione del progetto in `pyproject.toml` e `uv.lock` a 0.8.0.

### Fixed
- Selezione di match distinti nel backlog tramite raggruppamento per `match_id`, ordinati per avvistamento più recente e ID.
- Separati stato finale e stato atteso `RUNNING` negli aggiornamenti delle metriche di batch e run.
- Stato della run impostato a `FAILED` per gli errori propagati e a `STOPPED` per le interruzioni intercettate dal runner esterno.
- Gestione degli errori nella chiusura della run estesa anche all’apertura della connessione e al commit.

### Removed
- Rimossi dal codice attivo `BaseRepository`, `DbMetrics` e gli script di inizializzazione SQLite; copie conservate nell’archivio locale ignorato da Git.
- Rimosso dal repository il precedente notebook `notebooks/api_tests.ipynb`.

### Notes
- Il passaggio richiede PostgreSQL configurato e gli schemi inizializzati; non include il trasferimento dei dati SQLite esistenti.
- La verifica completa dell’ingestion su PostgreSQL e la dockerizzazione del runner restano da eseguire.
- Rimandata a una release successiva la protezione dell’errore originale di ingestion quando fallisce anche il salvataggio delle metriche del batch; nessun retry aggiuntivo introdotto.

## [0.7.0] - 2026-09-21

### Added
- Aggiunti gli script `scripts/db-init/init_db_postgres.py` e `scripts/db-init/init_metrics_db_postgres.py` per inizializzare tabelle e indici PostgreSQL negli schemi separati `core` e `metrics`.
- Connessione PostgreSQL tramite SQLAlchemy e driver `psycopg`, configurata dalle variabili d’ambiente `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_HOST`, `POSTGRES_PORT` e `POSTGRES_DB`; inizializzazione eseguita in transazione per ciascuno script.
- Schema PostgreSQL con tipi nativi: `TIMESTAMPTZ` per le date, `UUID` per gli identificativi run/batch, `BOOLEAN` per `timeline_fetched`, `BYTEA` per le timeline, `JSONB` per i parametri delle run e `DOUBLE PRECISION` per i tempi di attesa.
- Nello schema `core`, payload salvato nella colonna `timeline_bytea`, campi della cache Riot denominati `game_name` e `tag_line` e identificativi `run_id`/`batch_id` obbligatori su `match_timeline_fetch`.
- Aggiunto `Dockerfile.init-db`, basato su Python 3.12 e uv, per installare le dipendenze dal lockfile ed eseguire in sequenza l’inizializzazione degli schemi `core` e `metrics`.
- Aggiunta dipendenza `psycopg[binary]>=3.2` e aggiornato `uv.lock`.
- Configurato il build system setuptools in `pyproject.toml` con discovery dei package `lanefactor*` sotto `src/`; `uv sync` installa ora il progetto nel virtualenv in modalità editable.

### Changed
- Spostato il runner da `scripts/ingest_timelines.py` a `scripts/ingestion/ingest_timelines.py`, senza modifiche alla logica.
- Aggiornata la versione in `pyproject.toml` a `0.7.0` e rimossa la descrizione placeholder.
- Aggiunto il pattern `*.venv` a `.gitignore`.

### Fixed
- Risolto `ModuleNotFoundError: No module named 'lanefactor'` nell’esecuzione del runner con l’interprete del virtualenv dopo `uv sync`, senza necessità di impostare `PYTHONPATH`.

### Notes
- Gli script PostgreSQL inizializzano gli schemi in un database già esistente; non migrano i dati SQLite né modificano la persistenza dell’applicazione.

## [0.6.0] - 2026-03-03

### Added
- Preparata provenance su `match_timeline_fetch`: tracciabilità “last processed by” con `run_id/batch_id`.

### Changed
- Refactor runner `ingest_timelines` con pattern “decisione nel try, azione nel finally”:
  - Variabili di controllo batch introdotte:
    - `fetch_summary` inizializzato in modo safe (evita `UnboundLocalError` / `KeyError`)
    - `batch_action`: `"delete"` | `"finish"`
    - `batch_end_status`: `DONE` | `STOPPED` | `FAILED`
    - `stop_loop`: `True/False`
  - `finally` esegue **una sola volta**: `delete` oppure `finish` + `commit` (niente duplicazioni)

- Gestione batch vuoto (`selected_count == 0`):
  - `delete_batch(batch_id)` (batch non salvato)
  - stop loop
  - run => `DONE` (pass completato)

- Gestione batch non vuoto:
  - `finish_batch(..., DONE|STOPPED|FAILED, totals)`
  - `commit`
  - `batch_index += 1` **solo se** il batch è stato realmente registrato (finish)
  - run-level tracker aggiornato (aggregazione metriche + `total_batches += 1`)

- Semantica `STOPPED` più pulita:
  - Ctrl+C con dati: salva batch `STOPPED` + run `STOPPED`
  - Ctrl+C “precoce” senza dati: delete batch (no batch finto) + run `STOPPED`
  - Stop richiesto già in happy path: salva `STOPPED` e chiude senza giro extra
- `TelemetryTracker` reso schema-based (`ingestion_batch` vs `ingestion_run`) con default `0` per tutte le chiavi richieste.
- `RiotClient.metrics_summary` normalizzato su chiavi:
  - `total_429`, `total_4xx`, `total_5xx`, `total_sleep_seconds`
- Aggregazione run-level fatta per **incrementi** (es. `total_batches += 1`), evitando cumulati errati tipo `1+2+3...`.

### Fixed
- Fix semantica run status: eliminato il caso di `FAILED` “pulito” su run completata correttamente (es. backlog vuoto).
- Evitati errori “di fine run” dovuti a summary non inizializzati o batch duplicati.

### Notes
- Obiettivi della revisione: ridurre rumore nel runner `ingest_timelines` mantenendo robustezza, rendere coerente la semantica `DONE/STOPPED/FAILED` (niente “FAILED fantasma” a fine run pulita), migliorare leggibilità e debuggabilità di metriche batch/run, preparare tracciabilità “last processed by” su `match_timeline_fetch` (run_id/batch_id).

## [0.5.0] - 2026-03-03

### Added
- Aggiunta tabella `ingestion_batch_metrics` nel DB metrics per tracciare telemetria a livello batch (batch_index, requested_size, selected_count, ok/failed, 429/4xx/5xx, sleep, elapsed).
- Aggiunti indici `idx_batch_metrics_run_id` e `idx_batch_metrics_started_at`.
- Implementato `BatchMetricsRepository`:
  - `start_batch(...)` inserisce record batch in RUNNING
  - `finish_batch(...)` update idempotente (solo se status è RUNNING)
  - `delete_batch(...)` cleanup batch vuoti (solo se status è RUNNING)

### Changed
- Refactor `scripts/ingest_timelines.py`: spostato il loop “until done” nel runner; `fetch_and_store_timelines(batch_size)` è l’unità di batch.
- Reset metriche `RiotClient` per batch e accumulo dei totali run-level batch-by-batch.
- Migliorata la semantica dello status run:
  - DONE su completamento naturale (backlog vuoto)
  - STOPPED su stop richiesto / Ctrl+C
  - FAILED su eccezioni non gestite

### Fixed
- Fix run marcata FAILED anche se completava correttamente (set DONE su break per backlog vuoto).
- Fix batch zombie in RUNNING quando la backlog ritorna vuota (cleanup via delete_batch).
- Fix possibile KeyError sul conteggio 429 (uso di `.get(429, 0)`).
- Fix errore `DbMetrics` “property 'conn' has no setter” passando a `_conn` interno + property read-only.
- Aggiunto `commit_and_close()` per rendere più sicura la gestione lifecycle della connessione metrics.

## [0.4.1] - 2026-03-02

### Added
- `match_timeline_fetch` extended with retry scheduling fields:
  - `attempt_count INTEGER NOT NULL DEFAULT 0`
  - `last_attempt_at TEXT`
  - `next_retry_at TEXT`

### Changed
- Timeline backlog selection now respects `next_retry_at` cooldown and skips `FETCHED`:
  - pending includes: never-attempted or non-FETCHED with `next_retry_at` NULL/expired
  - excludes: `FETCHED` and non-expired cooldown entries
- Backlog time comparison switched to ISO-UTC parameter (`now_iso`) instead of `datetime('now')`
  to avoid format mismatch and ensure retries trigger correctly.
- `MatchTimelineRepository.insert_timeline` updated:
  - sets `next_retry_at` to `NULL` on success and to `now + 10 minutes` on failure
  - increments `attempt_count` atomically via SQL on every attempt (including FETCHED)
  - updates `last_attempt_at` every attempt
- Graceful stop semantics preserved in `TimelineIngestioneService`:
  - Ctrl+C sets stop flag, completes current item if payload already available, then exits batch/run cleanly
  - avoids writing "fake FAILED" rows when interruption happens mid-fetch

### Fixed
- Retry loop “lavatrice” on the same FAILED batch eliminated via `next_retry_at` cooldown.
- Retry eligibility bug caused by comparing ISO timestamps to SQLite `datetime('now')` format.
- `attempt_count` increment now works without extra SELECTs.

## [0.3.5] - 2026-02-28

### Changed
- Aggiornato il calcolo del percorso del database SQLite per riflettere la nuova struttura del progetto (correzione del path base usato da `DbSession`/repository).
- Migliorata la stabilità dell’ingestion evitando la creazione involontaria di un DB “vuoto” in path non previsti dopo refactor.

## [0.3.4] - 2026-02-28

### Added
- Metodo runner `ingest_timelines_until_done(...)` nel `TimelineIngestioneService` per eseguire l’ingestion delle timeline in loop fino a esaurimento backlog (batch ripetuti con chiusura della `DbSession` ad ogni iterazione).

### Changed
- Refactoring della struttura del progetto: moduli applicativi (services/domain/infrastructure/api) consolidati sotto `src/lanefactor/` per uniformare gli import (`lanefactor.*`) e semplificare packaging/esecuzione.

### Notes
- Gli script rimangono in `scripts/` fuori da `src/` e fungono da entrypoint “thin” che invocano i servizi.

## [0.3.2] - 2026-02-28

### Added
- Gestione del rate limit HTTP `429` basata sull’header `Retry-After` (quando presente), con fallback al backoff esponenziale.
- Delay di attesa sempre cappato da `max_sleep`.

### Changed
- `RiotClient.request()` ora preferisce `Retry-After` rispetto al backoff per i retry su `429`, rendendo l’ingestion più conforme ai rate limit di Riot.

## [0.3.1] - 2026-02-28

### Added
- Meccanismo di retry con backoff esponenziale (delay base 2s, cappato da `max_sleep`) per errori di rete (`requests.RequestException`) e per HTTP `429` / `5xx`.
- Recupero JSON centralizzato tramite `_get_json(endpoint, headers, params)` con forwarding di headers e params.

### Changed
- `RiotClient.request()` ora ritenta gli errori transitori prima di rilanciare l’eccezione all’ultimo tentativo.

### Notes
- La gestione di `429` usa attualmente il backoff; il supporto a `Retry-After` può essere aggiunto in seguito per rispettare in modo più preciso i rate limit.

## [0.3.0] - 2026-02-27
### Added
- Match ingestion service (match IDs → `puuid_match`) con paginazione oltre 100.
- Timeline ingestion service (match IDs pending → timeline) con tracciamento status/http_status.
- Repository layer: `BaseRepository`, `PuuidMatchRepository`, `MatchTimelineRepository`, `AccountCacheRepository`.
- `DbSession` per gestione connessione/transaction condivisa (fix lock SQLite).

### Changed
- Refactor: rimosso `sqlite_store`, persistenza gestita dalle repository.
- Query backlog: selezione match pending basata su join con `match_timeline_fetch` (`status='FETCHED'`).

### Fixed
- Risolto `database is locked` passando a connessione condivisa / gestione transazioni.

## [0.1.0]
### Added
- Struttura iniziale del progetto (cartelle e file base).
- `RiotClient` per il retrieve delle informazioni dalle Riot API.
- Setup iniziale del database SQLite locale e file base di inizializzazione.
- Prime funzioni per gestire transazioni SQLite.
- `paths.py` per la gestione dei percorsi (DB path).
