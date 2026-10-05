from datetime import datetime, timezone, timedelta
from sqlalchemy.engine import Connection
from sqlalchemy import text
from uuid import UUID
import gzip, json
import os

MAX_404_ATTEMPTS = int(os.getenv("RIOT_MAX_404_ATTEMPTS"))

class MatchDetailRepository:

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

    def _decode_payload(self, detail_bytea: bytes | None) -> dict | None:
        """Decomprime e interpreta il payload di un dettaglio salvato.

        Operazione inversa del salvataggio in insert_detail: gzip e poi JSON.
        Un gzip corrotto solleva l’eccezione di gzip senza essere intercettata.

        Parameters
        ----------
        detail_bytea : bytes | None
            Contenuto della colonna detail_bytea, JSON compresso con gzip.

        Returns
        -------
        dict | None
            Dettaglio come dizionario, oppure None se il contenuto è assente o vuoto.
        """

        if not detail_bytea:
            return 

        payload = gzip.decompress(detail_bytea)
        return json.loads(payload)
    

    def insert_detail(self, match_id:str, status:str, https_status:int | None, match_detail: dict | None, 
                        run_id:UUID|str, batch_id:UUID|str|None, max_404_attempts:int=MAX_404_ATTEMPTS) -> None:
        """Registra un tentativo senza sovrascrivere un dettaglio già FETCHED.

        Con risposta 200 e payload non vuoto salva JSON compresso con gzip ed
        estrae da info versione di gioco, queue, durata ed esito finale; negli
        altri casi pianifica un retry tra dieci minuti. Inserisce il contatore a uno
        o lo incrementa aggiornando un record non FETCHED. Un record già FETCHED
        rimane invariato, compresi contatore e provenienza.

        Un 404 è considerato definitivo solo se si ripete: quando il tentativo
        precedente era già un 404 e il contatore raggiunge max_404_attempts, lo
        stato salvato è UNAVAILABLE e next_retry_at è NULL, così il match esce
        dalla sync e dalle altre selezioni di download. Un 404 dopo errori di
        altro tipo (5xx, timeout) resta FAILED con retry. Una successiva
        risposta 200 può comunque sovrascrivere un record UNAVAILABLE.

        Non esegue commit. Se il payload 200 non contiene info, gameVersion,
        queueId o gameDuration solleva KeyError.

        Parameters
        ----------
        match_id : str
            Identificatore del match.
        status : str
            Stato del tentativo da registrare, normalmente FETCHED o FAILED; la
            query lo sostituisce con UNAVAILABLE nel caso descritto sopra.
        https_status : int | None
            Codice HTTP ricevuto oppure None in assenza di risposta.
        match_detail : dict | None
            Payload JSON del dettaglio oppure None in caso di fallimento.
        run_id : UUID | str
            UUID della run, come oggetto UUID o stringa valida.
        batch_id : UUID | str | None
            Identificatore del batch; None è ammesso dove indicato dal tipo.
        max_404_attempts : int
            Numero di tentativi totali a cui un 404 ripetuto rende il dettaglio
            UNAVAILABLE; maggiore di zero. Default: da RIOT_MAX_404_ATTEMPTS.

        Returns
        -------
        None
            Nessuna restituzione di valore.
        """

        # Setto datetime per il fetched_at, comprimo il json in un blob e definisco le righe da inserire
        now_dt = datetime.now(timezone.utc)

        if https_status == 200 and match_detail:
            detail_bytea = gzip.compress(json.dumps(match_detail).encode("utf-8"))
            fetched_at = now_dt
            next_retry_at = None

            info = match_detail["info"]
            game_version = info["gameVersion"]
            queue_id = info["queueId"]
            game_duration_s = info["gameDuration"]
            end_of_game_result = info.get("endOfGameResult")   # può mancare nelle partite vecchie

        else:
            next_retry_at = (now_dt + timedelta(minutes=10))
            game_version = None
            queue_id = None
            game_duration_s = None
            end_of_game_result = None
            detail_bytea = None
            fetched_at = None

        last_attempt_at = now_dt

        row = {
            "match_id": match_id,
            "status": status,
            "fetched_at": fetched_at,
            "https_status": https_status,
            "detail_bytea": detail_bytea,
            "game_version": game_version,
            "queue_id": queue_id,
            "game_duration_s": game_duration_s,
            "end_of_game_result": end_of_game_result,
            "last_attempt_at": last_attempt_at,
            "next_retry_at": next_retry_at,
            "run_id": run_id,
            "batch_id": batch_id,
            "max_404_attempts": max_404_attempts
        }

        # Definisco l'insert
        query = text("""
            INSERT INTO core.match_detail (
                match_id, status, fetched_at, https_status, detail_bytea,
                game_version, queue_id, game_duration_s, end_of_game_result,
                attempt_count, last_attempt_at, next_retry_at, run_id, batch_id
            )
            VALUES (
                :match_id, :status, :fetched_at, :https_status, :detail_bytea,
                :game_version, :queue_id, :game_duration_s, :end_of_game_result, 
                1, :last_attempt_at, :next_retry_at, :run_id, :batch_id)
            ON CONFLICT (match_id) DO UPDATE SET
                status = CASE 
                    WHEN EXCLUDED.https_status = 404 
                    AND match_detail.https_status = 404
                    AND match_detail.attempt_count+1 >= :max_404_attempts
                    THEN 'UNAVAILABLE' 
                    ELSE EXCLUDED.status END,
                fetched_at = EXCLUDED.fetched_at,
                https_status = EXCLUDED.https_status,
                detail_bytea = EXCLUDED.detail_bytea,
                game_version = EXCLUDED.game_version,
                queue_id = EXCLUDED.queue_id,
                game_duration_s = EXCLUDED.game_duration_s,
                end_of_game_result = EXCLUDED.end_of_game_result,
                attempt_count = match_detail.attempt_count + 1,
                last_attempt_at = EXCLUDED.last_attempt_at,
                next_retry_at = CASE
                    WHEN EXCLUDED.https_status = 404 
                    AND match_detail.https_status = 404
                    AND match_detail.attempt_count+1 >= :max_404_attempts
                    THEN NULL 
                    ELSE EXCLUDED.next_retry_at END,
                run_id = EXCLUDED.run_id,
                batch_id = EXCLUDED.batch_id
            WHERE match_detail.status != 'FETCHED'
        """)

        # Eseguo
        self._connection.execute(query, row)