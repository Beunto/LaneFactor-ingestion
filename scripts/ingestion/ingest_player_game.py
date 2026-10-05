from lanefactor.infrastructure.repositories.metrics.run_metrics_repository import RunMetricsRepository
from lanefactor.infrastructure.signal_guard import _forward_sigterm_as_sigint
from lanefactor.infrastructure.signal_guard import block_sigint
from lanefactor.infrastructure.logging_context import configure_logging
from lanefactor.infrastructure.logging_context import run_id_var
from lanefactor.infrastructure.riot_client import RiotClient
from lanefactor.infrastructure.db_session import DbSession
from .ingest_timelines import ingest_timelines
from .ingest_details import ingest_details
from .ingest_matches import ingest_matches
import logging
import signal
import click
import sys

logger = logging.getLogger(__name__)

@click.command()
@click.option("--game-name", "gameName", help="Nome dell'evocatore", type=str, required=True)
@click.option("--tag-line", "tagLine", help="Tag dell'evocatore", type=str, required=True)
@click.option("--start", help="Offset iniziale nella lista dei match", type=click.IntRange(min=0), default=0, show_default=True)
@click.option("--count", help="Numero massimo di match da recuperare", type=click.IntRange(min=0), default=100, show_default=True)
def ingest_player_game(gameName:str, tagLine:str, start:int=0, count:int=100) -> None:
    """Recupera gli ID dei match ranked solo/duo del giocatore, con timeline e dettaglio.

    Apre una run radice "ingest_player_game", senza metriche proprie perché
    non fa richieste HTTP, e la chiude sempre nel blocco finally. Esegue prima
    l'ingestion degli ID e passa quelli restituiti ai runner di timeline e
    dettaglio, uno dopo l'altro; le fasi condividono lo stesso client Riot e
    registrano ciascuna una run figlia, con parent_run_id uguale a quello
    della radice, con stato e metriche proprie. Se per una fase non vengono
    restituiti ID, quella fase non parte e la radice si chiude comunque DONE.

    Le eccezioni propagate dai runner interrompono il comando e chiudono la
    radice come FAILED (comprese InputError e ValueError di ingest_matches);
    un'interruzione la chiude come STOPPED. Uno stop gestito dal servizio non
    solleva eccezioni: la run figlia risulta STOPPED e ne restituisce lo stato.
    Se le timeline sono STOPPED il dettaglio non parte, e la radice si chiude
    STOPPED se lo è almeno una delle due figlie.

    Parameters
    ----------
    gameName : str
        Nome del giocatore nel Riot ID.
    tagLine : str
        Tag del Riot ID, senza il separatore '#'.
    start : int
        Offset iniziale nella lista Riot, previsto non negativo. Default: 0.
    count : int
        Numero massimo di ID da richiedere o selezionare. Default: 100.

    Returns
    -------
    None
        Nessuna restituzione di valore.
    """

    client = RiotClient()
    with DbSession() as conn:
        run_reporting = RunMetricsRepository(conn)
        run_id, run_started_dt = run_reporting.start_run(
            pipeline="ingest_player_game",
            params={
                "game_name":gameName,
                "tag_line":tagLine, 
                "start":start, 
                "count":count
            }
        )

    # inizializzo i contatori
    tl_status = dt_status = "DONE"
    end_status = "RUNNING"
    run_token = run_id_var.set(run_id)

    try: 
        timelines_to_fetch, detail_to_fetch = ingest_matches(
            gameName,
            tagLine,
            start,
            count,
            client=client,
            parent_run_id=run_id,
        )

        if timelines_to_fetch:
            tl_status = ingest_timelines(
                timelines_to_fetch,
                client=client,
                parent_run_id=run_id
            )

        if tl_status != "STOPPED" and detail_to_fetch:
            dt_status = ingest_details(
                detail_to_fetch,
                client=client,
                parent_run_id=run_id
            )

        # Al termine delle fasi gestisco lo stato della run
        end_status = "STOPPED" if "STOPPED" in (tl_status, dt_status) else "DONE"

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
    ingest_player_game()
