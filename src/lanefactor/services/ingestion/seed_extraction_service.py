from lanefactor.infrastructure.repositories.match_timeline_repository import MatchTimelineRepository
from lanefactor.infrastructure.repositories.puuid_seed_repository import PuuidSeedRepository
from lanefactor.infrastructure.signal_guard import block_sigint
from lanefactor.infrastructure.db_session import DbSession
from math import ceil

class SeedExtractionService:
    """Alimenta core.puuid_seed con i PUUID trovati nelle timeline già scaricate.

    Elabora a blocchi le timeline FETCHED con seeds_extracted_at NULL, estrae i
    PUUID dei partecipanti, inserisce quelli nuovi come seed e marca le
    timeline come lette. Non chiama Riot e non scarica match: l’uso dei seed
    e l’aggiornamento di last_ingested_at spettano al job che li consuma.
    """


    def count_pending_batches(self, batch_size:int) -> int:
        """Stima il numero di blocchi necessari per elaborare le timeline pendenti.

        Conta le timeline con seed non ancora estratti e le divide per la
        dimensione del blocco, arrotondando per eccesso. È una stima: se nel
        frattempo arrivano altre timeline, i blocchi reali possono essere di più.
        Sola lettura.

        Parameters
        ----------
        batch_size : int
            Dimensione del blocco; deve essere positiva.

        Returns
        -------
        int
            Numero di blocchi previsti; 0 se non ci sono timeline da elaborare.
        """

        with DbSession() as conn:
            mt_repo = MatchTimelineRepository(conn)
            pending = mt_repo.count_pending_seed_timelines()

        return ceil(pending / batch_size)


    @staticmethod
    def extract_puuids(payloads: list[dict]) -> list[str]:
        """Estrae i PUUID unici dai partecipanti delle timeline.

        Legge metadata.participants di ogni payload. Un payload senza
        metadata o senza participants non produce PUUID e non solleva errori.
        Non accede al database.

        Parameters
        ----------
        payloads : list[dict]
            Payload JSON delle timeline già decodificati; una lista vuota è ammessa.

        Returns
        -------
        list[str]
            PUUID senza duplicati, in ordine non garantito.
        """

        puuids = set()
        for payload in payloads:
            puuids.update(payload.get("metadata", {}).get("participants", []))

        return list(puuids)


    def read_batch(self, limit: int) -> tuple[list[str], list[str]]:
        """Legge un blocco di timeline con seed non ancora estratti.

        Seleziona fino a limit timeline FETCHED con seeds_extracted_at NULL ed
        estrae i PUUID dai payload. I match con payload assente (None) restano
        in match_ids, così vengono marcati come letti e non tornano a ogni
        ciclo, ma non contribuiscono ai PUUID. Sola lettura: nessuna modifica
        al database.

        Parameters
        ----------
        limit : int
            Numero massimo di timeline da leggere.

        Returns
        -------
        tuple[list[str], list[str]]
            match_id di tutte le righe lette e PUUID unici estratti dai payload.
        """

        with DbSession() as conn:
            mt_repo = MatchTimelineRepository(conn)
            rows = mt_repo.fetch_pending_seed_timelines(limit)

            match_ids = [match_id for match_id, _ in rows]
            payloads = [payload for _, payload in rows if payload is not None]
            puuids = self.extract_puuids(payloads)

        return match_ids, puuids


    def store_batch(self, match_ids: list[str], puuids: list[str]) -> None:
        """Salva i seed e marca le timeline lette in un’unica transazione.

        Inserisce i PUUID nuovi in core.puuid_seed e poi imposta
        seeds_extracted_at sulle timeline; il marcatore è scritto per ultimo.
        L’operazione è protetta da block_sigint per non lasciare la
        transazione a metà.

        Parameters
        ----------
        match_ids : list[str]
            match_id delle timeline da marcare come lette.
        puuids : list[str]
            PUUID da inserire come seed; quelli già presenti restano invariati.

        Returns
        -------
        None
            Nessuna restituzione di valore.
        """

        with block_sigint(), DbSession() as conn:
            mt_repo = MatchTimelineRepository(conn)
            ps_repo = PuuidSeedRepository(conn)

            ps_repo.insert_seeds(puuids)
            mt_repo.mark_seeds_extracted(match_ids)


    def run(self, limit: int) -> int:
        """Elabora un blocco di timeline: legge, estrae i seed e li salva.

        Con limit non positivo non esegue nulla. Se non ci sono timeline da
        leggere non apre nessuna transazione di scrittura.

        Parameters
        ----------
        limit : int
            Numero massimo di timeline da elaborare in questo blocco.

        Returns
        -------
        int
            Numero di timeline lette; 0 indica che non resta nulla da elaborare
            e il chiamante può fermare il ciclo.
        """

        if limit <= 0:
            return 0

        match_ids, puuids = self.read_batch(limit)

        if match_ids:
            self.store_batch(match_ids, puuids)

        return len(match_ids)