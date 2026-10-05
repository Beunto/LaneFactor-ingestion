from lanefactor.infrastructure.repositories.metrics.run_metrics_repository import RunMetricsRepository
from lanefactor.services.ingestion.seed_extraction_service import SeedExtractionService
from lanefactor.infrastructure.signal_guard import _forward_sigterm_as_sigint
from lanefactor.infrastructure.logging_context import configure_logging
from lanefactor.infrastructure.logging_context import run_id_var
from lanefactor.infrastructure.signal_guard import block_sigint
from lanefactor.infrastructure.db_session import DbSession
from lanefactor.utils.telemetry import TelemetryTracker
from tqdm import tqdm
import logging
import signal
import click
import sys

logger = logging.getLogger(__name__)

@click.command()
@click.option(
    "--batch-size", 
    "batch_size", 
    help="Numero di timeline da elaborare per blocco",
    type=click.IntRange(min=1), 
    default=500
)
def update_seed(batch_size: int) -> int:
    """Alimenta core.puuid_seed dai PUUID delle timeline già scaricate.

    Elabora a blocchi le timeline con seed non ancora estratti, senza chiamare
    Riot, e termina quando non ne restano da leggere. Registra stato e metriche
    della run: total_ok conta le timeline elaborate, total_batches i blocchi.
    Un’interruzione chiude la run come STOPPED, gli altri errori come FAILED e
    vengono propagati. I blocchi già completati restano salvati. Elaborazione
    e aggiornamento delle metriche di ogni blocco sono protetti da
    block_sigint(): un’interruzione attende la fine del blocco in corso, così
    total_ok e total_batches coincidono con le timeline marcate.

    Parameters
    ----------
    batch_size : int
        Numero massimo di timeline da elaborare per blocco.

    Returns
    -------
    int
        Numero totale di timeline elaborate nella run.
    """

    # faccio partire la run
    with DbSession() as conn:
        reporting_run = RunMetricsRepository(conn)
        run_id, run_started_dt = reporting_run.start_run(
            pipeline="update_seed",
            params={"batch_size": batch_size}
        )

    end_status = "RUNNING"
    run_tracker = TelemetryTracker("ingestion_run")
    run_token = run_id_var.set(run_id)

    try:

        # inizializzo il service
        service = SeedExtractionService()
        total_batches = service.count_pending_batches(batch_size)

        timeline_parsed:int = 0
        with tqdm(total=total_batches, desc="Batch processati", unit="batch") as pbar:
            while True:

                with block_sigint():
                    # Faccio partire la run
                    read_timelines = service.run(batch_size)

                    if read_timelines == 0:
                        break

                    # Aumento il contatore di timeline lette ed aggiorno le metriche
                    timeline_parsed += read_timelines
                    run_tracker.record_metrics({"total_ok": read_timelines, "total_batches": 1})
                    pbar.update(1)

            end_status = "DONE"

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
                reporting_run.finish_run(run_id, run_started_dt, end_status, run_tracker.report)

        except Exception:
            if not has_active_exception:
                raise

            logger.exception(
                "Errore nella chiusura delle metriche della run %s",
                run_id
            )

        finally:
            run_id_var.reset(run_token)

    return timeline_parsed


if __name__ == '__main__':
    signal.signal(signal.SIGTERM, _forward_sigterm_as_sigint)
    configure_logging()
    update_seed()