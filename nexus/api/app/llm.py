"""Passerelle vers Ollama (local). Le modèle propose ; le serveur décide."""
from __future__ import annotations
import json
from typing import Protocol
import httpx
from .errors import LLMUnavailable, LLMBadOutput


class LLM(Protocol):
    def chat(self, system: str, user: str, json_mode: bool = False) -> str: ...


class OllamaClient:
    def __init__(self, base_url: str, model: str, timeout_s: float):
        self.base_url, self.model, self.timeout_s = base_url.rstrip("/"), model, timeout_s

    def chat(self, system: str, user: str, json_mode: bool = False) -> str:
        body = {"model": self.model, "stream": False,
                "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
                "options": {"temperature": 0}}
        if json_mode:
            body["format"] = "json"
        try:
            r = httpx.post(f"{self.base_url}/api/chat", json=body, timeout=self.timeout_s)
            r.raise_for_status()
            return r.json()["message"]["content"]
        except (httpx.HTTPError, KeyError, ValueError) as e:
            raise LLMUnavailable(f"Ollama indisponible : {type(e).__name__}") from e


def parse_json_object(text: str) -> dict:
    try:
        data = json.loads(text)
    except ValueError as e:
        raise LLMBadOutput("Réponse du modèle non JSON") from e
    if not isinstance(data, dict):
        raise LLMBadOutput("Réponse du modèle : objet JSON attendu")
    return data
