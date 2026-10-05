from sqlalchemy import text
from sqlalchemy.engine import Connection
from datetime import datetime, timezone
import uuid
import json

RUN_STATUS_RUNNING = "RUNNING"
RUN_STATUS_DONE = "DONE"
RUN_STATUS_FAILED = "FAILED"
RUN_STATUS_STOPPED = "STOPPED"
RUN_STATUS_MISSING = "MISSING"

class RunMetricsRepository:

    def __init__(self, connection:Connection) -> None:
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

    def start_run(self, pipeline:str, params: dict | None = None, parent_run_id:str|None=None) -> tuple[str, datetime]:
        """Registra una run RUNNING e restituisci il suo ID e la data di inizio.

        Serializza params come JSON quando presente; altrimenti salva NULL.

        Parameters
        ----------
        pipeline : str
            Nome del flusso di ingestione.
        params : dict | None
            Parametri della run da serializzare in JSON, oppure None. Default: None.
        parent_run_id : str | None
            UUID della run che ha avviato questa, deve già esistere in
            ingestion_run_metrics; None per una run radice. Default: None.

        Returns
        -------
        tuple[str, datetime]
            UUID della run come stringa e data UTC di inizio.
        """

        started_dt = datetime.now(timezone.utc)
        run_id = str(uuid.uuid4())

        ingest_data = {
            "parent_run_id": parent_run_id,
            "run_id": run_id, 
            "status": RUN_STATUS_RUNNING, 
            "pipeline": pipeline,
            "started_at": started_dt,
            "params_json": json.dumps(params, sort_keys=True, ensure_ascii=False) if params is not None else None
        }

        query_insert = text("""
            INSERT INTO metrics.ingestion_run_metrics (parent_run_id, run_id, status, pipeline, started_at, params_json)
            VALUES (:parent_run_id, :run_id, :status, :pipeline, :started_at, :params_json)
        """)

        self._connection.execute(query_insert, ingest_data)

        return run_id, started_dt

    def finish_run(self, run_id: uuid.UUID | str, started_dt: datetime, end_status: str, totals: dict) -> int:
        """Concludi una run ancora RUNNING e restituisci le righe aggiornate.

        Salva lo stato finale, la durata e i totali, usando zero per le metriche
        mancanti. Converti gli stati non riconosciuti in MISSING.

        Parameters
        ----------
        run_id : uuid.UUID | str
            UUID della run, come oggetto UUID o stringa valida.
        started_dt : datetime
            Data di inizio con fuso orario, usata per calcolare la durata.
        end_status : str
            Stato finale; i valori non riconosciuti vengono convertiti in MISSING.
        totals : dict
            Conteggi e tempi aggregati; le metriche assenti valgono zero.

        Returns
        -------
        int
            Numero di run aggiornate; zero se assente o non RUNNING.
        """

        allowed = {RUN_STATUS_DONE, RUN_STATUS_FAILED, RUN_STATUS_STOPPED}
        s = end_status.strip().upper()
        end_status = s if s in allowed else RUN_STATUS_MISSING

        ended_dt = datetime.now(timezone.utc)

        total_batches = totals.get("total_batches", 0)
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
            "total_batches": total_batches,
            "total_ok": total_ok,
            "total_failed": total_failed,
            "total_429": total_429,
            "total_4xx": total_4xx,
            "total_5xx": total_5xx,
            "total_sleep_seconds": total_sleep_seconds,
            "total_elapsed_ms": total_elapsed_ms,
            "run_id": run_id,
            "expected_status": RUN_STATUS_RUNNING
        }

        query_update = text("""
            UPDATE metrics.ingestion_run_metrics
            SET
                ended_at = :ended_at,
                status = :status,
                total_batches = :total_batches,
                total_ok = :total_ok,
                total_failed = :total_failed,
                total_429 = :total_429,
                total_4xx = :total_4xx,
                total_5xx = :total_5xx,
                total_sleep_seconds = :total_sleep_seconds,
                total_elapsed_ms = :total_elapsed_ms
            WHERE run_id = :run_id
            AND status = :expected_status
        """)

        result = self._connection.execute(query_update, ingest_data)
        return result.rowcount
    
    def get_run(self, run_id: str) -> dict:
        """Restituisci i dati della run, oppure un dizionario vuoto se assente.

        Parameters
        ----------
        run_id : str
            UUID della run, come oggetto UUID o stringa valida.

        Returns
        -------
        dict
            Campi della run oppure un dizionario vuoto se assente.
        """

        query_select = text("""SELECT * FROM metrics.ingestion_run_metrics WHERE run_id = :run_id""")
        result = self._connection.execute(query_select, {"run_id": run_id})

        cols = result.keys()
        row = result.fetchone()

        if row is not None:
            run = {col: val for col, val in zip(cols, row)}
        else:
            run = {}

        return run

        
