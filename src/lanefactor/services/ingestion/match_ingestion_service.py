from lanefactor.infrastructure.repositories.account_cache_repository import AccountCacheRepository
from lanefactor.infrastructure.repositories.puuid_match_repository import PuuidMatchRepository
from lanefactor.infrastructure.repositories.match_repository import MatchRepository
from lanefactor.infrastructure.signal_guard import block_sigint
from lanefactor.infrastructure.riot_client import RiotClient
from lanefactor.infrastructure.db_session import DbSession
from lanefactor.exceptions import InputError

class MatchIngestionService:

    def __init__(self, riot: RiotClient) -> None:
        """Inizializza l’istanza e le dipendenze utilizzate dai metodi.

        Parameters
        ----------
        riot : RiotClient
            Client Riot usato per le richieste e le metriche HTTP.

        Returns
        -------
        None
            Nessuna restituzione di valore.
        """

        self.riot = riot


    def _validate_input_identity(self, gameName:str|None=None, tagLine:str|None=None, puuid:str|None=None) -> bool:
        """Valida che esattamente uno tra gameName+tagLine o puuid sia fornito.

        Parameters
        ----------
        gameName : str | None
            Nome del giocatore nel Riot ID. Va fornito insieme a tagLine, in
            alternativa a puuid. Default: None.
        tagLine : str | None
            Tag del Riot ID, senza il separatore '#'. Va fornito insieme a
            gameName, in alternativa a puuid. Default: None.
        puuid : str | None
            PUUID del giocatore. Va fornito da solo, in alternativa alla coppia
            gameName+tagLine. Default: None.

        Returns
        -------
        bool
            True se è stato fornito gameName+tagLine, False se è stato fornito
            puuid.

        Raises
        ------
        InputError
            Se è fornito solo uno tra gameName e tagLine, se nessuno tra coppia
            e puuid è fornito, oppure se sono forniti sia la coppia che il puuid.
        """

        has_name = bool(gameName)
        has_tag = bool(tagLine)
        has_puuid = bool(puuid)

        if has_name != has_tag:
            raise InputError("Deve essere fornito sia gameName che tagLine insieme.")

        has_riot_id = has_name and has_tag
        if has_riot_id == has_puuid:
            raise InputError("Deve essere fornito esattamente uno tra gameName+tagLine o puuid.")

        return has_riot_id
        

    def _resolve_puuid(self, gameName:str, tagLine:str) -> str:
        """Recupera il PUUID dalla cache o da Riot e aggiorna la cache se assente.

        Parameters
        ----------
        gameName : str
            Nome del giocatore nel Riot ID.
        tagLine : str
            Tag del Riot ID, senza il separatore '#'.

        Returns
        -------
        str
            PUUID dalla cache persistente o da Riot.
        """

        # Controllo se il PUUID è già in cache
        with DbSession() as conn:
            cache_repo = AccountCacheRepository(connection=conn)
            puuid = cache_repo.get_puuid(gameName, tagLine)
            if puuid:
                return puuid
            
        # cache miss -> passo per riot_client
        puuid = self.riot._get_puuid(gameName, tagLine)
        
        # aggiorna cache
        with block_sigint(), DbSession() as conn:
            cache_repo = AccountCacheRepository(connection=conn)
            cache_repo.upsert_account(gameName, tagLine, puuid)

        return puuid


    def ingest_ranked_match_ids(self, gameName:str=None, tagLine:str=None, puuid:str=None, start:int=0, count:int=100) -> tuple[list[str], list[str], list[str]]:
        """Registra i match ranked solo/duo e seleziona timeline e dettagli da scaricare.

        Richiede fino a count ID da start, in pagine di massimo 100. Registra prima
        i match globali e poi le nuove associazioni. Valuta tutti gli ID ricevuti
        per i download, inclusi quelli già associati, rispettando il cooldown.
        Il limite count riguarda gli ID richiesti a Riot, non le nuove associazioni.

        Parameters
        ----------
        gameName : str | None
            Nome del giocatore nel Riot ID. Da fornire insieme a tagLine, in
            alternativa a puuid. Default: None.
        tagLine : str | None
            Tag del Riot ID, senza il separatore '#'. Da fornire insieme a
            gameName, in alternativa a puuid. Default: None.
        puuid : str | None
            PUUID già noto; salta la risoluzione da Riot ID. Da fornire da solo,
            in alternativa alla coppia gameName+tagLine. Default: None.
        start : int
            Offset iniziale nella lista Riot, previsto non negativo. Default: 0.
        count : int
            Numero massimo di ID da richiedere o selezionare. Default: 100.

        Returns
        -------
        tuple[list[str], list[str], list[str]]
            Nuove associazioni in ordine Riot, ID delle timeline elaborabili e
            ID dei dettagli elaborabili. Le liste possono essere vuote; le
            ultime due non garantiscono l’ordine Riot.

        Raises
        ------
        InputError
            Se la combinazione di gameName, tagLine e puuid non è valida.
        """

        validation = self._validate_input_identity(gameName, tagLine, puuid)
        # controllo se il dato è in cache, eventualmente lo scarico e prendo i match_ids

        if validation:
            puuid = self._resolve_puuid(gameName, tagLine)

        # calcolo remaining e fetched per gestione di batch superiori a 100
        remaining: int=count

        # calcolo gli ID restituiti
        retrieved_ids: list[str] = []
        timelines_to_fetch: list[str] = []
        detail_to_fetch: list[str] = []
        with DbSession() as conn: 
            m_repo = MatchRepository(conn)
            pm_repo = PuuidMatchRepository(conn)
            for idx in range(start, start+count, 100):
                requested_page_size = min(100, remaining)

                match_ids = self.riot._get_match_ids(puuid, idx, requested_page_size)
                new_for_puuid = pm_repo.filter_unseen_match(puuid, match_ids)

                retrieved_ids.extend(new_for_puuid)

                with block_sigint():
                    m_repo.mark_seen(match_ids)
                    pm_repo.mark_seen(puuid, new_for_puuid)

                timelines_to_fetch.extend(m_repo.timelines_to_fetch(match_ids))
                detail_to_fetch.extend(m_repo.detail_to_fetch(match_ids))

                remaining -= len(match_ids)
                if remaining == 0 or len(match_ids) < requested_page_size:
                    break
            
            return retrieved_ids, timelines_to_fetch, detail_to_fetch
