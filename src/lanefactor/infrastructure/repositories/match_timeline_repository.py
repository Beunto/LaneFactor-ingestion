from datetime import datetime, timezone, timedelta
from sqlalchemy.engine import Connection
from sqlalchemy import text
from uuid import UUID
import gzip, json
import os

MAX_404_ATTEMPTS = int(os.getenv("RIOT_MAX_404_ATTEMPTS"))

class MatchTimelineRepository:

    def __init__(self, connection: Connection) -> None:
        """Inizializza l’istanza e le dipendenze utilizzate dai metodi.

        Parameters
        ----------
        connection : Connection
            Connessione SQLAlchemy usata senza eseguire commit nel repository.

        Returns
        -------
        None
            Nessuna restituzione di valore.
        """

        self._connection = connection

    def _decode_payload(self, timeline_bytea: bytes | None) -> dict | None:
        """Decomprime e interpreta il payload di una timeline salvata.

        Operazione inversa del salvataggio in insert_timeline: gzip e poi JSON.
        Un gzip corrotto solleva l’eccezione di gzip senza essere intercettata.

        Parameters
        ----------
        timeline_bytea : bytes | None
            Contenuto della colonna timeline_bytea, JSON compresso con gzip.

        Returns
        -------
        dict | None
            Timeline come dizionario, oppure None se il contenuto è assente o vuoto.
        """

        if not timeline_bytea:
            return 

        payload = gzip.decompress(timeline_bytea)
        return json.loads(payload)


    def count_pending_seed_timelines(self) -> int:
        """Conta le timeline FETCHED da cui non sono ancora stati estratti i seed.

        Usa lo stesso filtro di fetch_pending_seed_timelines (status FETCHED e
        seeds_extracted_at NULL), così il conteggio coincide con le righe che il
        job leggerà. È una sola lettura: non modifica nulla e non decomprime i
        payload.

        Returns
        -------
        int
            Numero di timeline ancora da leggere; 0 se non ne restano.
        """

        query = text("""
            SELECT COUNT(*) 
            FROM core.match_timeline
            WHERE status = 'FETCHED' AND seeds_extracted_at IS NULL
        """)
        
        result = self._connection.execute(query)
        return result.fetchone()[0]


    def fetch_pending_seed_timelines(self, limit: int) -> list[tuple[str, dict|None]]:
        """Legge un blocco di timeline FETCHED da cui non sono ancora stati estratti i seed.

        Seleziona le righe con seeds_extracted_at NULL, dalla più vecchia per
        fetched_at, e ne decomprime il payload. Non modifica nulla: la marcatura
        avviene con mark_seeds_extracted, dopo l’inserimento dei seed.

        Parameters
        ----------
        limit : int
            Numero massimo di timeline da leggere; limita anche la memoria usata.

        Returns
        -------
        list[tuple[str, dict]]
            Coppie (match_id, timeline decompressa) in ordine di fetched_at.
            La lista è vuota se non restano timeline da leggere. Il payload
            può essere None se il contenuto salvato è vuoto.
        """

        query = text("""
            SELECT match_id, timeline_bytea
            from core.match_timeline
            WHERE status = 'FETCHED' and seeds_extracted_at IS NULL
            ORDER BY fetched_at
            LIMIT :limit
        """)

        result = self._connection.execute(query, {"limit": limit})

        pending_timelines = []
        for row in result.fetchall():
            match_id, timeline_bytea = row
            payload = self._decode_payload(timeline_bytea)
            pending_timelines.append((match_id, payload))

        return pending_timelines


    def mark_seeds_extracted(self, match_ids: list[str]) -> None:
        """Segna come lette per i seed le timeline indicate.

        Imposta seeds_extracted_at all’istante corrente. Il CHECK della tabella
        consente il marcatore solo su righe FETCHED. Da chiamare per ultima,
        nella stessa transazione dell’inserimento dei seed. Un match_id assente
        non produce effetti; con una lista vuota non viene eseguita alcuna query.
        Il commit resta al chiamante.

        Parameters
        ----------
        match_ids : list[str]
            Identificatori dei match le cui timeline sono state lette; una lista vuota è ammessa.

        Returns
        -------
        None
            Nessuna restituzione di valore.
        """

        if not match_ids:
            return

        now = datetime.now(timezone.utc)

        query = text("""
            UPDATE core.match_timeline
            SET seeds_extracted_at = :now
            WHERE match_id = :match_id
        """)

        self._connection.execute(query, [{"now": now, "match_id": match_id} for match_id in match_ids])
    

    def insert_timeline(self, match_id:str, status:str, https_status:int | None, match_timeline: dict | None, 
                        run_id:UUID|str, batch_id:UUID|str|None, max_404_attempts:int=MAX_404_ATTEMPTS) -> None:
        """Registra un tentativo senza sovrascrivere una timeline già FETCHED.

        Con risposta 200 e payload non vuoto salva JSON compresso con gzip; negli
        altri casi pianifica un retry tra dieci minuti. Inserisce il contatore a uno
        o lo incrementa aggiornando un record non FETCHED. Un record già FETCHED
        rimane invariato, compresi contatore e provenienza.

        Un 404 è considerato definitivo solo se si ripete: quando il tentativo
        precedente era già un 404 e il contatore raggiunge max_404_attempts, lo
        stato salvato è UNAVAILABLE e next_retry_at è NULL, così il match esce
        dalla sync e dalle altre selezioni di download. Un 404 dopo errori di
        altro tipo (5xx, timeout) resta FAILED con retry. Una successiva
        risposta 200 può comunque sovrascrivere un record UNAVAILABLE. Non
        esegue commit.

        Parameters
        ----------
        match_id : str
            Identificatore del match.
        status : str
            Stato del tentativo da registrare, normalmente FETCHED o FAILED; la
            query lo sostituisce con UNAVAILABLE nel caso descritto sopra.
        https_status : int | None
            Codice HTTP ricevuto oppure None in assenza di risposta.
        match_timeline : dict | None
            Payload JSON della timeline oppure None in caso di fallimento.
        run_id : UUID | str
            UUID della run, come oggetto UUID o stringa valida.
        batch_id : UUID | str | None
            Identificatore del batch; None è ammesso dove indicato dal tipo.
        max_404_attempts : int
            Numero di tentativi totali a cui un 404 ripetuto rende la timeline
            UNAVAILABLE; maggiore di zero. Default: da RIOT_MAX_404_ATTEMPTS.

        Returns
        -------
        None
            Nessuna restituzione di valore.
        """

        # Setto datetime per il fetched_at, comprimo il json in un blob e definisco le righe da inserire
        now_dt = datetime.now(timezone.utc)

        if https_status == 200 and match_timeline:
            timeline_bytea = gzip.compress(json.dumps(match_timeline).encode("utf-8"))
            fetched_at = now_dt
            next_retry_at = None
        else:
            next_retry_at = (now_dt + timedelta(minutes=10))
            timeline_bytea = None
            fetched_at = None

        last_attempt_at = now_dt

        row = {
            "match_id": match_id,
            "status": status,
            "fetched_at": fetched_at,
            "https_status": https_status,
            "timeline_bytea": timeline_bytea,
            "last_attempt_at": last_attempt_at,
            "next_retry_at": next_retry_at,
            "run_id": run_id,
            "batch_id": batch_id,
            "max_404_attempts": max_404_attempts
        }

        # Definisco l'insert
        query = text("""
            INSERT INTO core.match_timeline (
                match_id, status, fetched_at, https_status, timeline_bytea,
                attempt_count, last_attempt_at, next_retry_at,
                run_id, batch_id
            )
            VALUES (:match_id, :status, :fetched_at, :https_status, :timeline_bytea, 1, :last_attempt_at, :next_retry_at, :run_id, :batch_id)
            ON CONFLICT (match_id) DO UPDATE SET
                status = CASE 
                    WHEN EXCLUDED.https_status = 404 
                    AND match_timeline.https_status = 404
                    AND match_timeline.attempt_count+1 >= :max_404_attempts
                    THEN 'UNAVAILABLE' 
                    ELSE EXCLUDED.status END,
                fetched_at = EXCLUDED.fetched_at,
                https_status = EXCLUDED.https_status,
                timeline_bytea = EXCLUDED.timeline_bytea,
                attempt_count = match_timeline.attempt_count + 1,
                last_attempt_at = EXCLUDED.last_attempt_at,
                next_retry_at = CASE
                    WHEN EXCLUDED.https_status = 404 
                    AND match_timeline.https_status = 404
                    AND match_timeline.attempt_count+1 >= :max_404_attempts
                    THEN NULL 
                    ELSE EXCLUDED.next_retry_at END,
                run_id = EXCLUDED.run_id,
                batch_id = EXCLUDED.batch_id
            WHERE match_timeline.status != 'FETCHED'
        """)

        # Eseguo
        self._connection.execute(query, row)