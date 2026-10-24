"""Exceptions propres au projet quantbot."""


class PatternBotError(Exception):
    """Base de toutes les erreurs du projet."""


class ConfigError(PatternBotError):
    """Configuration invalide."""


class DataValidationError(PatternBotError):
    """Données OHLCV invalides."""


class DataFetchError(PatternBotError):
    """Echec de récupération de données externes."""


class ExecutionError(PatternBotError):
    """Erreur d'exécution d'ordre."""


class LiveTradingDisabledError(ExecutionError):
    """Le trading réel n'est pas explicitement autorisé."""


class AIAdapterError(PatternBotError):
    """Echec d'un adaptateur LLM."""


class MemoryStoreError(PatternBotError):
    """Echec de la mémoire d'expériences."""
