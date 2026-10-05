from sqlalchemy.engine import Connection
from uuid import UUID
from lanefactor.infrastructure.repositories.match_repository import MatchRepository
from lanefactor.infrastructure.repositories.match_timeline_repository import MatchTimelineRepository
from lanefactor.services.ingestion.payload_ingestion_service import PayloadIngestionService

class TimelineIngestionService(PayloadIngestionService):
    """Scarica e salva le timeline dei match (match-v5 /matches/{id}/timeline)."""

    def _make_repo(self, conn: Connection) -> MatchTimelineRepository:
        return MatchTimelineRepository(conn)

    def _fetch(self, match_id: str) -> dict:
        return self.riot._get_match_timeline(match_id)

    def _store(self, repo: MatchTimelineRepository, match_id: str, status: str, https_status: int | None,
               payload: dict | None, run_id: UUID | str, batch_id: str | None) -> None:
        repo.insert_timeline(
            match_id=match_id, status=status, https_status=https_status,
            match_timeline=payload, run_id=run_id, batch_id=batch_id,
        )

    def _mark(self, m_repo: MatchRepository, ok_ids: list[str]) -> None:
        m_repo.mark_timeline_fetched(ok_ids)