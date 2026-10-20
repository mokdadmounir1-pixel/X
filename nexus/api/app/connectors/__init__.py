"""Interfaces des connecteurs ultérieurs. Aucun n'est activé en v0.1 : chaque appel lève ConnectorDisabled.
Activer un connecteur exigera une nouvelle décision (ordre d'exécution), un type de tâche de niveau 2 et des tests."""
from __future__ import annotations
from abc import ABC, abstractmethod


class ConnectorDisabled(RuntimeError):
    pass


class Connector(ABC):
    name: str = ""
    enabled: bool = False                # figé à False en v0.1 ; aucune configuration ne le change
    runs_in_container: bool = True

    def _guard(self):
        if not self.enabled:
            raise ConnectorDisabled(f"Connecteur {self.name} non activé dans NEXUS v0.1")

    @abstractmethod
    def describe(self) -> dict: ...

    def health(self) -> dict:
        return {"name": self.name, "enabled": self.enabled, "status": "disabled"}


class Crawl4AI(Connector):
    name = "crawl4ai"

    def describe(self): return {"purpose": "Collecte web pour l'agence (prospects documentés)", "needs_approval": True}
    def fetch(self, url: str): self._guard()


class BrowserUse(Connector):
    name = "browser-use"

    def describe(self): return {"purpose": "Navigation pilotée par agent", "needs_approval": True}
    def run(self, goal: str): self._guard()


class CCXT(Connector):
    name = "ccxt"

    def describe(self): return {"purpose": "Données et ordres crypto", "orders": "interdits sans approbation et sans nouvelle décision"}
    def fetch_ohlcv(self, symbol: str, timeframe: str): self._guard()
    def place_order(self, *a, **k): self._guard()


class MT5(Connector):
    """Processus DISTINCT, sur le PC Windows qui héberge le terminal MetaTrader 5. Le paquet `MetaTrader5`
    ne fonctionne que sous Windows : ne pas supposer qu'il tourne dans un conteneur Linux."""
    name = "mt5"
    runs_in_container = False

    def describe(self): return {"purpose": "Lecture des exports et état du terminal", "platform": "Windows uniquement",
                                "availability": "non vérifiée : aucun terminal MT5 dans l'environnement de développement"}
    def terminal_status(self): self._guard()
    def place_order(self, *a, **k): self._guard()


REGISTRY: dict[str, Connector] = {c.name: c for c in (Crawl4AI(), BrowserUse(), CCXT(), MT5())}
