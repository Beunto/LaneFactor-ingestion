# Glossario

I termini del progetto, in un posto solo. La stessa pagina è nella scheda Documentazione > Glossario dell'artifact; la fonte è questo file, quindi vanno aggiornati insieme.

## Dati di Riot

**PUUID**  
L'identificatore unico e permanente di un account Riot: non cambia quando il giocatore cambia nome. È la chiave di `core.puuid_seed`, `core.puuid_match` e `core.riot_id_cache`.

**Riot ID**  
Il nome visibile di un giocatore, nella forma `gameName#tagLine`. Può cambiare, per questo il programma lavora sul PUUID e usa il Riot ID solo per partire (`ingest_player_game`).

**Match**  
Una partita, identificata da un `match_id` come `EUW1_1234567890`. I match sono globali: una partita giocata da dieci persone è un solo match, con dieci associazioni.

**Coda ranked solo/duo**  
La modalità che il progetto raccoglie, `queue_id` 420. Tutte le richieste degli ID chiedono solo questa coda.

**Timeline**  
Il payload match-v5 `/matches/{id}/timeline`: un'istantanea al minuto (posizioni, oro, livello) più gli eventi (kill, torri, mostri). Contiene i PUUID dei partecipanti, ma non campione, ruolo o rune.

**Dettaglio**  
Il payload match-v5 `/matches/{id}`: campioni, ruoli, rune, statistiche finali, versione di gioco, coda, durata ed esito. È un concetto separato dalla timeline e richiede una richiesta a parte per ogni match.

**Payload**  
Il JSON grezzo restituito da Riot, salvato così com'è, compresso in gzip, in una colonna `BYTEA`. Le colonne estratte (`game_version`, `queue_id`, `game_duration_s`, `end_of_game_result`) servono a filtrare senza decomprimere.

**Patch**  
La versione del gioco (`game_version`, per esempio `16.14`). Cambia le regole del gioco: partite di patch diverse non sono sempre confrontabili.

**Rimessa**  
Una partita brevissima, rifatta o abbandonata. Non viene scartata all'ingestion: si filtra in analisi con `game_duration_s`.

**Associazione**  
Una riga di `core.puuid_match`: dice che quel giocatore ha giocato quel match. La coppia (PUUID, match) è unica.

## Lo snowball

**Snowball (valanga)**  
Il campionamento che fa crescere il pool di partite a valanga: si parte da un giocatore, dalle sue partite si scoprono gli avversari, e dalle loro partite altri ancora. Il job che lo esegue si chiama `snowball`; nei discorsi «la valanga».

**Seed**  
Un PUUID noto da visitare, cioè un punto di partenza per chiedere i suoi match a Riot. Sta in `core.puuid_seed` e si estrae dalle timeline già scaricate con `update_seed`.

**Rotazione dei seed**  
L'ordine in cui `snowball` sceglie i seed: prima i mai ingeriti (`last_ingested_at` NULL), poi i meno recenti. Nessun seed va mai a riposo.

**Seed ingerito**  
Un seed per cui è stato completato un giro: ID registrati e run di timeline e dettaglio terminate senza stop. I singoli download falliti non lo impediscono e un seed senza match ranked è segnato comunque.

**Seed iniziale**  
Il giocatore da cui parte tutto: lo registra `ingest_player_game` dal Riot ID.

## Stati e recupero

**Flag globali**  
`timeline_fetched` e `detail_fetched` in `core.match`: due flag indipendenti. TRUE vuol dire che quel payload è scaricato e salvato; FALSE che non lo è ancora, oppure che non lo sarà (`UNAVAILABLE`).

**Stato di un tentativo**  
`FETCHED` (scaricato), `FAILED` (fallito, con retry) o `UNAVAILABLE` (perso). `PENDING` e `IN_PROGRESS` esistono nello schema ma oggi nessun codice li scrive.

**Retry e cooldown**  
Dopo un fallimento il match non si riprova subito: `next_retry_at` lo rimanda di 10 minuti. Finché non scade, quel match non viene selezionato da nessun job.

**UNAVAILABLE**  
Lo stato terminale per un payload non recuperabile: un 404 che si ripete (con il tentativo precedente anch'esso 404) a `RIOT_MAX_404_ATTEMPTS` tentativi. Non si riprova più; un 200 successivo può comunque sovrascriverlo.

**Scaricabile ora**  
Un payload è scaricabile ora quando il suo flag è FALSE, la riga manca oppure non è `FETCHED` né `UNAVAILABLE`, e `next_retry_at` è assente o scaduto. È la condizione di tutte le selezioni.

**Arretrato (backlog)**  
I match registrati per cui manca un payload e che i job di sync devono ancora recuperare.

**Partizione**  
La divisione dei match tra i tre job di sync in base ai due flag, in modo che ogni match abbia un solo job: `match_sync` (né timeline né dettaglio), `match_timeline_sync` (dettaglio già scaricato), `match_detail_sync` (timeline già scaricata).

**Job di sync**  
I tre job di recupero, facoltativi e fuori dal ciclo dello snowball: riscaricano ciò che è rimasto indietro. Non vanno lanciati in parallelo.

**Match completo**  
Un match con entrambi i flag TRUE: ha timeline e dettaglio. È l'unico utile come esempio per le analisi.

**Idempotente**  
Un'operazione che si può rilanciare senza duplicare dati né cambiare l'esito: `update_seed` e i job di sync lo sono.

## Run e metriche

**Runner**  
Un file di `scripts/ingestion/`: un comando che si lancia a mano o da Kestra, oppure una funzione che i comandi chiamano. Decide cosa lanciare e in che ordine.

**Run**  
Una riga di `metrics.ingestion_run_metrics`: un'esecuzione di un job, con stato, esiti e tempi.

**Run radice e run figlia**  
Le run formano un albero tramite `parent_run_id`. La radice non fa richieste e non ha metriche proprie; le figlie (`ingest_ranked_match_ids`, `ingest_timelines`, `ingest_details`) fanno il lavoro. L'esecuzione di una radice si legge sommando le figlie.

**Batch**  
Un blocco di al massimo 20 match dentro `ingest_timelines` o `ingest_details`. Ha una riga in `metrics.ingestion_batch_metrics` e una transazione propria.

**Giro**  
Un'unità di lavoro di un job: in `snowball`, il lavoro su un seed; nei job di sync, una selezione di `--limit` match. Ogni giro apre le proprie run figlie.

**Stati di una run**  
`RUNNING`, `DONE`, `FAILED`, `STOPPED`, `MISSING`. Una run si chiude sempre nel `finally`, anche dopo un errore o un Ctrl+C.

**STOPPED assorbito**  
Un Ctrl+C durante un download viene intercettato dal servizio, che chiude la run `STOPPED` senza sollevare un'eccezione. Il chiamante lo vede dal valore restituito (`DONE` o `STOPPED`). Il processo, però, termina con codice 0.

**Service**  
La logica di dominio in `services/ingestion/`: cosa vuol dire scaricare, registrare, estrarre.

**Repository**  
Una classe per tabella, con le query. Non ha logica di flusso.

**Infrastruttura**  
Tutto ciò che parla col mondo esterno: Riot, PostgreSQL, i segnali, i log.

## Rate limit e arresto

**Rate limit**  
Il limite di richieste che Riot accetta per chiave. Una chiave di sviluppo ammette circa 100 richieste ogni 2 minuti, e oltre il limite Riot risponde 429.

**Pacing**  
La pausa minima tra due richieste (`RIOT_MIN_REQUEST_INTERVAL`, 1,25 s nell'esempio), che mantiene il ritmo sotto il rate limit. Vale per processo: due job insieme sulla stessa chiave raddoppiano il ritmo.

**429 e Retry-After**  
La risposta con cui Riot dice «troppe richieste». `RiotClient` aspetta il numero di secondi indicato da `Retry-After` e riprova.

**Chiave di sviluppo e di produzione**  
La chiave di sviluppo ha limiti bassi e scade; per un uso continuo serve una chiave approvata da Riot.

**block_sigint**  
Il gestore di contesto che sospende il Ctrl+C durante le scritture critiche: il segnale resta in sospeso fino al commit, così una scrittura già in corso non si interrompe.

**SIGTERM e stop grace period**  
`docker stop` manda `SIGTERM`, che il progetto rimappa su `SIGINT` per avere la stessa chiusura ordinata del Ctrl+C. Docker aspetta 10 secondi (lo stop grace period), poi manda `SIGKILL`, che nessun codice intercetta.

**Contesto di log**  
`run_id` e `batch_id` viaggiano in `ContextVar`, così ogni riga di log dei retry dice a quale run e batch appartiene senza passarli a ogni funzione.