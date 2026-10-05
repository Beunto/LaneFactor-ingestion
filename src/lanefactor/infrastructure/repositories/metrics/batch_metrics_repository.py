from sqlalchemy.engine import Connection
from sqlalchemy import text
from datetime import datetime, timezone
import uuid

BATCH_STATUS_RUNNING = "RUNNING"
BATCH_STATUS_DONE = "DONE"
BATCH_STATUS_FAILED = "FAILED"
BATCH_STATUS_STOPPED = "STOPPED"
BATCH_STATUS_MISSING = "MISSING"

class BatchMetricsRepository:

    def __init__(self, connection: Connection) -> None:
        """Inizializza l’istanza e le dipendenze utilizzate dai metodi.

        Parameters
        ----------
        connection : Connection
            Connessione SQLAlchemy usata senza eseguire commit nel repository.

        Returns
        -------
        None
            Nessuna restituzione di valore.
        """

        self._connection = connection

    def delete_batch(self, batch_id: uuid.UUID | str) -> int:
        """Elimina un batch ancora RUNNING e restituisci le righe eliminate.

        Parameters
        ----------
        batch_id : uuid.UUID | str
            Identificatore del batch; None è ammesso dove indicato dal tipo.

        Returns
        -------
        int
            Numero di righe eliminate; zero se assente o non RUNNING.
        """

        batch_id = str(batch_id)
        delete_query = text("""
            DELETE FROM metrics.ingestion_batch_metrics 
            WHERE batch_id = :batch_id
            AND status = :status
        """)

        result = self._connection.execute(delete_query, {"batch_id": batch_id, "status": BATCH_STATUS_RUNNING})
        return result.rowcount

    def start_batch(self, run_id: uuid.UUID | str, batch_index:int, requested_size:int) -> tuple[str, datetime]:
        """Registra un batch RUNNING e restituisci il suo ID e la data di inizio.

        Parameters
        ----------
        run_id : uuid.UUID | str
            UUID della run, come oggetto UUID o stringa valida.
        batch_index : int
            Indice del batch all’interno della run.
        requested_size : int
            Numero di ID richiesti per il batch.

        Returns
        -------
        tuple[str, datetime]
            UUID del batch come stringa e data UTC di inizio.
        """

        started_dt = datetime.now(timezone.utc)
        batch_id = str(uuid.uuid4())
        run_id = str(run_id)
        ingest_data = {
            "batch_id": batch_id,
            "run_id": run_id,
            "batch_index": batch_index,
            "status": BATCH_STATUS_RUNNING, 
            "started_at": started_dt,
            "requested_size": requested_size
        }

        query_insert = text("""
            INSERT INTO metrics.ingestion_batch_metrics (batch_id, run_id, batch_index, status, started_at, requested_size)
            VALUES (:batch_id, :run_id, :batch_index, :status, :started_at, :requested_size)
        """)

        self._connection.execute(query_insert, ingest_data)

        return batch_id, started_dt

    def finish_batch(self, batch_id: uuid.UUID | str, started_dt: datetime, end_status: str, totals: dict) -> int:
        """Concludi un batch ancora RUNNING e restituisci le righe aggiornate.

        Salva lo stato finale, la durata e i totali, usando zero per le metriche
        mancanti. Converti gli stati non riconosciuti in MISSING.

        Parameters
        ----------
        batch_id : uuid.UUID | str
            Identificatore del batch; None è ammesso dove indicato dal tipo.
        started_dt : datetime
            Data di inizio con fuso orario, usata per calcolare la durata.
        end_status : str
            Stato finale; i valori non riconosciuti vengono convertiti in MISSING.
        totals : dict
            Conteggi e tempi aggregati; le metriche assenti valgono zero.

        Returns
        -------
        int
            Numero di batch aggiornati; zero se assente o non RUNNING.
        """

        allowed = {BATCH_STATUS_DONE, BATCH_STATUS_FAILED, BATCH_STATUS_STOPPED}
        s = end_status.strip().upper()
        end_status = s if s in allowed else BATCH_STATUS_MISSING

        ended_dt = datetime.now(timezone.utc)

        selected_count = totals.get("selected_count", 0)
        total_ok = totals.get("total_ok", 0)
        total_failed = totals.get("total_failed", 0)
        total_429 = totals.get("total_429", 0)
        total_4xx = totals.get("total_4xx", 0)
        total_5xx = totals.get("total_5xx", 0)
        total_sleep_seconds = totals.get("total_sleep_seconds", 0)
        total_elapsed_ms = int((ended_dt - started_dt).total_seconds() * 1000)

        ingest_data = {
            "ended_at": ended_dt,
            "status": end_status,
            "selected_count": selected_count,
            "total_ok": total_ok,
            "total_failed": total_failed,
            "total_429": total_429,
            "total_4xx": total_4xx,
            "total_5xx": total_5xx,
            "total_sleep_seconds": total_sleep_seconds,
            "total_elapsed_ms": total_elapsed_ms,
            "batch_id": batch_id,
            "expected_status": BATCH_STATUS_RUNNING
        }

        query_update = text("""
            UPDATE metrics.ingestion_batch_metrics
            SET
                ended_at = :ended_at,
                status = :status,
                selected_count = :selected_count,
                total_ok = :total_ok,
                total_failed = :total_failed,
                total_429 = :total_429,
                total_4xx = :total_4xx,
                total_5xx = :total_5xx,
                total_sleep_seconds = :total_sleep_seconds,
                total_elapsed_ms = :total_elapsed_ms
            WHERE batch_id = :batch_id
            AND status = :expected_status
        """)

        result = self._connection.execute(query_update, ingest_data)
        return result.rowcount
    
    def get_batch(self, batch_id: uuid.UUID | str) -> dict:
        """Restituisci i dati del batch, oppure un dizionario vuoto se assente.

        Parameters
        ----------
        batch_id : uuid.UUID | str
            Identificatore del batch; None è ammesso dove indicato dal tipo.

        Returns
        -------
        dict
            Campi del batch oppure un dizionario vuoto se assente.
        """

        query_select = text("""SELECT * FROM metrics.ingestion_batch_metrics WHERE batch_id = :batch_id""")
        result = self._connection.execute(query_select, {"batch_id": batch_id})

        cols = result.keys()
        row = result.fetchone()

        if row is not None:
            batch = {col: val for col, val in zip(cols, row)}
        else:
            batch = {}

        return batch

        