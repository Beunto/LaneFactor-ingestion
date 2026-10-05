from lanefactor.infrastructure.repositories.metrics.run_metrics_repository import RunMetricsRepository
from lanefactor.infrastructure.repositories.match_repository import MatchRepository
from lanefactor.infrastructure.signal_guard import _forward_sigterm_as_sigint
from lanefactor.infrastructure.signal_guard import block_sigint
from lanefactor.infrastructure.logging_context import configure_logging
from lanefactor.infrastructure.logging_context import run_id_var
from lanefactor.infrastructure.riot_client import RiotClient
from lanefactor.infrastructure.db_session import DbSession
from .ingest_timelines import ingest_timelines
import logging
import signal
import click
import sys

logger = logging.getLogger(__name__)

@click.command()
@click.option("--limit", help="Numero di match selezionati a ogni giro", type=click.IntRange(min=1), default=100, show_default=True)
def match_timeline_sync(limit: int) -> None:
    """Recupera le timeline dei match che hanno già il dettaglio.

    Apre una run radice "match_timeline_sync", senza metriche proprie perché
    non fa richieste HTTP, e la chiude sempre nel blocco finally. A ogni giro
    seleziona fino a limit match con il dettaglio già scaricato e la timeline da
    scaricare ora (fetch_timeline_sync_ids) e li passa a ingest_timelines, come
    run figlia con lo stesso client Riot. Termina quando la selezione è vuota,
    senza attendere i retry futuri.

    I match senza nessun payload appartengono a match_sync. Se la run figlia è
    STOPPED il ciclo si ferma e la radice chiude STOPPED; le eccezioni
    propagate la chiudono come FAILED.

    Parameters
    ----------
    limit : int
        Numero di match selezionati a ogni giro, maggiore di zero. Le funzioni
        ingest_* li scaricano poi a batch. Default: 100.

    Returns
    -------
    None
        Nessuna restituzione di valore.
    """

    client = RiotClient()
    with DbSession() as conn:
        run_reporting = RunMetricsRepository(conn)
        run_id, run_started_dt = run_reporting.start_run(
            pipeline="match_timeline_sync",
            params={"limit": limit}
        )

    # inizializzo i contatori
    end_status = "RUNNING"
    run_token = run_id_var.set(run_id)

    try:
        # Cambia solo se una run figlia viene fermata
        end_status = "DONE"

        while True:
            # Seleziono il prossimo giro di match, senza tenere aperta la sessione durante le richieste
            with DbSession() as conn:
                match_ids = MatchRepository(conn).fetch_timeline_sync_ids(limit)

            # I match selezionati escono dalla selezione una volta scaricati,
            # in cooldown o UNAVAILABLE: senza match il lavoro è finito
            if not match_ids:
                break

            # Scarico le timeline dei match selezionati; se la run figlia è stata fermata mi fermo
            if ingest_timelines(match_ids, client=client, parent_run_id=run_id) == "STOPPED":
                end_status = "STOPPED"
                break

    # in caso di interruzione: STOPPED
    except KeyboardInterrupt:
        end_status = "STOPPED"
        raise

    # in tutti gli altri casi, compresi errore di rete: FAILED
    except Exception:
        end_status = "FAILED"
        raise

    finally:
        exc = sys.exc_info()[0]
        has_active_exception = exc is not None

        try:

            with block_sigint(), DbSession() as conn:
                reporting_run = RunMetricsRepository(conn)
                reporting_run.finish_run(run_id, run_started_dt, end_status, {})

        except Exception:
            if not has_active_exception:
                raise

            logger.exception(
                "Errore nella chiusura delle metriche della run %s",
                run_id
            )

        finally:
            run_id_var.reset(run_token)

if __name__ == '__main__':
    signal.signal(signal.SIGTERM, _forward_sigterm_as_sigint)
    configure_logging()
    match_timeline_sync()
