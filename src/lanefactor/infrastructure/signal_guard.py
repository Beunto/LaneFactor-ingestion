from collections.abc import Iterator
from contextlib import contextmanager
from os import kill, getpid
from types import FrameType
import signal

@contextmanager
def block_sigint() -> Iterator[None]:
    """Blocca SIGINT (di solito generato da Ctrl+C) per la durata del blocco.

    Serve a proteggere le sezioni critiche, come un commit sul database: il
    segnale resta in sospeso e viene consegnato all'uscita dal blocco, quando
    la maschera originale viene ripristinata.

    Yields
    ------
    None
        Nessun valore; si usa come `with block_sigint(): ...`.
    """

    old_mask = signal.pthread_sigmask(signal.SIG_BLOCK, {signal.SIGINT})
    try:
        yield
    finally:
        signal.pthread_sigmask(signal.SIG_SETMASK, old_mask)


def _forward_sigterm_as_sigint(signum: int, frame: FrameType | None) -> None:
    """Rimanda SIGTERM come SIGINT allo stesso processo.

    Registrato come handler di SIGTERM, fa sì che `docker stop` inneschi la
    stessa chiusura ordinata di un Ctrl+C.

    Parameters
    ----------
    signum : int
        Numero del segnale ricevuto, imposto dalla firma degli handler e non usato.
    frame : FrameType | None
        Frame in esecuzione al momento del segnale, imposto dalla firma degli handler e non usato.

    Returns
    -------
    None
        Nessuna restituzione di valore.
    """

    kill(getpid(), signal.SIGINT)
