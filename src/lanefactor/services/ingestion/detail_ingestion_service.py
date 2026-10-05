from sqlalchemy.engine import Connection
from uuid import UUID
from lanefactor.infrastructure.repositories.match_repository import MatchRepository
from lanefactor.infrastructure.repositories.match_detail_repository import MatchDetailRepository
from lanefactor.services.ingestion.payload_ingestion_service import PayloadIngestionService

class DetailIngestionService(PayloadIngestionService):
    """Scarica e salva il dettaglio dei match (match-v5 /matches/{id})."""

    def _make_repo(self, conn: Connection) -> MatchDetailRepository:
        return MatchDetailRepository(conn)

    def _fetch(self, match_id: str) -> dict:
        return self.riot._get_match_detail(match_id)

    def _store(self, repo: MatchDetailRepository, match_id: str, status: str, https_status: int | None,
               payload: dict | None, run_id: UUID | str, batch_id: str | None) -> None:
        repo.insert_detail(
            match_id=match_id, status=status, https_status=https_status,
            match_detail=payload, run_id=run_id, batch_id=batch_id,
        )

    def _mark(self, m_repo: MatchRepository, ok_ids: list[str]) -> None:
        m_repo.mark_detail_fetched(ok_ids)