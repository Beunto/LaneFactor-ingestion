from lanefactor.infrastructure.repositories.metrics.run_metrics_repository import RunMetricsRepository
from lanefactor.services.ingestion.match_ingestion_service import MatchIngestionService
from lanefactor.infrastructure.logging_context import run_id_var
from lanefactor.infrastructure.signal_guard import block_sigint
from lanefactor.infrastructure.riot_client import RiotClient
from lanefactor.infrastructure.db_session import DbSession
from lanefactor.utils.telemetry import TelemetryTracker
import logging
import sys

logger = logging.getLogger(__name__)

def ingest_matches(
        gameName:str|None=None, tagLine:str|None=None,
        start: int=0, count: int=100, puuid:str|None=None,
        client:RiotClient|None=None, parent_run_id:str|None=None) -> tuple[list[str], list[str]]:
    """Recupera e registra gli ID dei match ranked solo/duo di un giocatore.

    Parte dal Riot ID, di cui risolve il PUUID, oppure da un PUUID già noto, e
    salva le associazioni tra giocatore e match. Registra stato e metriche della
    run; gli errori non gestiti dal servizio vengono propagati al chiamante.
    Con un client passato dall'esterno ne azzera le metriche all'inizio, così la
    run registra solo le proprie richieste; il chiamante resta proprietario del
    client.

    Solleva ValueError per start o count negativi e InputError se non è fornito
    esattamente uno tra puuid e la coppia gameName+tagLine; in quel caso la run
    viene chiusa come FAILED. Propaga le interruzioni.

    Parameters
    ----------
    gameName : str | None
        Nome del giocatore nel Riot ID. Da fornire insieme a tagLine, in
        alternativa a puuid. Default: None.
    tagLine : str | None
        Tag del Riot ID, senza il separatore '#'. Da fornire insieme a
        gameName, in alternativa a puuid. Default: None.
    start : int
        Offset iniziale nella lista Riot, previsto non negativo. Default: 0.
    count : int
        Numero massimo di ID da richiedere o selezionare. Default: 100.
    puuid : str | None
        PUUID già noto; salta la risoluzione da Riot ID. Da fornire da solo, in
        alternativa alla coppia gameName+tagLine. Default: None.
    client : RiotClient | None
        Client Riot da riutilizzare; con None ne viene creato uno nuovo.
        Default: None.
    parent_run_id : str | None
        UUID della run del job chiamante, registrato come parent_run_id di
        questa run; None se la run è una radice. Default: None.

    Returns
    -------
    tuple[list[str], list[str]]
        ID con timeline elaborabile e ID con dettaglio elaborabile, tra quelli
        ricevuti da Riot, anche già associati al giocatore. Una lista vuota può
        indicare cooldown o assenza di candidati.
    """

    # Verifico la correttezza dei parametri
    if start < 0:
        raise ValueError("start deve essere >= 0")
    if count < 0:
        raise ValueError("count deve essere >= 0")

    # faccio partire la run
    with DbSession() as conn:
        reporting_run = RunMetricsRepository(conn)
        run_id, run_started_dt = reporting_run.start_run(
            parent_run_id=parent_run_id,
            pipeline="ingest_ranked_match_ids",
            params={
                "puuid":puuid,
                "game_name":gameName, 
                "tag_line": tagLine, 
                "start":start, 
                "count":count
            }
        )

    # inizializzo i contatori
    end_status = "RUNNING"
    run_tracker = TelemetryTracker("ingestion_run")
    run_token = run_id_var.set(run_id)

    try:
        # apro la connessione al client e la passo al service che si occupa dei match
        if client is None:
            client = RiotClient()

        client.reset_metrics()
        service = MatchIngestionService(client)

        # effettuo l'ingestion dei match
        retrieved_ids, timelines_to_fetch, detail_to_fetch = service.ingest_ranked_match_ids(
            gameName=gameName, 
            tagLine=tagLine, 
            puuid=puuid,
            start=start, 
            count=count
        )

        # Registro le nuove associazioni PUUID-match e completo la run
        run_tracker.record_metrics({"total_ok": len(retrieved_ids)})
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

            if client is not None:
                run_tracker.record_metrics(client.metrics_summary)

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

    return timelines_to_fetch, detail_to_fetch
