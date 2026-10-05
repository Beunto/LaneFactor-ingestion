from sqlalchemy import text
from sqlalchemy import bindparam
from sqlalchemy.engine import Connection
from datetime import datetime, timezone

class MatchRepository:

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


    def fetch_detail_sync_ids(self, limit:int) -> list[str]:
        """Seleziona i match con il solo dettaglio pendente, per match_detail_sync.

        Perimetro: timeline già scaricata (timeline_fetched TRUE) e dettaglio da
        scaricare ora (detail_fetched FALSE, riga assente o non FETCHED e non
        UNAVAILABLE, retry assente o scaduto). Insieme a sync_timelines e
        sync_match forma una partizione: un match non compare in più di un job.
        Un match con la timeline persa (UNAVAILABLE) non viene selezionato.
        Ordina per seen_at decrescente e poi per ID; non attende retry futuri.

        Parameters
        ----------
        limit : int
            Numero massimo di match da selezionare, maggiore di zero.

        Returns
        -------
        list[str]
            Al massimo limit ID; lista vuota se non ci sono match elaborabili.
        """

        now = datetime.now(timezone.utc)
        query = text("""
            SELECT m.match_id
            FROM core.match m
            LEFT JOIN core.match_detail mt
            ON m.match_id = mt.match_id
            WHERE m.detail_fetched IS FALSE AND m.timeline_fetched IS TRUE
                AND (mt.match_id IS NULL OR mt.status NOT IN ('FETCHED','UNAVAILABLE'))
                AND (mt.next_retry_at IS NULL OR mt.next_retry_at <= :now)
            ORDER BY m.seen_at DESC, m.match_id
            LIMIT :limit
        """)

        result = self._connection.execute(query, {"now": now, "limit":limit})

        return [row[0] for row in result.fetchall()]


    def fetch_timeline_sync_ids(self, limit:int) -> list[str]:
        """Seleziona i match con la sola timeline pendente, per match_timeline_sync.

        Perimetro: dettaglio già scaricato (detail_fetched TRUE) e timeline da
        scaricare ora (timeline_fetched FALSE, riga assente o non FETCHED e non
        UNAVAILABLE, retry assente o scaduto). Non include i match senza alcun
        payload, che appartengono a sync_match, né quelli con il dettaglio perso
        (UNAVAILABLE). Ordina per seen_at decrescente e poi per ID; non attende
        retry futuri.

        Parameters
        ----------
        limit : int
            Numero massimo di match da selezionare, maggiore di zero.

        Returns
        -------
        list[str]
            Al massimo limit ID; lista vuota se non ci sono match elaborabili.
        """

        now = datetime.now(timezone.utc)
        query = text("""
            SELECT m.match_id
            FROM core.match m
            LEFT JOIN core.match_timeline mt
            ON m.match_id = mt.match_id
            WHERE m.timeline_fetched IS FALSE AND m.detail_fetched IS TRUE
                AND (mt.match_id IS NULL OR mt.status NOT IN ('FETCHED','UNAVAILABLE'))
                AND (mt.next_retry_at IS NULL OR mt.next_retry_at <= :now)
            ORDER BY m.seen_at DESC, m.match_id
            LIMIT :limit
        """)

        result = self._connection.execute(query, {"now": now, "limit":limit})

        return [row[0] for row in result.fetchall()]


    def fetch_match_sync_ids(self, limit:int) -> list[str]:
        """Seleziona i match senza alcun payload, per match_sync.

        Perimetro: timeline e dettaglio entrambi da scaricare ora (flag FALSE,
        riga assente o non FETCHED e non UNAVAILABLE, retry assente o scaduto
        per ciascuno dei due). Un match con un payload in cooldown o perso
        (UNAVAILABLE) non viene selezionato, per non ignorare il retry di
        ingest_timelines e ingest_details, che non filtrano gli ID ricevuti.
        Ordina per seen_at decrescente e poi per ID; non attende retry futuri.

        Parameters
        ----------
        limit : int
            Numero massimo di match da selezionare, maggiore di zero.

        Returns
        -------
        list[str]
            Al massimo limit ID; lista vuota se non ci sono match elaborabili.
        """

        now = datetime.now(timezone.utc)
        query = text("""
            SELECT m.match_id
            FROM core.match m
            LEFT JOIN core.match_timeline mt ON mt.match_id = m.match_id
            LEFT JOIN core.match_detail  md ON md.match_id = m.match_id
            WHERE m.timeline_fetched IS FALSE
                AND (mt.match_id IS NULL OR mt.status NOT IN ('FETCHED','UNAVAILABLE'))
                AND (mt.next_retry_at IS NULL OR mt.next_retry_at <= :now)
                AND m.detail_fetched IS FALSE
                AND (md.match_id IS NULL OR md.status NOT IN ('FETCHED','UNAVAILABLE'))
                AND (md.next_retry_at IS NULL OR md.next_retry_at <= :now)
            ORDER BY m.seen_at DESC, m.match_id
            LIMIT :limit
        """)

        result = self._connection.execute(query, {"now": now, "limit":limit})

        return [row[0] for row in result.fetchall()]
    

    def timelines_to_fetch(self, match_ids:list[str]) -> list[str]:
        """Seleziona i match candidati con timeline elaborabile.

        Richiede il flag globale FALSE, esclude gli stati FETCHED e UNAVAILABLE e
        ammette retry assenti o scaduti. L’ordine del risultato non è garantito dalla query.

        Parameters
        ----------
        match_ids : list[str]
            ID dei match da considerare; una lista vuota è ammessa.

        Returns
        -------
        list[str]
            ID elaborabili tra i candidati, senza ordine garantito.
        """

        if not match_ids:
            return []

        now = datetime.now(timezone.utc)
        query = text("""
            SELECT m.match_id
            FROM core.match m
            LEFT JOIN core.match_timeline mt
                ON mt.match_id = m.match_id
            WHERE m.match_id IN :match_ids
            AND m.timeline_fetched IS FALSE
            AND (mt.match_id IS NULL OR mt.status NOT IN ('FETCHED', 'UNAVAILABLE'))    
            AND (mt.next_retry_at IS NULL OR mt.next_retry_at <= :now)
        """).bindparams(bindparam("match_ids", expanding=True))

        result = self._connection.execute(query, {"match_ids": match_ids, "now": now})

        return [row[0] for row in result.fetchall()]


    def detail_to_fetch(self, match_ids:list[str]) -> list[str]:
        """Seleziona i match candidati con dettaglio elaborabile.

        Richiede il flag globale detail_fetched FALSE, esclude gli stati FETCHED e
        UNAVAILABLE e ammette retry assenti o scaduti. L’ordine del risultato non è garantito dalla query.

        Parameters
        ----------
        match_ids : list[str]
            ID dei match da considerare; una lista vuota è ammessa.

        Returns
        -------
        list[str]
            ID elaborabili tra i candidati, senza ordine garantito.
        """

        if not match_ids:
            return []

        now = datetime.now(timezone.utc)
        query = text("""
            SELECT m.match_id
            FROM core.match m
            LEFT JOIN core.match_detail mt
                ON mt.match_id = m.match_id
            WHERE m.match_id IN :match_ids
            AND m.detail_fetched IS FALSE
            AND (mt.match_id IS NULL OR mt.status NOT IN ('FETCHED', 'UNAVAILABLE'))  
            AND (mt.next_retry_at IS NULL OR mt.next_retry_at <= :now)
        """).bindparams(bindparam("match_ids", expanding=True))

        result = self._connection.execute(query, {"match_ids": match_ids, "now": now})

        return [row[0] for row in result.fetchall()]


    def mark_seen(self, match_ids:list[str]) -> None:
        """Inserisce i match globali assenti, conservando flag e seen_at esistenti.

        Un input vuoto non esegue query; il commit resta al chiamante.

        Parameters
        ----------
        match_ids : list[str]
            ID dei match da considerare; una lista vuota è ammessa.

        Returns
        -------
        None
            Nessuna restituzione di valore.
        """

        if not match_ids:
            return

        # Setto datetime per il seen_at e le righe da inserire
        seen_at = datetime.now(timezone.utc)

        rows = [
            {"match_id": match_id, "seen_at": seen_at}
            for match_id in match_ids
        ]

        # Definisco l'insert
        query = text("""
            INSERT INTO core.match (match_id, seen_at)
            VALUES (:match_id, :seen_at)
            ON CONFLICT (match_id) DO NOTHING
        """)

        # Eseguo la transaction
        self._connection.execute(query, rows)


    def mark_timeline_fetched(self, match_ids:list[str]) -> None:
        """Segna come scaricate le timeline di tutti i match indicati.

        Parameters
        ----------
        match_ids : list[str]
            ID dei match da considerare; una lista vuota è ammessa.

        Returns
        -------
        None
            Nessuna restituzione di valore.
        """

        if not match_ids:
            return

        query_update = text("""
            UPDATE core.match
            SET timeline_fetched = TRUE
            WHERE match_id = :match_id
        """)

        matches = [{"match_id": match_id} for match_id in match_ids]
        self._connection.execute(query_update, matches)


    def mark_detail_fetched(self, match_ids:list[str]) -> None:
        """Segna come scaricati i dettagli di tutti i match indicati.

        Parameters
        ----------
        match_ids : list[str]
            ID dei match da considerare; una lista vuota è ammessa.

        Returns
        -------
        None
            Nessuna restituzione di valore.
        """

        if not match_ids:
            return

        query_update = text("""
            UPDATE core.match
            SET detail_fetched = TRUE
            WHERE match_id = :match_id
        """)

        matches = [{"match_id": match_id} for match_id in match_ids]
        self._connection.execute(query_update, matches)