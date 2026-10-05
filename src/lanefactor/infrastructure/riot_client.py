from .logging_context import run_id_var, batch_id_var
from dataclasses import dataclass
from dotenv import load_dotenv
from typing import Any
import requests
import logging
import time
import math
import os

logger = logging.getLogger(__name__)

@dataclass
class RiotApiError(Exception):

    status_code: int
    message: str
    endpoint: str | None = None

    def __str__(self) -> str:
        """Formatta l’errore HTTP includendo l’endpoint quando presente.

        Parameters
        ----------
        None
            Nessun parametro esplicito.

        Returns
        -------
        str
            Messaggio dell’errore con codice HTTP ed eventuale endpoint.
        """

        base = f"Riot API error {self.status_code}: {self.message}"
        return f"{base} [{self.endpoint}]" if self.endpoint else base


class RiotClient:

    def __init__(self) -> None:
        """Carica la configurazione Riot e inizializza cache e metriche.

        Carica .env e legge RIOT_API_KEY, REGION, i parametri interi RIOT_TIMEOUT,
        RIOT_MAX_ATTEMPTS e RIOT_MAX_SLEEP e il decimale RIOT_MIN_REQUEST_INTERVAL,
        tutti obbligatori. Timeout e tentativi devono essere positivi; attesa
        massima e intervallo minimo possono essere zero.
        Solleva ValueError per chiave o regione assenti, valori non convertibili
        o limiti non validi; TypeError per parametri numerici assenti.

        Parameters
        ----------
        None
            Nessun parametro esplicito.

        Returns
        -------
        None
            Nessuna restituzione di valore.
        """

        self._http_counts: dict
        self._total_sleep_seconds: float

        # Carico le variabili da un eventuale file .env (con Compose arrivano già dall'ambiente)
        load_dotenv()

        # Leggo la configurazione dall'ambiente
        self.api_key = os.getenv("RIOT_API_KEY")
        self.region = os.getenv("REGION")
        self.max_attempts = int(os.getenv("RIOT_MAX_ATTEMPTS"))
        self.max_sleep = int(os.getenv("RIOT_MAX_SLEEP"))
        self.timeout = int(os.getenv("RIOT_TIMEOUT"))
        self.min_request_interval = float(os.getenv("RIOT_MIN_REQUEST_INTERVAL"))

        self.headers = {"X-Riot-Token":self.api_key}
        self._puuid_cache = {}

        self.reset_metrics()
        self._validate_config()


    @property
    def total_sleep_seconds(self) -> float:
        """Restituisce i secondi di attesa programmati per i retry dall’ultimo reset.

        Parameters
        ----------
        None
            Nessun parametro esplicito.

        Returns
        -------
        float
            Somma delle attese programmate, anche se interrotte anticipatamente.
        """

        return self._total_sleep_seconds


    @property
    def http_counts(self) -> dict[int, int]:
        """Restituisce una copia dei conteggi HTTP dall’ultimo reset.

        Parameters
        ----------
        None
            Nessun parametro esplicito.

        Returns
        -------
        dict[int, int]
            Numero di risposte osservate per codice HTTP.
        """

        return self._http_counts.copy()


    @property
    def metrics_summary(self) -> dict[str, int | float]:
        """Restituisci i conteggi degli errori HTTP e i secondi di attesa dei retry.

        Parameters
        ----------
        None
            Nessun parametro esplicito.

        Returns
        -------
        dict[str, int | float]
            Conteggi total_429, total_4xx esclusi i 429, total_5xx e total_sleep_seconds.
        """

        summary = {
            "total_429": self._http_counts.get(429, 0),
            "total_4xx": sum(v for code, v in self._http_counts.items() if code // 100 == 4 and code != 429),
            "total_5xx": sum(v for code, v in self._http_counts.items() if code // 100 == 5),
            "total_sleep_seconds": self._total_sleep_seconds
        }
        return summary


    def reset_metrics(self) -> None:
        """Azzera i conteggi delle risposte HTTP e il tempo di attesa dei retry.

        Parameters
        ----------
        None
            Nessun parametro esplicito.

        Returns
        -------
        None
            Nessuna restituzione di valore.
        """

        self._http_counts = {}
        self._total_sleep_seconds = 0


    def request(self, endpoint:str, headers:dict=None, params:dict=None) -> requests.Response:
        """Esegui una richiesta GET con timeout e tentativi limitati.

        Riprova in caso di errori di connessione, risposte 429 o errori 5xx.
        Restituisci la risposta 200; propaga RequestException o RiotApiError
        quando i tentativi sono esauriti o lo stato HTTP non consente retry.

        Parameters
        ----------
        endpoint : str
            URL della risorsa Riot.
        headers : dict
            Header aggiuntivi; non sostituiscono il token configurato. Default: None.
        params : dict
            Parametri della query HTTP, oppure None. Default: None.

        Returns
        -------
        requests.Response
            Risposta con stato 200; gli errori finali vengono propagati.
        """

        BASE_DELAY = 2

        headers = headers or {}
        params = params or {} # Per simmetria

        merged = self.headers.copy()
        merged.update(headers)
        merged["X-Riot-Token"] = self.headers["X-Riot-Token"]

        # Loop fino a max_attempts, l'ultimo esce direttamente
        for attempt in range(self.max_attempts):
            fallback = min(BASE_DELAY*2**attempt, self.max_sleep)

            pacing_sleep:float = 0.0
            started = time.monotonic()
            # Gestisco i retry per errore di connessione
            try:

                response = requests.get(
                    url=endpoint,
                    params=params,
                    headers=merged,
                    timeout=self.timeout
                )

            except requests.RequestException as e:
                warn_msg = "Riot API connection error ({}) after {:.1f}s | endpoint: {} | attempt={}/{} | retry in {}s | run_id: {} | batch_id: {}"
                logger.warning(
                    warn_msg.format(
                        type(e).__name__,
                        time.monotonic() - started,
                        endpoint,
                        attempt+1,
                        self.max_attempts,
                        fallback if attempt < self.max_attempts-1 else "-",
                        run_id_var.get(),
                        batch_id_var.get()
                    )
                )

                if attempt == self.max_attempts-1:
                    # Se finiscono i tentativi, rilancio(RequestException)
                    raise

                # Ho una RequestException e ancora tentativi, vado al prossimo
                self._total_sleep_seconds += fallback
                time.sleep(fallback)
                continue

            finally:
                elapsed = time.monotonic() - started
                pacing_sleep = max(0, self.min_request_interval-elapsed)

                self._total_sleep_seconds += pacing_sleep
                time.sleep(pacing_sleep)

            # Gestisco retry/raise per response ricevuta
            try:
                self._validate_response(response, endpoint)
            except RiotApiError as e:
                sc = e.status_code
                if attempt == self.max_attempts-1: # Se finiscono i tentativi, rilancio(RiotApiError)
                    raise

                if sc == 429: # Retry per rate limit

                    sleep_s = fallback
                    try:
                        # Controllo sul retry_after ricevuto
                        retry_after = float(response.headers.get("Retry-After"))
                        if math.isfinite(retry_after) and retry_after >= 0:
                            sleep_s = min(retry_after, self.max_sleep)

                    except (ValueError, TypeError):
                        pass

                    warn_msg = "Riot API rate limit hit (429) — retrying in {}s | endpoint: {} | attempt={} | run_id: {} | batch_id: {}"
                    logger.warning(
                        warn_msg.format(
                            sleep_s,
                            endpoint,
                            attempt+1,
                            run_id_var.get(),
                            batch_id_var.get()
                        )
                    )

                    info_message = "Retry INFO: Retry-After: {} | X-Rate-Limit-Type: {} | X-App-Rate-Limit: {} | " \
                    "X-App-Rate-Limit-Count: {} | X-Method-Rate-Limit: {} | X-Method-Rate-Limit-Count: {}"
                    logger.info(
                        info_message.format(
                            response.headers.get("Retry-After"),
                            response.headers.get("X-Rate-Limit-Type"),
                            response.headers.get("X-App-Rate-Limit"),
                            response.headers.get("X-App-Rate-Limit-Count"),
                            response.headers.get("X-Method-Rate-Limit"),
                            response.headers.get("X-Method-Rate-Limit-Count"),
                        )
                    )

                    self._total_sleep_seconds += sleep_s
                    time.sleep(sleep_s)
                    continue

                elif sc//100 ==5: # Retry per server error
                    warn_msg = "Riot API server error ({}) — retrying in {}s | endpoint: {} | attempt={}/{} | run_id: {} | batch_id: {}"
                    logger.warning(
                        warn_msg.format(
                            sc,
                            fallback,
                            endpoint,
                            attempt+1,
                            self.max_attempts,
                            run_id_var.get(),
                            batch_id_var.get()
                        )
                    )
                    
                    self._total_sleep_seconds += fallback
                    time.sleep(fallback)
                    continue # Non necessario, lascio per simmetria

                else:
                    # Per errori non gestiti ma soprattutto 400, 401, 403, 404 chiudo
                    # In questo caso rilancio una RiotApiError
                    raise
            else:
                return response


    def _get_json(self, endpoint:str, headers:dict=None, params:dict=None) -> Any:
        """Esegui la richiesta e restituisci il contenuto JSON decodificato.

        Parameters
        ----------
        endpoint : str
            URL della risorsa Riot.
        headers : dict
            Header aggiuntivi; non sostituiscono il token configurato. Default: None.
        params : dict
            Parametri della query HTTP, oppure None. Default: None.

        Returns
        -------
        Any
            Contenuto JSON decodificato; gli errori HTTP e di decoding vengono propagati.
        """

        return self.request(endpoint, headers, params).json()


    def _validate_config(self) -> None:
        """Verifica le credenziali configurate e i limiti numerici dei retry.

        Richiede chiave API e regione non vuote, tentativi e timeout positivi,
        attesa massima e intervallo minimo tra richieste non negativi. I
        parametri numerici devono essere già convertiti. Solleva ValueError se
        un controllo fallisce.
        Non verifica la validità della chiave o della regione presso Riot.

        Parameters
        ----------
        None
            Nessun parametro esplicito.

        Returns
        -------
        None
            Nessuna restituzione di valore.
        """

        if not self.api_key:
            raise ValueError("RIOT_API_KEY non configurata")

        if not self.region:
            raise ValueError("REGION non configurata")

        if self.max_attempts <= 0:
            raise ValueError("RIOT_MAX_ATTEMPTS deve essere positivo.")

        if self.timeout <= 0:
            raise ValueError("RIOT_TIMEOUT deve essere positivo.")

        if self.max_sleep < 0:
            raise ValueError("RIOT_MAX_SLEEP deve essere non negativo.")

        if self.min_request_interval < 0:
            raise ValueError("RIOT_MIN_REQUEST_INTERVAL deve essere non negativo.")


    def _validate_response(self, response: requests.Response, endpoint: str | None = None) -> None:
        """Conta la risposta HTTP e solleva RiotApiError se lo stato non è 200.

        Parameters
        ----------
        response : requests.Response
            Risposta HTTP da contare e validare.
        endpoint : str | None
            URL della risorsa Riot. Default: None.

        Returns
        -------
        None
            Nessuna restituzione di valore.
        """

        sc = response.status_code
        self._http_counts[sc] = self._http_counts.get(sc, 0) + 1

        if sc == 200:
            return  # Tutto ok, proseguiamo

        elif sc == 403:
            # Il 403 indica quasi sempre che devi rigenerare la chiave sul portale
            msg = "Errore 403: La tua RIOT_API_KEY è scaduta o non valida."

        elif sc == 404:
            # Utile per segnalare se un player o un match non esistono
            msg = "Errore 404: Risorsa non trovata (Player o Match errato)."

        elif sc == 429:
            # Gestione del Rate Limit
            msg = "Errore 429: Rate Limit superato. Rallenta le chiamate."

        else:
            # Per tutti gli altri errori (500, 503, ecc.)
            msg = f"HTTP {sc} [{response.reason}]"

        raise RiotApiError(sc, msg, endpoint)


    def _get_puuid(self, gameName:str, tagLine:str) -> str:
        """Recupera il PUUID dalla cache in memoria o dalle API Riot.

        Solleva ValueError se la risposta non contiene un PUUID.

        Parameters
        ----------
        gameName : str
            Nome del giocatore nel Riot ID.
        tagLine : str
            Tag del Riot ID, senza il separatore '#'.

        Returns
        -------
        str
            PUUID restituito da Riot o dalla cache in memoria.
        """

        key = (gameName, tagLine)
        if key in self._puuid_cache:
            return self._puuid_cache[key]

        # Dati per la request
        url = "https://{region}.api.riotgames.com/riot/account/v1/accounts/by-riot-id/{gameName}/{tagLine}"

        # Chiamata API verso Riot
        endpoint = url.format(region=self.region, gameName=gameName, tagLine=tagLine)
        data = self._get_json(endpoint)

        puuid = data.get("puuid")
        if not puuid:
            raise ValueError(f"Nessun puuid nella risposta: {data}")
        self._puuid_cache[key] = puuid

        return puuid


    def _get_match_ids(self, puuid:str, start:int=0, count:int=100) -> list[str]:
        """Richiedi gli ID dei match ranked solo/duo del PUUID, da start per count.

        Parameters
        ----------
        puuid : str
            Identificatore testuale del giocatore.
        start : int
            Offset iniziale nella lista Riot, previsto non negativo. Default: 0.
        count : int
            Numero massimo di ID da richiedere o selezionare. Default: 100.

        Returns
        -------
        list[str]
            ID restituiti da Riot per la coda ranked solo/duo.
        """

        # Dati per la request
        url = 'https://{region}.api.riotgames.com/lol/match/v5/matches/by-puuid/{puuid}/ids'
        params = {
            "start": start,
            "count": count,
            "queue": 420 # Parametro per la solo/duo
        }

        # Chiamata API verso Riot
        endpoint = url.format(region=self.region, puuid=puuid)
        match_ids = self._get_json(endpoint, params=params)

        return match_ids


    def _get_match_timeline(self, match_id:str) -> dict:
        """Scarica la timeline del match e solleva ValueError se il payload è vuoto.

        Parameters
        ----------
        match_id : str
            Identificatore del match.

        Returns
        -------
        dict
            Payload non vuoto restituito da Riot.
        """

        # Dati per la request
        url = 'https://{region}.api.riotgames.com/lol/match/v5/matches/{match_id}/timeline'

        # Chiamata API verso Riot
        endpoint = url.format(region=self.region, match_id=match_id)
        match_timeline = self._get_json(endpoint)
        if not match_timeline:
            raise ValueError(f"Nessuna timeline nella risposta: {match_timeline}")

        return match_timeline


    def _get_match_detail(self, match_id:str) -> dict:
        """Scarica il dettaglio del match e solleva ValueError se manca info.

        Parameters
        ----------
        match_id : str
            Identificatore del match.

        Returns
        -------
        dict
            Payload restituito da Riot, con la chiave info.
        """

        # Dati per la request
        url = 'https://{region}.api.riotgames.com/lol/match/v5/matches/{match_id}'

        # Chiamata API verso Riot
        endpoint = url.format(region=self.region, match_id=match_id)
        match_detail = self._get_json(endpoint)
        if not match_detail or "info" not in match_detail:
            raise ValueError(f"Nessun dettaglio nella risposta: {match_detail}")

        return match_detail
