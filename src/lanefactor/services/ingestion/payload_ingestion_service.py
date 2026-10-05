from lanefactor.infrastructure.repositories.match_repository import MatchRepository
from lanefactor.infrastructure.riot_client import RiotClient, RiotApiError
from lanefactor.infrastructure.signal_guard import block_sigint
from lanefactor.infrastructure.db_session import DbSession
from requests import RequestException
from sqlalchemy.engine import Connection
from uuid import UUID


class PayloadIngestionService:
    """Base dei servizi che scaricano un payload per match e lo salvano.

    Contiene il ciclo di download, la gestione dello stop e il report; le
    sottoclassi forniscono repository, richiesta, salvataggio e marcatura del
    flag globale tramite _make_repo, _fetch, _store e _mark.
    """

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
        self._stop_requested: bool = False

    @property
    def stop_requested(self) -> bool:
        """Indica se è stato richiesto lo stop durante un download.

        Parameters
        ----------
        None
            Nessun parametro esplicito.

        Returns
        -------
        bool
            True se il servizio ha intercettato una richiesta di interruzione.
        """

        return self._stop_requested


    def _make_repo(self, conn: Connection) -> object:
        """Crea il repository dei payload sulla connessione della transazione.

        Parameters
        ----------
        conn : Connection
            Connessione SQLAlchemy del batch.

        Returns
        -------
        object
            Repository con cui _store salva i tentativi.
        """

        raise NotImplementedError


    def _fetch(self, match_id:str) -> dict:
        """Scarica da Riot il payload del match.

        Parameters
        ----------
        match_id : str
            Identificatore del match.

        Returns
        -------
        dict
            Payload non vuoto; gli errori di rete, HTTP o di valore vengono
            gestiti da fetch_and_store.
        """

        raise NotImplementedError


    def _store(self, repo: object, match_id:str, status:str, https_status:int|None, payload:dict|None, run_id:UUID|str, batch_id:str|None) -> None:
        """Salva l’esito di un tentativo con il repository della sottoclasse.

        Parameters
        ----------
        repo : object
            Repository creato da _make_repo.
        match_id : str
            Identificatore del match.
        status : str
            FETCHED o FAILED.
        https_status : int | None
            Codice HTTP ricevuto oppure None in assenza di risposta.
        payload : dict | None
            Payload scaricato; None in caso di fallimento.
        run_id : UUID | str
            UUID della run.
        batch_id : str | None
            Identificatore del batch, se presente.

        Returns
        -------
        None
            Nessuna restituzione di valore.
        """

        raise NotImplementedError


    def _mark(self, m_repo:MatchRepository, ok_ids:list[str]) -> None:
        """Imposta il flag globale dei match scaricati con successo.

        Parameters
        ----------
        m_repo : MatchRepository
            Repository dei match sulla connessione del batch.
        ok_ids : list[str]
            ID dei match con esito FETCHED.

        Returns
        -------
        None
            Nessuna restituzione di valore.
        """

        raise NotImplementedError


    def fetch_and_store(self, match_ids:list[str], run_id:UUID|str, batch_id:UUID|str|None=None) -> dict[str, int]:
        """Scarica gli ID forniti e salva gli esiti in una transazione di batch.

        Non filtra gli ID prima delle richieste. Gli errori HTTP, di rete e di
        valore gestiti vengono registrati come fallimenti. Un KeyboardInterrupt
        durante il download richiede lo stop; i risultati precedenti vengono
        confermati se la transazione termina regolarmente. Altri errori propagati
        possono causare il rollback dell’intero batch.

        Parameters
        ----------
        match_ids : list[str]
            ID dei match da considerare; una lista vuota è ammessa.
        run_id : UUID | str
            UUID della run, come oggetto UUID o stringa valida.
        batch_id : UUID | str | None
            Identificatore del batch; None è ammesso dove indicato dal tipo. Default: None.

        Returns
        -------
        dict[str, int]
            selected_count conta tutti gli ID ricevuti; total_ok e total_failed
            contano gli esiti gestiti. Dopo uno stop alcuni ID possono non essere tentati.
        """

        batch_id = str(batch_id) if batch_id is not None else None

        with DbSession() as conn:
            m_repo = MatchRepository(conn)
            repo = self._make_repo(conn)

            ok_ids: list[str] = []
            failed_ids : list[str] = []
            # results:list[tuple[str, str, int | None]] = []

            for match_id in match_ids:
                status = "FAILED"
                https_status = None
                payload = None
                try: 
                    payload = self._fetch(match_id)
                except KeyboardInterrupt:
                    self._stop_requested = True
                except (RequestException, ValueError):
                    failed_ids.append(match_id)
                except RiotApiError as e:
                    https_status = e.status_code
                    failed_ids.append(match_id)
                else:
                    status = "FETCHED"
                    https_status = 200
                    ok_ids.append(match_id)
                finally:

                    with block_sigint():
                        # results.append((match_id, status, https_status))
                        if payload is not None or not self._stop_requested:
                            self._store(
                                repo=repo,
                                match_id=match_id,
                                status=status,
                                https_status=https_status,
                                payload=payload,
                                run_id=run_id,
                                batch_id=batch_id,
                            )

                if self._stop_requested:
                    break

            self._mark(m_repo, ok_ids)

        report = {
            "selected_count": len(match_ids),
            "total_ok": len(ok_ids),
            "total_failed": len(failed_ids)
        }

        return report