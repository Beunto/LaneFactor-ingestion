from lanefactor.infrastructure.repositories.metrics.run_metrics_repository import RunMetricsRepository
from lanefactor.infrastructure.repositories.puuid_seed_repository import PuuidSeedRepository
from lanefactor.infrastructure.signal_guard import _forward_sigterm_as_sigint
from lanefactor.infrastructure.signal_guard import block_sigint
from lanefactor.infrastructure.logging_context import configure_logging
from lanefactor.infrastructure.logging_context import run_id_var
from lanefactor.infrastructure.riot_client import RiotClient
from lanefactor.infrastructure.db_session import DbSession
from .ingest_timelines import ingest_timelines
from lanefactor.exceptions import InputError
from .ingest_details import ingest_details
from .ingest_matches import ingest_matches
import logging
import signal
import click
import sys

logger = logging.getLogger(__name__)

@click.command()
@click.option("--limit", help="Numero massimo di seed da elaborare", type=click.IntRange(min=1), default=100, show_default=True)
@click.option("--matches-per-seed", "matches_per_seed", help="Numero massimo di match da richiedere a Riot per ogni seed", type=click.IntRange(min=1), default=100, show_default=True)
def snowball(limit: int, matches_per_seed: int) -> None:
    """Recupera i match dei seed in core.puuid_seed, con timeline e dettaglio.

    Apre una run radice "snowball", senza metriche proprie perché non fa
    richieste HTTP, e la chiude sempre nel blocco finally. Seleziona fino a
    limit seed in ordine di rotazione (prima i mai ingeriti, poi i meno
    recenti) e per ciascuno esegue in sequenza ingest_matches in modalità
    PUUID, ingest_timelines e ingest_details. Le tre fasi condividono lo
    stesso client Riot e registrano ciascuna una run figlia, con
    parent_run_id uguale a quello della radice; una fase senza ID da
    scaricare non parte.

    Un seed viene segnato come ingerito (last_ingested_at) solo quando le
    run di timeline e dettaglio terminano senza stop. I singoli download
    falliti non lo impediscono: li registra il servizio e li recupera
    i job di sync. Un seed senza match ranked viene segnato
    comunque. Un InputError su un seed lo fa saltare, con un log di errore e
    senza segnarlo; le altre eccezioni interrompono il comando e chiudono la
    radice come FAILED.

    Se una run figlia termina STOPPED, il ciclo si ferma subito (le timeline
    STOPPED impediscono l'avvio del dettaglio) e il seed in corso non viene
    segnato: resta tra i mai ingeriti e viene ripreso quando la rotazione lo
    raggiunge. La radice si chiude STOPPED, come per un'interruzione propagata.

    Parameters
    ----------
    limit : int
        Numero massimo di seed da elaborare, maggiore di zero. Default: 100.
    matches_per_seed : int
        Numero massimo di ID richiesti a Riot per ogni seed, maggiore di
        zero. Default: 100.

    Returns
    -------
    None
        Nessuna restituzione di valore.
    """

    client = RiotClient()
    with DbSession() as conn:
        run_reporting = RunMetricsRepository(conn)
        run_id, run_started_dt = run_reporting.start_run(
            pipeline="snowball",
            params={
                "limit": limit,
                "matches_per_seed": matches_per_seed
            }
        )

    # inizializzo i contatori
    end_status = "RUNNING"
    run_token = run_id_var.set(run_id)

    try: 
        # Recupero i seed su cui effettuare ingestion
        with DbSession() as conn:
            p_repo = PuuidSeedRepository(conn)
            puuids = p_repo.select_seeds_to_ingest(limit)

        for puuid in puuids: 

            tl_status = dt_status = "DONE"
            
            try:
                # Inserisco i match relativi a questo seed
                timelines_to_fetch, detail_to_fetch = ingest_matches(
                    puuid=puuid,
                    count=matches_per_seed,
                    client=client,
                    parent_run_id=run_id,
                )
            except InputError:
                logger.error(
                    "Errore nell'inserimento del seed %s",
                    puuid
                )

                continue

            # Recupero e faccio ingest sulle timeline
            if timelines_to_fetch:
                tl_status = ingest_timelines(
                    timelines_to_fetch,
                    client=client,
                    parent_run_id=run_id
                )

            # Controllo l'uscita da ingest_timelines
            if tl_status == "STOPPED":
                end_status = "STOPPED"
                break

            # Recupero e faccio ingest sui detail
            if detail_to_fetch:
                dt_status = ingest_details(
                    detail_to_fetch,
                    client=client,
                    parent_run_id=run_id
                )

            # Controllo l'uscita da ingest_details
            if dt_status == "STOPPED":
                end_status = "STOPPED"
                break

            # Segno il seed come ingerito, al riparo da un'interruzione
            with block_sigint(), DbSession() as conn:
                p_repo = PuuidSeedRepository(conn)
                p_repo.mark_ingested([puuid])

        # Il ciclo è arrivato in fondo senza stop: la run è completata
        else:
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
    snowball()
