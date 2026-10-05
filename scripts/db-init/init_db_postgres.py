import os
import sqlalchemy
from sqlalchemy import text
from sqlalchemy import create_engine


SCHEMA = """
CREATE SCHEMA IF NOT EXISTS core;

CREATE TABLE IF NOT EXISTS core.puuid_seed (
    puuid TEXT NOT NULL PRIMARY KEY,
    discovered_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_ingested_at TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_puuid_seed_last_ingested_at_discovered_at
ON core.puuid_seed (last_ingested_at NULLS FIRST, discovered_at);

CREATE TABLE IF NOT EXISTS core.match (
    match_id TEXT PRIMARY KEY,
    timeline_fetched BOOLEAN NOT NULL DEFAULT FALSE,
    detail_fetched BOOLEAN NOT NULL DEFAULT FALSE,
    seen_at TIMESTAMPTZ NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_match_timeline_fetched_seen_at
ON core.match (timeline_fetched, seen_at);
CREATE INDEX IF NOT EXISTS idx_match_detail_fetched_seen_at
ON core.match (detail_fetched, seen_at);


CREATE TABLE IF NOT EXISTS core.match_detail (
    match_id TEXT NOT NULL PRIMARY KEY,
    status TEXT NOT NULL,                 -- PENDING / IN_PROGRESS / FETCHED / FAILED / UNAVAILABLE
    fetched_at TIMESTAMPTZ,
    https_status INTEGER,
    detail_bytea BYTEA,
    game_version TEXT,                    -- info.gameVersion, per raggruppare per patch
    queue_id INTEGER,                     -- info.queueId
    game_duration_s INTEGER,              -- info.gameDuration
    end_of_game_result TEXT,              -- info.endOfGameResult
    attempt_count INTEGER NOT NULL DEFAULT 0,
    last_attempt_at TIMESTAMPTZ NOT NULL,
    next_retry_at TIMESTAMPTZ,
    run_id UUID NOT NULL,
    batch_id UUID,

    FOREIGN KEY (match_id) REFERENCES core.match(match_id),

    CHECK (status IN ('PENDING', 'IN_PROGRESS', 'FETCHED', 'FAILED', 'UNAVAILABLE')),
    CHECK (attempt_count >= 0),
    CHECK (next_retry_at IS NULL OR next_retry_at > last_attempt_at),
    CHECK (
        status <> 'FETCHED'
        OR (
            detail_bytea IS NOT NULL
            AND fetched_at IS NOT NULL
            AND https_status IS NOT NULL
            AND https_status = 200
            AND next_retry_at IS NULL
            AND game_version IS NOT NULL
            AND game_duration_s IS NOT NULL
        )
    )
);
CREATE INDEX IF NOT EXISTS idx_match_detail_run_id ON core.match_detail(run_id);
CREATE INDEX IF NOT EXISTS idx_match_detail_batch_id ON core.match_detail(batch_id);
CREATE INDEX IF NOT EXISTS idx_match_detail_status ON core.match_detail(status);
CREATE INDEX IF NOT EXISTS idx_match_detail_version_queue
ON core.match_detail (game_version, queue_id) WHERE status = 'FETCHED';


CREATE TABLE IF NOT EXISTS core.match_timeline (
    match_id TEXT NOT NULL PRIMARY KEY,
    status TEXT NOT NULL,                 -- PENDING / IN_PROGRESS / FETCHED / FAILED / UNAVAILABLE
    fetched_at TIMESTAMPTZ,
    https_status INTEGER,
    timeline_bytea BYTEA,
    attempt_count INTEGER NOT NULL DEFAULT 0,
    last_attempt_at TIMESTAMPTZ NOT NULL,
    next_retry_at TIMESTAMPTZ,
    seeds_extracted_at TIMESTAMPTZ,
    run_id UUID NOT NULL,
    batch_id UUID,

    FOREIGN KEY (match_id) REFERENCES core.match(match_id),

    CHECK (status IN ('PENDING', 'IN_PROGRESS', 'FETCHED', 'FAILED', 'UNAVAILABLE')),
    CHECK (attempt_count >= 0),
    CHECK (next_retry_at IS NULL OR next_retry_at > last_attempt_at),
    CHECK (seeds_extracted_at IS NULL or status = 'FETCHED'),
    CHECK (
        status <> 'FETCHED'
        OR (
            timeline_bytea IS NOT NULL
            AND fetched_at IS NOT NULL
            AND https_status IS NOT NULL
            AND https_status = 200
            AND next_retry_at IS NULL
        )
    )
);
CREATE INDEX IF NOT EXISTS idx_match_timeline_run_id ON core.match_timeline(run_id);
CREATE INDEX IF NOT EXISTS idx_match_timeline_batch_id ON core.match_timeline(batch_id);
CREATE INDEX IF NOT EXISTS idx_match_timeline_status ON core.match_timeline(status);
CREATE INDEX IF NOT EXISTS idx_match_timeline_fetched_at ON core.match_timeline(fetched_at);
CREATE INDEX IF NOT EXISTS idx_match_timeline_seeds_pending
ON core.match_timeline (fetched_at)
WHERE status = 'FETCHED' AND seeds_extracted_at IS NULL;


CREATE TABLE IF NOT EXISTS core.puuid_match (
    puuid TEXT NOT NULL,
    match_id TEXT NOT NULL,
    seen_at TIMESTAMPTZ NOT NULL,
    UNIQUE (puuid, match_id),
    FOREIGN KEY (match_id) REFERENCES core.match (match_id)
);
CREATE INDEX IF NOT EXISTS idx_puuid_match_puuid
ON core.puuid_match (puuid);


CREATE TABLE IF NOT EXISTS core.riot_id_cache (
    game_name TEXT NOT NULL,
    tag_line TEXT NOT NULL,
    puuid TEXT NOT NULL,
    PRIMARY KEY (puuid),
    UNIQUE(game_name, tag_line)
);
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
