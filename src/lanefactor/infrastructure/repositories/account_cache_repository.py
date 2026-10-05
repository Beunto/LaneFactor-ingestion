from sqlalchemy.engine import Connection
from sqlalchemy import text

class AccountCacheRepository:

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

    def upsert_account(self, gameName:str, tagLine:str, puuid:str) -> None:
        """Inserisci un account nella cache o aggiorna nome e tag del PUUID esistente.

        Parameters
        ----------
        gameName : str
            Nome del giocatore nel Riot ID.
        tagLine : str
            Tag del Riot ID, senza il separatore '#'.
        puuid : str
            Identificatore testuale del giocatore.

        Returns
        -------
        None
            Nessuna restituzione di valore.
        """

        # Definisco l'insert
        query = text("""
            INSERT INTO core.riot_id_cache (game_name, tag_line, puuid)
            VALUES (:game_name, :tag_line, :puuid)
            ON CONFLICT (puuid) DO UPDATE SET
                game_name = EXCLUDED.game_name,
                tag_line = EXCLUDED.tag_line
        """)

        # Eseguo l'inserimento
        self._connection.execute(query, {"game_name": gameName, "tag_line": tagLine, "puuid": puuid})

    def get_puuid(self, gameName: str, tagLine: str) -> str | None:
        """Restituisci il PUUID associato a nome e tag, oppure None.

        Parameters
        ----------
        gameName : str
            Nome del giocatore nel Riot ID.
        tagLine : str
            Tag del Riot ID, senza il separatore '#'.

        Returns
        -------
        str | None
            PUUID memorizzato oppure None se la coppia nome/tag non è presente.
        """

        # Definisco la select
        query = text("""
            SELECT puuid
            FROM core.riot_id_cache
            WHERE game_name = :game_name AND tag_line = :tag_line
        """)

        # Eseguo la transaction
        result = self._connection.execute(query, {"game_name": gameName, "tag_line": tagLine})

        row = result.fetchone()
        return row[0] if row else None