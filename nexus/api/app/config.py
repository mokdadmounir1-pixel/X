"""Configuration lue depuis l'environnement. Aucun secret par défaut."""
from __future__ import annotations
import os
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Settings:
    database_url: str
    ollama_url: str = "http://127.0.0.1:11434"
    ollama_model: str = "qwen2.5:7b-instruct"
    llm_timeout_s: float = 60.0
    approval_default_ttl_min: int = 24 * 60
    approval_max_ttl_min: int = 72 * 60
    session_ttl_h: int = 12
    worker_enabled: bool = True
    retry_backoff_s: float = 5.0
    cors_origins: tuple[str, ...] = ("http://127.0.0.1:5173", "http://localhost:5173")
    web_dir: str = ""
    probe_urls: dict = field(default_factory=dict)

    @staticmethod
    def from_env() -> "Settings":
        url = os.environ.get("NEXUS_DATABASE_URL", "")
        if not url:
            raise RuntimeError("NEXUS_DATABASE_URL est obligatoire (voir deploy/.env.example)")
        return Settings(
            database_url=url,
            ollama_url=os.environ.get("NEXUS_OLLAMA_URL", "http://127.0.0.1:11434"),
            ollama_model=os.environ.get("NEXUS_OLLAMA_MODEL", "qwen2.5:7b-instruct"),
            llm_timeout_s=float(os.environ.get("NEXUS_LLM_TIMEOUT_S", "60")),
            worker_enabled=os.environ.get("NEXUS_WORKER", "1") == "1",
            retry_backoff_s=float(os.environ.get("NEXUS_RETRY_BACKOFF_S", "5")),
            web_dir=os.environ.get("NEXUS_WEB_DIR", ""),
        )
