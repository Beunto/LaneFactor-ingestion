-- Migrazione del 2026-10-01 per un database già inizializzato.
--
-- 1. core.match_timeline_fetch diventa core.match_timeline (con indici e vincoli).
-- 2. core.match riceve il flag detail_fetched.
--
-- Da eseguire PRIMA di init_db_postgres.py, che poi crea core.match_detail e gli
-- indici mancanti: se gira prima, crea una core.match_timeline vuota accanto a
-- quella vecchia. Lo script è idempotente.

BEGIN;

ALTER TABLE IF EXISTS core.match_timeline_fetch RENAME TO match_timeline;

ALTER INDEX IF EXISTS core.match_timeline_fetch_pkey RENAME TO match_timeline_pkey;
ALTER INDEX IF EXISTS core.idx_match_timeline_fetch_run_id RENAME TO idx_match_timeline_run_id;
ALTER INDEX IF EXISTS core.idx_match_timeline_fetch_batch_id RENAME TO idx_match_timeline_batch_id;
ALTER INDEX IF EXISTS core.idx_match_fetch_status RENAME TO idx_match_timeline_status;
ALTER INDEX IF EXISTS core.idx_match_fetch_fetched_at RENAME TO idx_match_timeline_fetched_at;
ALTER INDEX IF EXISTS core.idx_match_timeline_fetch_seeds_pending RENAME TO idx_match_timeline_seeds_pending;

DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'match_timeline_fetch_match_id_fkey'
          AND conrelid = 'core.match_timeline'::regclass
    ) THEN
        ALTER TABLE core.match_timeline
            RENAME CONSTRAINT match_timeline_fetch_match_id_fkey TO match_timeline_match_id_fkey;
    END IF;
END $$;

ALTER TABLE core.match
    ADD COLUMN IF NOT EXISTS detail_fetched BOOLEAN NOT NULL DEFAULT FALSE;

COMMIT;
