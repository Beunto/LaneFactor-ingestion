from uuid import UUID
from lanefactor.infrastructure.riot_client import RiotClient
from lanefactor.infrastructure.repositories.metrics.batch_metrics_repository import BatchMetricsRepository
from lanefactor.services.ingestion.payload_ingestion_service import PayloadIngestionService
from lanefactor.infrastructure.logging_context import batch_id_var
from lanefactor.infrastructure.signal_guard import block_sigint
from lanefactor.infrastructure.db_session import DbSession
from lanefactor.utils.telemetry import TelemetryTracker
import logging
import sys

logger = logging.getLogger(__name__)

class BatchService:

    def __init__(self, payload_service: PayloadIngestionService) -> None:
        """Inizializza il servizio che coordina il ciclo di vita dei batch.

        Parameters
        ----------
        payload_service : PayloadIngestionService
            Servizio usato per scaricare e salvare i payload e rilevare lo stop.

        Returns
        -------
        None
            Nessuna restituzione di valore.
        """

        self.payload_service = payload_service

    def run_batch(self, match_ids: list[str], run_id: UUID | str, run_tracker: TelemetryTracker, batch_index: int, client: RiotClient) -> tuple[str, str]:

        # Inizializzo il tracker del batch e la repo
        """Esegue un batch di payload e ne registra lo stato e le metriche.

        Crea il batch prima dell’ingestione e aggrega le metriche nella run
        quando lo chiude. Un KeyboardInterrupt intercettato restituisce STOPPED;
        se manca un riepilogo, elimina il batch ancora RUNNING. Gli altri errori
        vengono propagati dopo il tentativo di chiusura con stato FAILED.
        Un errore secondario nella chiusura viene registrato senza sostituire
        l’eccezione già in propagazione. Ripristina il contesto di logging del
        batch all’uscita dal blocco di ingestione e chiusura.

        Il chiamante azzera le metriche del client prima della chiamata e
        gestisce incremento dell’indice, pause e stato finale della run.

        Parameters
        ----------
        match_ids : list[str]
            ID dei match da scaricare.
        run_id : UUID | str
            Identificatore della run a cui appartiene il batch.
        run_tracker : TelemetryTracker
            Accumulatore delle metriche della run, aggiornato alla chiusura.
        batch_index : int
            Indice del batch da registrare; non viene incrementato dal servizio.
        client : RiotClient
            Client usato dal servizio di ingestione, da cui leggere le metriche.

        Returns
        -------
        tuple[str, str]
            Azione del batch, "finish" oppure "delete", e stato DONE o STOPPED.
            In caso di errore propagato non viene restituito alcun risultato.
        """

        batch_tracker = TelemetryTracker("ingestion_batch")
        with block_sigint(), DbSession() as conn:
            reporting_batch = BatchMetricsRepository(conn)

            # Registro l'avvio del batch
            batch_id, batch_started_dt = reporting_batch.start_batch(run_id, batch_index, len(match_ids))


        # Inizializzo lo stato del batch
        fetch_summary: dict[str, int] = {}
        batch_end_status: str | None = None
        batch_action = "finish"
        batch_token = batch_id_var.set(batch_id)

        try:
            fetch_summary = self.payload_service.fetch_and_store(match_ids, run_id, batch_id)

            # Chiusura happy path
            batch_end_status = "STOPPED" if self.payload_service.stop_requested else "DONE"

        except KeyboardInterrupt:
            # Chiusura per Interruzioni da tastiera
            if not fetch_summary:
                batch_action = "delete"
            batch_end_status = "STOPPED"

        except Exception:
            # Chiusura per interruzione generica
            batch_end_status= "FAILED"
            raise

        finally:
            # Registro una eventuale eccezione sollevata in precedenza
            exc = sys.exc_info()[0]
            has_active_exception = exc is not None

            try:
                with block_sigint(), DbSession() as conn:
                    reporting_batch = BatchMetricsRepository(conn)

                    if batch_action == "delete":
                        reporting_batch.delete_batch(batch_id)
                    elif batch_action == "finish":
                        batch_tracker.record_metrics(client.metrics_summary, fetch_summary)
                        reporting_batch.finish_batch(batch_id, batch_started_dt, batch_end_status, batch_tracker.report)
                        run_tracker.record_metrics(client.metrics_summary, fetch_summary, {"total_batches": 1})

            except Exception:
                if not has_active_exception:
                    raise

                logger.exception(
                    "Errore nella chiusura delle metriche del batch %s",
                    batch_id
                )

            finally:
                batch_id_var.reset(batch_token)

        return batch_action, batch_end_status
