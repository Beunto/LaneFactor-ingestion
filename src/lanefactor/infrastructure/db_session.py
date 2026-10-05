from sqlalchemy.engine import Connection
from types import TracebackType
from lanefactor.infrastructure.database import engine

class DbSession:

    def __init__(self) -> None:
        """Inizializza l’istanza e le dipendenze utilizzate dai metodi.

        Parameters
        ----------
        None
            Nessun parametro esplicito.

        Returns
        -------
        None
            Nessuna restituzione di valore.
        """

        self.engine = engine

    def __enter__(self) -> Connection:
        """Apre e restituisce una connessione dall’engine configurato.

        Parameters
        ----------
        None
            Nessun parametro esplicito.

        Returns
        -------
        Connection
            Connessione aperta da usare nel contesto.
        """

        self.conn = self.engine.connect()
        return self.conn

    def __exit__(self, exc_type: type[BaseException] | None, exc: BaseException | None, tb: TracebackType | None) -> bool:
        """Conferma la transazione senza errori, altrimenti esegue rollback.

        Chiude sempre la connessione e non sopprime l’eccezione del contesto.

        Parameters
        ----------
        exc_type : type[BaseException] | None
            Tipo dell’eccezione in uscita dal contesto, oppure None.
        exc : BaseException | None
            Eccezione in uscita dal contesto, oppure None.
        tb : TracebackType | None
            Traceback dell’eccezione, oppure None.

        Returns
        -------
        bool
            False: le eccezioni del contesto non vengono soppresse.
        """

        try:
            if exc_type is None:
                self.conn.commit()
            else:
                self.conn.rollback()
        finally:
            self.conn.close()
        return False