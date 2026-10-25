"""Adaptateurs LLM : Claude, ChatGPT, Gemini (exclusivement).

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


class GeminiAdapter(LLMAdapter):
    """Gemini via le SDK `google-genai` (clé GEMINI_API_KEY ou GOOGLE_API_KEY)."""

    name = "gemini"

    def __init__(self, cfg: AIConfig) -> None:
        key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
        if not key:
            raise AIAdapterError("GEMINI_API_KEY absent")
        try:
            from google import genai  # type: ignore
        except ImportError as exc:
            raise AIAdapterError("SDK google-genai non installé") from exc
        self._genai = genai
        self._client = genai.Client(api_key=key)
        self._model = cfg.gemini_model

    def complete(self, prompt: str, system: Optional[str] = None) -> str:
        try:
            config = self._genai.types.GenerateContentConfig(system_instruction=system) if system else None
            resp = self._client.models.generate_content(model=self._model, contents=prompt, config=config)
            return resp.text or ""
        except Exception as exc:
            raise AIAdapterError(f"Gemini a échoué : {exc}") from exc


def build_adapters(cfg: AIConfig) -> dict[str, LLMAdapter]:
    adapters: dict[str, LLMAdapter] = {}
    for klass in (ClaudeAdapter, ChatGPTAdapter, GeminiAdapter):
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
