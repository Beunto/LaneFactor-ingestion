from lanefactor.infrastructure.repositories.metrics.run_metrics_repository import RunMetricsRepository
from lanefactor.services.ingestion.detail_ingestion_service import DetailIngestionService
from lanefactor.services.ingestion.batch_service import BatchService
from lanefactor.infrastructure.logging_context import run_id_var, batch_id_var
from lanefactor.infrastructure.signal_guard import block_sigint
from lanefactor.infrastructure.riot_client import RiotClient
from lanefactor.infrastructure.db_session import DbSession
from lanefactor.utils.telemetry import TelemetryTracker
from tqdm import tqdm
import logging
import time
import sys

logger = logging.getLogger(__name__)

def ingest_details(match_ids:list[str], max_batch_size:int=20, client:RiotClient|None=None, parent_run_id:str|None=None) -> str:
    """Scarica e salva il dettaglio dei match indicati, registrando le metriche.

    Passa gli ID al servizio senza selezionare altri match dal database.
    Elabora un batch per transazione e registra le metriche in una sola run.
    Attende cinque secondi tra batch, ma non dopo l'ultimo o in caso di stop.
    I fallimenti di download gestiti dal servizio vengono registrati per
    singolo match e non interrompono l'elaborazione degli ID successivi.
    Gli altri errori vengono propagati al chiamante. La run è segnata STOPPED
    se il servizio richiede lo stop, altrimenti DONE al termine del lavoro,
    anche in presenza di singoli download falliti.

    Se viene passato un client, lo usa invece di crearne uno; il chiamante
    resta proprietario del client. Le metriche del client vengono azzerate
    prima di ogni batch: il chiamante deve registrare le proprie prima di
    chiamare la funzione, altrimenti le perde.

    Solleva ValueError per max_batch_size non positivo; propaga gli errori non gestiti e le interruzioni non assorbite dal servizio.

    Parameters
    ----------
    match_ids : list[str]
        ID dei match da considerare; una lista vuota è ammessa.
    max_batch_size : int
        Numero massimo di match per batch, maggiore di zero. Default: 20.
    client : RiotClient | None
        Client Riot da riutilizzare, ad esempio quello di un job che ha già
        fatto richieste, così pacing e metriche restano condivisi. Con None
        ne viene creato uno nuovo. Default: None.
    parent_run_id : str | None
        UUID della run del job chiamante, registrato come parent_run_id della
        run di dettaglio; None se la run è una radice. Default: None.

    Returns
    -------
    str
        Stato finale della run: "DONE" se il lavoro è terminato, "STOPPED" se
        lo stop è stato richiesto. Il chiamante lo usa per fermare il proprio
        ciclo, perché uno stop gestito dal servizio non solleva eccezioni.
    """

    if max_batch_size <= 0:
        raise ValueError("max_batch_size deve essere > 0")

    # faccio partire la run
    with DbSession() as conn:
        reporting_run = RunMetricsRepository(conn)
        run_id, run_started_dt = reporting_run.start_run(
            parent_run_id=parent_run_id,
            pipeline="ingest_details",
            params={
                "match_ids": match_ids,
                "count": len(match_ids),
                "max_batch_size": max_batch_size,
                "pause_seconds": 5,
            }
        )

    # inizializzo i contatori
    batch_index = 0
    end_status = "RUNNING"

    run_tracker = TelemetryTracker("ingestion_run")
    run_token = run_id_var.set(run_id)
    batch_scope_token = batch_id_var.set(None)

    try:
        # apro la connessione al client e la passo al service
        if client is None:
            client = RiotClient()

        service = DetailIngestionService(client)
        batch_service = BatchService(service)

        # Implemento la logica per batch
        current_matches: list[str] = []
        for offset in tqdm(range(0, len(match_ids), max_batch_size), desc="Batch ingestion", unit="batch"):
            if service.stop_requested:
                break

            client.reset_metrics()
            current_matches = match_ids[offset:offset+max_batch_size]

            batch_action, batch_end_status = batch_service.run_batch(
                current_matches,
                run_id,
                run_tracker,
                batch_index,
                client
            )

            if batch_action == "finish":
                batch_index += 1

            if batch_end_status == "STOPPED":
                end_status = "STOPPED"
                break

            if offset + max_batch_size < len(match_ids):
                time.sleep(5)

        # Al termine del ciclo gestisco lo stato della run
        if end_status not in ("STOPPED", "FAILED"):
            end_status = "STOPPED" if service.stop_requested else "DONE"

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
            batch_id_var.reset(batch_scope_token)

    return end_status
