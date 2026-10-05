# Specifica dell'export per l'artifact (replay e dashboard)

L'artifact non raggiunge né Postgres né Riot: legge solo file JSON pubblicati
insieme alla pagina. Questo documento fissa il formato dei file che lo
script di export deve produrre. Tutti i file sono UTF-8, con `"version"` al
primo livello (`matches.json` è alla versione 2: le partite possono avere anche
i campi del dettaglio, vedi la sezione 1b; la versione 1 resta accettata dalla
pagina).

Valgono due regole di privacy:

- Nessun PUUID esce dal database.
- Nessun nome#tag compare in chiaro: la ricerca usa un hash (vedi `players.json`).

## 1. `matches.json`

Solo i match con `status = 'FETCHED'` e payload presente in cui compare almeno un
giocatore presente in `core.riot_id_cache` (via `core.puuid_match`). Nessun altro
match viene esportato. Se sono più di 150, tenere i più recenti. Dimensione
attesa: circa 20-25 KB a match (verificato su due timeline reali).

```json
{
  "version": 1,
  "exported_at": "2026-10-01T12:00:00Z",
  "matches": [
    {
      "match_id": "EUW1_7123456789",
      "duration_s": 1893,
      "frame_interval_s": 60,
      "winner": 100,
      "frames": [
        { "t": 0, "p": [[x, y, gold, level, cs, jungle_cs, hp, hp_max], "... 10 voci, indice = participantId - 1"] }
      ],
      "events": [
        { "k": "KILL", "t": 301234, "killer": 3, "victim": 8, "assists": [1, 2], "x": 5200, "y": 9100 },
        { "k": "BUILDING", "t": 702000, "team": 200, "killer": 3, "type": "TOWER_BUILDING", "lane": "MID_LANE", "tt": "OUTER_TURRET", "x": 5000, "y": 5200 },
        { "k": "MONSTER", "t": 640000, "killer": 2, "type": "DRAGON", "sub": "FIRE_DRAGON", "x": 9800, "y": 4400 },
        { "k": "PLATE", "t": 312097, "team": 100, "killer": 0, "lane": "MID_LANE", "x": 5846, "y": 6396 }
      ]
    }
  ]
}
```

Da dove si prende ogni campo (struttura della timeline Riot v5, dopo aver
decompresso il gzip e fatto `json.loads`):

| Campo | Origine |
|---|---|
| `match_id` | `metadata.matchId` |
| `frame_interval_s` | `info.frameInterval / 1000` |
| `duration_s` | `timestamp` dell'ultimo frame, diviso 1000 e arrotondato |
| `winner` | `winningTeam` dell'evento `GAME_END` (100 o 200), altrimenti `null` |
| `frames[].t` | `timestamp` del frame, in millisecondi |
| `frames[].p[i]` | per `participantId = i + 1`, da `participantFrames[str(i + 1)]`: `position.x`, `position.y`, `totalGold`, `level`, `minionsKilled + jungleMinionsKilled`, `jungleMinionsKilled`, `championStats.health`, `championStats.healthMax`. Tutti interi (arrotondare la vita) |
| `KILL` | evento `CHAMPION_KILL`: `killerId`, `victimId`, `assistingParticipantIds`, `position`, `timestamp`. Se `killerId` è 0 (torre, minion) tenere 0 |
| `BUILDING` | evento `BUILDING_KILL`: `teamId` (la squadra che perde la struttura), `killerId`, `buildingType`, `laneType`, `towerType` (campo `tt`, può mancare per gli inibitori), `position` (coincide con la posizione della struttura) |
| `MONSTER` | evento `ELITE_MONSTER_KILL`: `killerId`, `monsterType`, `monsterSubType` (può mancare: mettere `null`), `position` |
| `PLATE` | evento `TURRET_PLATE_DESTROYED`: `teamId` (la squadra che perde la piastra), `killerId` (0 se un minion), `laneType`, `position` (la torre) |

Gli acquisti e le abilità vanno esportati a parte (sezione 1b); gli altri tipi di evento (ward, livelli) vanno scartati. Gli eventi `WARD_PLACED` e `WARD_KILL` non hanno una posizione nelle timeline reali, quindi le ward non si possono mostrare sulla mappa. Gli eventi
vanno ordinati per `t` crescente.

I partecipanti 1-5 sono la squadra 100 (blu) e 6-10 la squadra 200 (rossa). La corrispondenza `participantId` → PUUID sta in `info.participants` (campi `participantId` e `puuid`): usare quella, non l'indice di `metadata.participants`. La
pagina ne deriva squadra e ruolo dall'ordine: top, jungle, mid, bot, support.

## 1b. Campi aggiunti dal dettaglio (`matches.json` versione 2)

Servono alla scheda del campione e al tab Riepilogo. Sono tutti facoltativi: una
partita senza `detail` (match con `detail_fetched = FALSE`) si vede come prima, con
nomi inventati. Per averli servono entrambi i payload del match
(`core.match_timeline` e `core.match_detail`).

```json
{
  "match_id": "EUW1_7883441286",
  "frames": [ { "t": 60000, "p": [ "... come sopra ..." ],
                "x": [[current_gold, xp, ad, ap, armor, mr, attack_speed, move_speed, ability_haste, dmg_to_champs, dmg_taken], "... 10 voci"] } ],
  "events": [ { "k": "KILL", "t": 125103, "killer": 9, "victim": 1, "assists": [10], "x": 13106, "y": 2299,
                "bounty": 400, "streak": 0, "fb": true, "mk": 2 } ],
  "inv":    { "1": [[0, "b", 1055], [135000, "s", 1055], [200000, "d", 2003], [138030, "u", 1001, 0]] },
  "skills": { "1": [[0, 4], [73835, 1]] },
  "detail": {
    "patch": "16.12", "queue": 420, "mode": "CLASSIC", "duration_s": 1841, "ended": "GameComplete", "start": "2026-06-11T08:41:28Z",
    "players": [ { "pid": 1, "champ_id": 164, "champ": "Camille", "role": "TOP", "win": true, "spells": [4, 12],
                   "perks": { "prim_style": 8400, "prim": [8437, 8401, 8473, 8451], "sub_style": 8300, "sub": [8345, 8304], "shards": [5005, 5008, 5001] },
                   "level": 18, "kda": [2, 6, 7], "cs": 253, "gold": 12610, "dmg": 19737, "taken": 35462, "heal": 0, "cc": 12, "vision": 20,
                   "wards": [8, 2, 3], "items": [3074, 3161, 3133, 1037, 3078, 2422, 3340], "dead_s": 200, "spree": 2, "multi": [0, 0, 0, 0],
                   "turrets": 1, "dragons": 0, "barons": 0, "fb": false } ],
    "teams": [ { "id": 100, "win": true, "bans": [360, 555], "obj": { "tower": 9, "dragon": 2, "baron": 1, "riftHerald": 1, "horde": 3, "inhibitor": 1, "champion": 29, "atakhan": 0 }, "first": ["horde", "inhibitor"] } ]
  }
}
```

| Campo | Origine |
|---|---|
| `frames[].x[i]` | `participantFrames[str(i + 1)]`: `currentGold`, `xp`, `championStats.attackDamage`, `abilityPower`, `armor`, `magicResist`, `attackSpeed`, `movementSpeed`, `abilityHaste`, `damageStats.totalDamageDoneToChampions`, `totalDamageTaken` (interi) |
| `KILL.bounty`, `KILL.streak` | `bounty` e `killStreakLength` dello stesso `CHAMPION_KILL` |
| `KILL.fb`, `KILL.mk` | dagli eventi `CHAMPION_SPECIAL_KILL` con lo stesso `timestamp` e `killerId`: `KILL_FIRST_BLOOD` mette `fb = true`, `KILL_MULTI` mette `mk = multiKillLength` |
| `inv[pid]` | eventi `ITEM_PURCHASED` (`"b"`), `ITEM_SOLD` (`"s"`), `ITEM_DESTROYED` (`"d"`) con `[timestamp, op, itemId]`, e `ITEM_UNDO` (`"u"`) con `[timestamp, "u", beforeId, afterId]`. Si scartano gli eventi con `participantId = 0` (oggetti di missione dati a inizio partita) |
| `skills[pid]` | `SKILL_LEVEL_UP` con `levelUpType = NORMAL`: `[timestamp, skillSlot]` (1-4 = Q, W, E, R) |
| `detail.patch` | `info.gameVersion` ridotto a `major.minor` |
| `detail.queue`, `mode`, `duration_s`, `ended`, `start` | `info.queueId`, `gameMode`, `gameDuration`, `endOfGameResult`, `gameStartTimestamp` (ISO 8601 in UTC) |
| `detail.players[i]` | `info.participants` ordinati per `participantId` (indice = `participantId - 1`). Non esportare `riotIdGameName`, `riotIdTagline`, `puuid`, `summonerName` né i campi di ping, missioni o `challenges` |
| `perks` | `perks.styles[]` (`description` = `primaryStyle`/`subStyle`: `style` e i `perk` delle `selections`) e `perks.statPerks` (`offense`, `flex`, `defense`) |
| `cs` | `totalMinionsKilled + neutralMinionsKilled` |
| `detail.teams[]` | `info.teams`: `teamId`, `win`, `bans[].championId` (escluso -1), `objectives.<nome>.kills` e, in `first`, i nomi con `first = true` |

L'inventario a un istante si ricostruisce rigiocando `inv` fino a quel momento,
con il minimo a zero. Non è perfetto: la timeline non registra il trinket
iniziale, gli oggetti di missione dei support né quelli dati dalla runa Magical
Footwear (la pagina li aggiunge con una regola fissa). Per questo, a fine partita,
la pagina mostra gli oggetti di `detail.players[].items` e non la ricostruzione.

## 2. `players.json`

Serve per la ricerca per nome#tag senza mettere i nomi nella pagina.

```json
{
  "version": 1,
  "players": {
    "9f2c…64 caratteri esadecimali…": [
      { "match_id": "EUW1_7123456789", "pid": 4 }
    ]
  }
}
```

- La chiave è lo SHA-256 esadecimale della stringa
  `game_name.strip().lower() + "#" + tag_line.strip().lower()`, codificata in UTF-8.
  La pagina calcola lo stesso hash sul testo digitato.
- Si include un giocatore solo se compare in `core.riot_id_cache`.
- Per ogni giocatore si elencano solo i match presenti in `matches.json`.
- `pid` è il `participantId` del suo PUUID in `info.participants`.

## 3. `dashboard.json`

```json
{
  "version": 1,
  "generated_at": "2026-10-01T12:00:00Z",
  "counts": {
    "matches_total": 0,
    "matches_timeline_pending": 0,
    "timelines": { "FETCHED": 0, "FAILED": 0, "PENDING": 0, "IN_PROGRESS": 0 },
    "timelines_seeds_unread": 0,
    "seeds_total": 0,
    "seeds_never_ingested": 0,
    "players_cached": 0
  },
  "runs": [
    { "run_id": "7c1e0a42", "parent_run_id": null, "pipeline": "ingest_player_game", "status": "DONE",
      "started_at": "2026-10-01T10:00:00Z", "ended_at": "2026-10-01T10:02:10Z",
      "total_ok": 0, "total_failed": 0, "total_429": 0, "total_4xx": 0, "total_5xx": 0,
      "total_sleep_seconds": 0, "total_elapsed_ms": 0 }
  ],
  "batches": [
    { "run_id": "7c1e0a42", "batch_index": 0, "status": "DONE", "started_at": "2026-10-01T10:00:20Z",
      "requested_size": 20, "selected_count": 20, "total_ok": 0, "total_failed": 0,
      "total_429": 0, "total_5xx": 0, "total_sleep_seconds": 0, "total_elapsed_ms": 0 }
  ],
  "daily": [
    { "day": "2026-09-30", "ok": 0, "failed": 0, "t429": 0, "t5xx": 0 }
  ]
}
```

`run_id` si accorcia ai primi 8 caratteri (esportare comunque la relazione
`parent_run_id` con la stessa abbreviazione). `runs` contiene le ultime 40 run,
`batches` gli ultimi 80 batch, `daily` gli ultimi 30 giorni. Le date sono ISO 8601
in UTC.

Query di partenza (nomi di colonna dallo schema dell'artifact):

```sql
-- counts
SELECT count(*) FROM core.match;
SELECT count(*) FROM core.match WHERE timeline_fetched = FALSE;
SELECT status, count(*) FROM core.match_timeline GROUP BY status;
SELECT count(*) FROM core.match_timeline
  WHERE status = 'FETCHED' AND seeds_extracted_at IS NULL;
SELECT count(*), count(*) FILTER (WHERE last_ingested_at IS NULL) FROM core.puuid_seed;
SELECT count(*) FROM core.riot_id_cache;

-- runs
SELECT run_id, parent_run_id, pipeline, status, started_at, ended_at,
       total_ok, total_failed, total_429, total_4xx, total_5xx,
       total_sleep_seconds, total_elapsed_ms
FROM metrics.ingestion_run_metrics ORDER BY started_at DESC LIMIT 40;

-- batches
SELECT run_id, batch_index, status, started_at, requested_size, selected_count,
       total_ok, total_failed, total_429, total_5xx, total_sleep_seconds, total_elapsed_ms
FROM metrics.ingestion_batch_metrics ORDER BY started_at DESC LIMIT 80;

-- daily
SELECT started_at::date AS day, sum(total_ok) AS ok, sum(total_failed) AS failed,
       sum(total_429) AS t429, sum(total_5xx) AS t5xx
FROM metrics.ingestion_run_metrics
WHERE started_at >= now() - interval '30 days'
GROUP BY 1 ORDER BY 1;
```

## Come arrivano alla pagina

Metti i tre file in una cartella fuori dal repository (contengono dati reali) e
dai il percorso a Claude: li pubblica come file della pagina, accanto
all'HTML. Per aggiornarli si rilancia lo script e si ripubblica.

## 4. `assets.json`

Nomi e icone per le partite con dettaglio. Le icone sono data URI WebP, perché la
pagina non può caricare immagini da altri host. Si genera con
`build_assets.py` (scratchpad della sessione, da portare nella repo se serve)
da Data Dragon: serve la versione del client della partita (per `16.12.x` si usa
`16.12.1`), i nomi in italiano (`it_IT`) e i soli id che compaiono nei payload.

```json
{
  "version": "16.12.1",
  "items":  { "3074": { "n": "nome in italiano", "g": 3300, "i": "data:image/webp;base64,…" } },
  "champs": { "164":  { "k": "Camille", "n": "nome in italiano", "i": "data:image/webp;base64,…" } },
  "spells": { "4":    { "n": "nome in italiano", "i": "…" } },
  "runes":  { "8437": { "n": "nome in italiano", "i": "…" } },
  "styles": { "8400": { "n": "nome in italiano", "i": "…" } },
  "ui":     { "tower": { "i": "…" }, "baron": { "i": "…" } }
}
```

Chiavi: `items` per `itemId`, `champs` per `championId`, `spells` per `summonerXId`,
`runes` per `perk` e `styles` per `style`. `ui` contiene le icone della minimappa (Community Dragon) che la timeline del replay usa per strutture e mostri: `tower`, `inhibitor`, `nexus`, `baron`, `herald`, `grub`, `atakhan`, `dragon` e `dragon_mountain`, `dragon_infernal`, `dragon_ocean`, `dragon_cloud`, `dragon_hextech`, `dragon_chemtech`, `dragon_elder`; senza di loro la timeline torna ai quadrati e ai rombi. Con 104 oggetti, 19 campioni, 6
incantesimi, 37 rune e 15 icone `ui` il file pesa circa 370 KB (icone ridimensionate a 56, 72,
48 e 48 pixel). La pagina funziona anche senza questo file, ma mostra segnaposto
al posto delle icone.
