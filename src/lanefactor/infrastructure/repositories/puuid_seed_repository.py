from sqlalchemy import text
from sqlalchemy.engine import Connection
from datetime import datetime, timezone

class PuuidSeedRepository:

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

    def insert_seeds(self, puuids: list[str]) -> None:
        """Inserisce i PUUID nuovi come seed senza modificare quelli esistenti.

        Per un PUUID già presente in core.puuid_match, last_ingested_at riceve
        la data più recente di associazione; altrimenti resta NULL. I seed già
        presenti restano invariati, così la rotazione non viene azzerata. Un
        input vuoto non esegue query; il commit resta al chiamante.

        Parameters
        ----------
        puuids : list[str]
            PUUID da inserire; una lista vuota è ammessa e i duplicati sono ignorati.

        Returns
        -------
        None
            Nessuna restituzione di valore.
        """

        if not puuids:
            return 

        query = text("""   
            INSERT INTO core.puuid_seed (puuid, last_ingested_at) 
            VALUES (:puuid, (SELECT MAX(seen_at) FROM core.puuid_match where puuid = :puuid))
            ON CONFLICT DO NOTHING
        """)

        self._connection.execute(query,[{"puuid": puuid} for puuid in puuids])


    def select_seeds_to_ingest(self, limit: int) -> list[str]:
        """Seleziona i seed a cui chiedere i match, in ordine di rotazione.

        Restituisce prima i seed mai ingeriti (last_ingested_at NULL), poi i meno
        recenti; a parità di last_ingested_at vale l’ordine di scoperta. Nessun
        seed è escluso: la selezione non marca né blocca le righe, quindi
        last_ingested_at va aggiornato con mark_ingested a ingestion riuscita.

        Parameters
        ----------
        limit : int
            Numero massimo di PUUID da restituire, previsto positivo.

        Returns
        -------
        list[str]
            PUUID selezionati; una lista vuota se core.puuid_seed è vuota.
        """

        query = text("""
            SELECT puuid
            FROM core.puuid_seed
            ORDER BY last_ingested_at NULLS FIRST, discovered_at
            LIMIT :limit
        """)

        result = self._connection.execute(query, {"limit":limit})
        return result.scalars().all()


    def mark_ingested(self, puuids: list[str]) -> None:
        """Imposta last_ingested_at all’istante corrente per i seed indicati.

        Da chiamare dopo un’ingestion riuscita dei match del seed. Un PUUID non
        presente in core.puuid_seed non produce effetti. Con una lista vuota
        non viene eseguita alcuna modifica; il commit resta al chiamante.

        Parameters
        ----------
        puuids : list[str]
            PUUID dei seed da segnare come ingeriti; una lista vuota è ammessa.

        Returns
        -------
        None
            Nessuna restituzione di valore.
        """

        if not puuids:
            return

        now = datetime.now(timezone.utc)

        query = text("""
            UPDATE core.puuid_seed SET last_ingested_at = :now WHERE puuid = :puuid
        """)

        self._connection.execute(query, [{"now": now, "puuid": puuid} for puuid in puuids])