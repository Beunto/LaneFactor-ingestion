import logging
from contextvars import ContextVar

run_id_var = ContextVar("run_id", default=None)
batch_id_var = ContextVar("batch_id", default=None)


def configure_logging() -> None:
    """Configura il logging di base delle CLI a livello INFO.

    Include data, livello, nome del logger e messaggio. Se il logger root
    dispone già di handler, basicConfig mantiene la configurazione esistente.

    Parameters
    ----------
    None
        Nessun parametro esplicito.

    Returns
    -------
    None
        Nessuna restituzione di valore.
    """

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )
