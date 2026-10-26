"""Adaptateurs LLM : Claude, ChatGPT, Hermes (exclusivement). Hermes = modèle LOCAL (exécution / routage d'automatisation), jamais d'appel hors de cette machine.

Chaque adaptateur n'importe son SDK à la demande ; sans clé/SDK il lève
AIAdapterError à la construction et `build_adapters` l'ignore.
"""
from __future__ import annotations

import json
import os
import re
from abc import ABC, abstractmethod
from typing import Any, Optional

from ..config import AIConfig
from ..exceptions import AIAdapterError
from ..logging_utils import get_logger

log = get_logger("ai.adapters")


class LLMAdapter(ABC):
    name = "llm"

    @abstractmethod
    def complete(self, prompt: str, system: Optional[str] = None) -> str: ...


class ClaudeAdapter(LLMAdapter):
    name = "claude"

    def __init__(self, cfg: AIConfig) -> None:
        if not os.environ.get("ANTHROPIC_API_KEY"):
            raise AIAdapterError("ANTHROPIC_API_KEY absent")
        try:
            import anthropic  # type: ignore
        except ImportError as exc:
            raise AIAdapterError("SDK anthropic non installé") from exc
        self._client = anthropic.Anthropic(timeout=cfg.timeout_s)
        self._model = cfg.claude_model

    def complete(self, prompt: str, system: Optional[str] = None) -> str:
        try:
            resp = self._client.messages.create(
                model=self._model, max_tokens=1500, system=system or "You are a quantitative trading analyst.",
                messages=[{"role": "user", "content": prompt}])
            return "".join(b.text for b in resp.content if getattr(b, "type", "") == "text")
        except Exception as exc:
            raise AIAdapterError(f"Claude a échoué : {exc}") from exc


class ChatGPTAdapter(LLMAdapter):
    name = "chatgpt"

    def __init__(self, cfg: AIConfig) -> None:
        if not os.environ.get("OPENAI_API_KEY"):
            raise AIAdapterError("OPENAI_API_KEY absent")
        try:
            import openai  # type: ignore
        except ImportError as exc:
            raise AIAdapterError("SDK openai non installé") from exc
        self._client = openai.OpenAI(timeout=cfg.timeout_s)
        self._model = cfg.chatgpt_model

    def complete(self, prompt: str, system: Optional[str] = None) -> str:
        try:
            msgs = ([{"role": "system", "content": system}] if system else []) + [{"role": "user", "content": prompt}]
            resp = self._client.chat.completions.create(model=self._model, messages=msgs)
            return resp.choices[0].message.content or ""
        except Exception as exc:
            raise AIAdapterError(f"ChatGPT a échoué : {exc}") from exc


class HermesAdapter(LLMAdapter):
    """Hermes local via un serveur Ollama-compatible (`POST /api/chat`) sur la boucle locale uniquement : aucune clé, aucune donnée ne quitte le PC."""

    name = "hermes"

    def __init__(self, cfg: AIConfig) -> None:
        from urllib.parse import urlparse
        u = urlparse(cfg.hermes_url)
        if u.scheme != "http" or u.hostname not in ("127.0.0.1", "localhost", "::1"):
            raise AIAdapterError(f"Hermes doit être local (127.0.0.1/localhost), reçu : {cfg.hermes_url}")
        self._url = cfg.hermes_url.rstrip("/") + "/api/chat"; self._model = cfg.hermes_model; self._timeout = cfg.timeout_s
        import urllib.request
        try:
            urllib.request.urlopen(cfg.hermes_url.rstrip("/") + "/api/tags", timeout=min(3.0, cfg.timeout_s)).read()
        except Exception as exc:
            raise AIAdapterError(f"serveur Hermes local injoignable ({cfg.hermes_url}) : {type(exc).__name__}") from exc

    def complete(self, prompt: str, system: Optional[str] = None) -> str:
        import urllib.request
        msgs = ([{"role": "system", "content": system}] if system else []) + [{"role": "user", "content": prompt}]
        body = json.dumps({"model": self._model, "messages": msgs, "stream": False}).encode()
        try:
            req = urllib.request.Request(self._url, data=body, headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=self._timeout) as r:
                return str(json.loads(r.read().decode()).get("message", {}).get("content", ""))
        except Exception as exc:
            raise AIAdapterError(f"Hermes a échoué : {exc}") from exc


def build_adapters(cfg: AIConfig) -> dict[str, LLMAdapter]:
    adapters: dict[str, LLMAdapter] = {}
    for klass in (ClaudeAdapter, ChatGPTAdapter, HermesAdapter):
        try:
            adapters[klass.name] = klass(cfg)
        except AIAdapterError as exc:
            log.info("Adaptateur %s indisponible : %s", klass.name, exc)
    return adapters


def extract_json(text: str) -> Any:
    """Extrait le premier objet/tableau JSON d'une réponse LLM (avec ou sans ```)."""
    if not text:
        raise AIAdapterError("Réponse vide")
    fenced = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    candidates = [fenced.group(1)] if fenced else []
    candidates.append(text)
    for chunk in candidates:
        starts = sorted((chunk.find(o), o, c) for o, c in (("{", "}"), ("[", "]")) if chunk.find(o) != -1)
        for start, _, closer in starts:
            end = chunk.rfind(closer)
            if end > start:
                try:
                    return json.loads(chunk[start:end + 1])
                except json.JSONDecodeError:
                    continue
    raise AIAdapterError("Aucun JSON exploitable dans la réponse")
