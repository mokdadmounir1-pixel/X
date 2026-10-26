"""Orchestrateur IA : routage par rôle, repli entre modèles, sorties JSON bornées.

Rôles (d'après l'architecture) :
  reasoning  -> Claude   : analyse des échecs, hypothèses d'amélioration
  validation -> ChatGPT  : relecture critique (Research Reviewer)
  automation -> Claude   : routage des tâches d'automatisation et leçons du journal (ChatGPT en repli) ; l'exécution locale sur le PC est faite par ChatGPT hors de cette boucle
Les IA sont consultatives : elles ne contournent jamais la validation (lab/) ni le RiskManager.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Optional

from ..config import Settings
from ..exceptions import AIAdapterError
from ..improvement.diagnosis import PARAM_SPACE, Failure, Hypothesis, sanitize_overrides
from ..logging_utils import get_logger
from ..signals.engine import Signal
from .adapters import LLMAdapter, extract_json

log = get_logger("ai.orchestrator")

ROUTING: dict[str, list[str]] = {
    "reasoning": ["claude", "chatgpt"],
    "validation": ["chatgpt", "claude"],
    "automation": ["claude", "chatgpt"],
}
_SYSTEM = ("You are a rigorous quantitative trading researcher. Reply ONLY with valid JSON. "
           "Never propose code; only parameter changes from the allowed list.")


@dataclass
class Review:
    verdict: str  # agree | veto | neutral
    reason: str
    source: str = ""


class AIOrchestrator:
    def __init__(self, adapters: dict[str, LLMAdapter], settings: Settings) -> None:
        self.adapters = adapters
        self.settings = settings

    @property
    def available(self) -> bool:
        return bool(self.adapters)

    def ask_json(self, role: str, prompt: str) -> tuple[Any, str]:
        """Essaie les modèles du rôle dans l'ordre ; lève AIAdapterError si tous échouent."""
        errors = []
        for name in ROUTING[role]:
            adapter = self.adapters.get(name)
            if adapter is None:
                continue
            try:
                return extract_json(adapter.complete(prompt, _SYSTEM)), name
            except AIAdapterError as exc:
                errors.append(f"{name}: {exc}")
                log.warning("Rôle %s : %s", role, exc)
        raise AIAdapterError("Aucun modèle n'a répondu : " + " | ".join(errors) if errors
                             else "Aucun adaptateur IA configuré")

    def propose_hypotheses(self, failures: list[Failure], settings: Settings, failed_before: list[dict],
                           lessons: Optional[list[str]] = None,
                           pattern_stats: Optional[list[dict]] = None) -> list[Hypothesis]:
        allowed = {k: (v if isinstance(v, list) else {"min": v[0], "max": v[1], "step": v[2]})
                   for k, v in PARAM_SPACE.items()}
        current = {k: getattr(getattr(settings, k.split(".")[0]), k.split(".")[1]) for k in PARAM_SPACE}
        prompt = json.dumps({
            "task": "Propose up to 3 hypotheses to fix the observed failures. Each hypothesis changes at most 3 "
                    "parameters. Do not repeat rejected changes.",
            "failures": [{"kind": f.kind, "severity": round(f.severity, 2), "evidence": f.evidence} for f in failures],
            "current_parameters": current,
            "allowed_parameters": allowed,
            "journal_lessons": (lessons or [])[-20:],
            "setup_performance": pattern_stats or [],
            "rejected_before": [{"change": r["change"], "overrides": r["overrides"]} for r in failed_before[-10:]],
            "output_format": [{"description": "str", "overrides": {"section.key": "value"}}],
        }, default=str)
        data, source = self.ask_json("reasoning", prompt)
        items = data if isinstance(data, list) else data.get("hypotheses", []) if isinstance(data, dict) else []
        out = []
        for item in items[:3]:
            if not isinstance(item, dict):
                continue
            clean = sanitize_overrides(item.get("overrides"))
            if clean:
                out.append(Hypothesis(str(item.get("description", "idée IA"))[:200], clean, f"ai:{source}"))
        return out

    def review(self, subject: dict, role: str = "validation") -> Review:
        """Relecture critique ; toute erreur -> verdict neutre (jamais bloquant)."""
        prompt = json.dumps({"task": "Review for flaws (look-ahead, overfitting, cost blindness).",
                             "subject": subject,
                             "output_format": {"verdict": "agree|veto|neutral", "reason": "str"}}, default=str)
        try:
            data, source = self.ask_json(role, prompt)
            verdict = str(data.get("verdict", "neutral")).lower() if isinstance(data, dict) else "neutral"
            if verdict not in {"agree", "veto", "neutral"}:
                verdict = "neutral"
            return Review(verdict, str(data.get("reason", ""))[:300] if isinstance(data, dict) else "", source)
        except AIAdapterError as exc:
            return Review("neutral", f"IA indisponible : {exc}")

    def lesson(self, trade: dict) -> Optional[str]:
        """Leçon d'une phrase tirée d'un trade clôturé (Claude en priorité) ; None si IA indisponible."""
        prompt = json.dumps({"task": "Write ONE short lesson a trader would note in their journal about this closed "
                                     "trade (setup quality, exit, context). No advice to change risk.",
                             "trade": trade, "output_format": {"lesson": "str"}}, default=str)
        try:
            data, _ = self.ask_json("automation", prompt)
        except AIAdapterError:
            return None
        text = data.get("lesson") if isinstance(data, dict) else None
        return str(text)[:300] if text else None

    def review_signal(self, signal: Signal) -> Review:
        return self.review({"direction": signal.direction, "confidence": round(signal.confidence, 3),
                            "patterns": [{"name": m.name, "score": round(m.score, 2), "confirmed": m.confirmed}
                                         for m in signal.matches], "notes": signal.notes})

    def filter_signal(self, signal: Optional[Signal]) -> Optional[Signal]:
        """Veto optionnel (ai.veto_enabled) ; par défaut le signal passe tel quel."""
        if signal is None or not (self.settings.ai.enabled and self.settings.ai.veto_enabled):
            return signal
        review = self.review_signal(signal)
        if review.verdict == "veto":
            log.info("Signal vetoé par %s : %s", review.source, review.reason)
            return None
        return signal
