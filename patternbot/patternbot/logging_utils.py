"""Logs structurés : une seule configuration pour tout le package."""
from __future__ import annotations

import logging
import sys
from typing import Optional

from .exceptions import ConfigError

_ROOT = "patternbot"
_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"


def setup_logging(level: str = "INFO", log_file: Optional[str] = None) -> logging.Logger:
    numeric = getattr(logging, str(level).upper(), None)
    if not isinstance(numeric, int):
        raise ConfigError(f"Niveau de log invalide : {level!r}")
    logger = logging.getLogger(_ROOT)
    logger.setLevel(numeric)
    for handler in list(logger.handlers):
        logger.removeHandler(handler)
        handler.close()
    formatter = logging.Formatter(_FORMAT)
    stream = logging.StreamHandler(sys.stderr)
    stream.setFormatter(formatter)
    logger.addHandler(stream)
    if log_file:
        file_handler = logging.FileHandler(log_file, encoding="utf-8")
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)
    logger.propagate = False
    return logger


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(f"{_ROOT}.{name}")
