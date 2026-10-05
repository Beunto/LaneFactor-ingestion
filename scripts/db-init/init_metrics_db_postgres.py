import os
import sqlalchemy
from sqlalchemy import text
from sqlalchemy import create_engine

SCHEMA = """
CREATE SCHEMA IF NOT EXISTS metrics;

CREATE TABLE IF NOT EXISTS metrics.ingestion_run_metrics (
    run_id UUID PRIMARY KEY,
    parent_run_id UUID REFERENCES metrics.ingestion_run_metrics(run_id),
    pipeline TEXT NOT NULL,
    started_at TIMESTAMPTZ NOT NULL,
    ended_at TIMESTAMPTZ,
    status TEXT NOT NULL,
    params_json JSONB,
    total_batches INTEGER NOT NULL DEFAULT 0,
    total_ok INTEGER NOT NULL DEFAULT 0,
    total_failed INTEGER NOT NULL DEFAULT 0,
    total_429 INTEGER NOT NULL DEFAULT 0,
    total_4xx INTEGER NOT NULL DEFAULT 0,
    total_5xx INTEGER NOT NULL DEFAULT 0,
    total_sleep_seconds DOUBLE PRECISION NOT NULL DEFAULT 0,
    total_elapsed_ms INTEGER NOT NULL DEFAULT 0,

    CHECK (parent_run_id IS NULL OR parent_run_id <> run_id),
    CHECK (status IN ('RUNNING', 'DONE', 'FAILED', 'STOPPED', 'MISSING')),
    CHECK (ended_at IS NULL OR ended_at >= started_at),
    CHECK (
        (status = 'RUNNING' AND ended_at IS NULL)
        OR (status <> 'RUNNING' AND ended_at IS NOT NULL)
    ),
    CHECK (
        total_ok >= 0
        AND total_failed >= 0
        AND total_429 >= 0
        AND total_4xx >= 0
        AND total_5xx >= 0
        AND total_elapsed_ms >= 0
    ),
    CHECK (
        total_sleep_seconds >= 0
        AND total_sleep_seconds < 'Infinity'::double precision
    ),
    CHECK (total_batches >= 0)
);
CREATE INDEX IF NOT EXISTS idx_run_metrics_started_at
    ON metrics.ingestion_run_metrics(started_at);
CREATE INDEX IF NOT EXISTS idx_run_metrics_pipeline
    ON metrics.ingestion_run_metrics(pipeline);
CREATE INDEX IF NOT EXISTS idx_run_metrics_parent_run_id
    ON metrics.ingestion_run_metrics(parent_run_id)
    WHERE parent_run_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS metrics.ingestion_batch_metrics (
    batch_id UUID PRIMARY KEY,
    run_id UUID NOT NULL,
    batch_index INTEGER NOT NULL,
    started_at TIMESTAMPTZ NOT NULL,
    ended_at TIMESTAMPTZ,
    status TEXT NOT NULL,
    requested_size INTEGER NOT NULL DEFAULT 0,
    selected_count INTEGER NOT NULL DEFAULT 0,
    total_ok INTEGER NOT NULL DEFAULT 0,
    total_failed INTEGER NOT NULL DEFAULT 0,
    total_429 INTEGER NOT NULL DEFAULT 0,
    total_4xx INTEGER NOT NULL DEFAULT 0,
    total_5xx INTEGER NOT NULL DEFAULT 0,
    total_sleep_seconds DOUBLE PRECISION NOT NULL DEFAULT 0,
    total_elapsed_ms INTEGER NOT NULL DEFAULT 0,

    FOREIGN KEY(run_id) REFERENCES metrics.ingestion_run_metrics(run_id),
    UNIQUE(run_id, batch_index),

    CHECK (status IN ('RUNNING', 'DONE', 'FAILED', 'STOPPED', 'MISSING')),
    CHECK (ended_at IS NULL OR ended_at >= started_at),
    CHECK (
        (status = 'RUNNING' AND ended_at IS NULL)
        OR (status <> 'RUNNING' AND ended_at IS NOT NULL)
    ),
    CHECK (
        total_ok >= 0
        AND total_failed >= 0
        AND total_429 >= 0
        AND total_4xx >= 0
        AND total_5xx >= 0
        AND total_elapsed_ms >= 0
    ),
    CHECK (
        total_sleep_seconds >= 0
        AND total_sleep_seconds < 'Infinity'::double precision
    ),
    CHECK (batch_index >= 0),
    CHECK (requested_size >= 0),
    CHECK (selected_count >= 0 AND selected_count <= requested_size)
);
CREATE INDEX IF NOT EXISTS idx_batch_metrics_run_id
    ON metrics.ingestion_batch_metrics(run_id);
CREATE INDEX IF NOT EXISTS idx_batch_metrics_started_at
    ON metrics.ingestion_batch_metrics(started_at);
"""

def main() -> None:
    """Crea le tabelle mancanti usando le variabili POSTGRES_* dell’ambiente.

    Esegue lo schema in una transazione; non migra le tabelle esistenti e
    propaga gli errori di configurazione o SQL.

    Parameters
    ----------
    None
        Nessun parametro esplicito.

    Returns
    -------
    None
        Nessuna restituzione di valore.
    """

    URL = sqlalchemy.URL.create(
        drivername="postgresql+psycopg",
        host=os.getenv("POSTGRES_HOST"),
        port=os.getenv("POSTGRES_PORT"),
        database=os.getenv("POSTGRES_DB"),
        username=os.getenv("POSTGRES_USER"),
        password=os.getenv("POSTGRES_PASSWORD")
    )

    engine = create_engine(URL)

    with engine.begin() as conn:
        conn.execute(text(SCHEMA))

    print("Schema PostgreSQL creato/aggiornato.")

if __name__ == "__main__":
    main()