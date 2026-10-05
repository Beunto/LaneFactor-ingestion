# Artifact di progetto

Indice delle pagine pubblicate come Artifact su claude.ai (diagrammi, mappe,
report). Sono **private**: le apre solo chi le ha pubblicate o chi ha ricevuto
accesso dal menu Share della pagina. Il link resta valido tra una sessione e
l'altra.

Il codice sorgente delle pagine non è nel repository: per modificarne una si
passa l'URL a Claude, che la rilegge dal link e la ripubblica sullo stesso
indirizzo. Dopo un cambio importante nel flusso (nuovo job, schema modificato)
conviene chiedere di aggiornare la pagina corrispondente e aggiornare qui la
data.

| Pagina | Contenuto | Link | Ultimo aggiornamento |
|---|---|---|---|
| LANEFACTOR (tendina: Mappa ingestion · Osservatorio · Diagnostica · Documentazione) | **Mappa ingestion** (vista predefinita): sei schede con navigatore su ciclo dello snowball, pipeline (valanga inclusa, con simulatore del rate limit), livelli del codice, schema PostgreSQL, ciclo di vita delle run (con albero interattivo) e stato del lavoro. **Osservatorio**: replay di una partita da timeline e dettaglio (mappa con i ritratti dei campioni, oro, eventi, ricerca per Riot ID tramite hash, pulsante Template, scheda del campione con oggetti, abilità, statistiche e rune a ogni istante), tab Riepilogo con il dettaglio finale (squadre, ban, obiettivi, build) e, in una pagina a parte, **Diagnostica** con la salute dell'ingestion (qui andranno gli altri controlli). **Documentazione**: albero della directory e una scheda apribile per ogni componente (9 runner, 6 service, 15 tra infrastruttura e repository) con cosa fa, a cosa serve, la sua promessa e i problemi possibili, scritta a mano sul codice e da aggiornare quando un componente cambia, più un glossario di 45 termini (la stessa fonte di `docs/glossario.md`). Il replay procede a passi (un passo per minuto registrato e per ogni kill, torre o mostro, a 0,5×, 1× o 2×) la mappa ha zoom (rotella, pizzico, pulsanti) e spostamento, con riquadro di orientamento e modalità che segue il giocatore selezionato, e la timeline usa le icone reali di strutture e mostri. L'Osservatorio legge `matches.json`, `players.json`, `assets.json` (nomi e icone da Data Dragon) e `dashboard.json` pubblicati accanto alla pagina; senza questi file mostra dati di esempio, formato in [export-spec.md](export-spec.md) | https://claude.ai/artifact/YLL3BUJQarijC6TgiEKuqC | 2026-10-01 (nuova scheda Documentazione; mappa aggiornata con i tre job di sync `match_sync`, `match_timeline_sync` e `match_detail_sync` al posto di `timelines_matches_sync`, e con la valanga `snowball` scritta, lo stato restituito da timeline e dettaglio e le decisioni su `mark_ingested`; mappa allineata a dettaglio e classe madre; replay con scheda campione e Riepilogo; Osservatorio unito alla mappa con la tendina; replay con la minimappa ufficiale di Data Dragon e le icone del Community Dragon, tooltip sulla timeline, velocità 1×-120×; ancora con dati di esempio) |

## Come aggiungere una voce

Quando una nuova pagina viene pubblicata, aggiungere una riga alla tabella con
titolo, contenuto in una frase, URL e data. Per ritrovare le pagine
pubblicate: `/artifacts` nel terminale di Claude Code, oppure la galleria su
claude.ai/code/artifacts.
