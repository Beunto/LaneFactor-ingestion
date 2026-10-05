from sqlalchemy import text
from sqlalchemy import bindparam
from sqlalchemy.engine import Connection
from datetime import datetime, timezone

class PuuidMatchRepository:

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

    def filter_unseen_match(self, puuid:str, match_ids:list[str]) -> list[str]:
        """Seleziona gli ID non ancora associati al giocatore.

        Mantiene l’ordine e le eventuali ripetizioni dell’input; non verifica le timeline.

        Parameters
        ----------
        puuid : str
            Identificatore testuale del giocatore.
        match_ids : list[str]
            ID dei match da considerare; una lista vuota è ammessa.

        Returns
        -------
        list[str]
            ID non ancora associati al giocatore, nell’ordine dell’input.
        """

        if not match_ids:
            return []

        query = text("""
            SELECT match_id
            FROM core.puuid_match
            WHERE puuid = :puuid
            AND match_id in :match_ids
        """).bindparams(bindparam("match_ids", expanding=True))

        result = self._connection.execute(
            query,
            {"match_ids": match_ids, "puuid": puuid}
        )

        existing = [row[0] for row in result.fetchall()]
        return [ids for ids in match_ids if ids not in existing]

    def mark_seen(self, puuid:str, match_ids:list[str]) -> None:
        """Inserisce le nuove associazioni senza aggiornare quelle esistenti.

        I match globali devono già esistere per rispettare la foreign key.
        Un input vuoto non esegue query; il commit resta al chiamante.

        Parameters
        ----------
        puuid : str
            Identificatore testuale del giocatore.
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
            {"puuid": puuid, "match_id": match_id, "seen_at": seen_at}
            for match_id in match_ids
        ]

        # Definisco l'insert
        query = text("""
            INSERT INTO core.puuid_match (puuid, match_id, seen_at)
            VALUES (:puuid, :match_id, :seen_at)
            ON CONFLICT (puuid, match_id) DO NOTHING
        """)

        # Eseguo la transaction
        self._connection.execute(query, rows)
