from collections import Counter
from typing import Any

class TelemetryTracker:

    _SCHEMAS = {
            "ingestion_batch": [
                "total_429", "total_4xx", "total_5xx", 
                "selected_count", "total_ok", "total_failed", "total_sleep_seconds"
            ],
            "ingestion_run": [
                "total_429", "total_4xx", "total_5xx", 
                "total_batches", "total_ok", "total_failed", "total_sleep_seconds"
            ]
        }
    
    def __init__(self, schema_key: str) -> None:
        """Inizializza i contatori a zero per lo schema richiesto.

        Solleva ValueError per uno schema non riconosciuto.

        Parameters
        ----------
        schema_key : str
            Schema delle metriche: ingestion_run oppure ingestion_batch.

        Returns
        -------
        None
            Nessuna restituzione di valore.
        """

        self.schema_key = schema_key.strip().lower()
        if self.schema_key not in self._SCHEMAS:
            raise ValueError(f"Schema {schema_key} non riconosciuto.")
        
        self.required_keys = self._SCHEMAS[self.schema_key]
        self._collector = Counter({key:0 for key in self.required_keys})

    def record_metrics(self, *metrics: dict[str, Any]) -> None:
        """Somma i valori dei dizionari al contatore delle metriche.

        Per lo schema ingestion_run ignora fetched_ids; le altre chiavi vengono
        accumulate anche quando non fanno parte dello schema iniziale.

        Parameters
        ----------
        *metrics : dict[str, Any]
            Dizionari di valori numerici da sommare per chiave.

        Returns
        -------
        None
            Nessuna restituzione di valore.
        """

        for metric in metrics:
            if self.schema_key == "ingestion_run":
                metric = {k: v for k, v in metric.items() if k != "fetched_ids"}
            self._collector.update(metric)

    @property
    def report(self) -> dict[str, Any]:
        """Restituisci una copia delle metriche accumulate come dizionario.

        Parameters
        ----------
        None
            Nessun parametro esplicito.

        Returns
        -------
        dict[str, Any]
            Copia delle metriche accumulate, comprese eventuali chiavi aggiuntive.
        """

        return dict(self._collector)