"""Filtre d'injection de consignes dans les textes externes.

LIMITE ASSUMEE : c'est une heuristique. Elle ne constitue PAS la frontiere de securite.
La frontiere reelle, ce sont les droits de base (un agent ne peut pas approuver, depenser
ou envoyer par lui-meme) et les listes blanches. Le filtre sert a retirer le bruit evident
avant qu'un modele ne lise le texte, et a lever une alerte pour un humain.
"""
from __future__ import annotations

import re

_PATTERNS = [
    ("ignorer_regles", r"\bignor\w*\b.{0,30}\b(r[eè]gles?|instructions?|consignes?|rules?|prompts?)\b"),
    ("nouveau_role", r"\b(tu es maintenant|you are now|d[eé]sormais tu|agis comme)\b"),
    ("mode_privilegie", r"\bmode\s+(admin\w*|root|d[eé]veloppeur|developer|dieu|god)\b"),
    ("approbation_forcee", r"\b(approuve\w*|valide\w*|approve|confirm)\b.{0,40}\b(tout|tous|toutes|ce message|all|everything)\b"),
    ("exfiltration", r"\b(envoie\w*|transmets?|r[eé]v[eè]le\w*|send|reveal|leak)\b.{0,40}\b(rib|iban|mot de passe|password|cl[eé]s?|secrets?|token|system prompt)\b"),
    ("prompt_systeme", r"\bsystem prompt\b|\bprompt syst[eè]me\b"),
    ("sql_ou_shell", r"\b(grant|drop|delete|truncate)\s+(all|table|from|database)\b|\brm\s+-rf\b|\bsudo\b"),
]
_RX = [(n, re.compile(p, re.I | re.S)) for n, p in _PATTERNS]
_SPLIT = re.compile(r"(?<=[.!?;\n])\s+")


def scan(text: str) -> tuple[str, list[dict]]:
    """Retourne (texte nettoye, constats). Les phrases suspectes sont retirees, pas executees."""
    if not text:
        return text, []
    kept, findings = [], []
    for sentence in _SPLIT.split(text):
        hit = next((n for n, rx in _RX if rx.search(sentence)), None)
        if hit:
            findings.append({"rule": hit, "sentence": sentence.strip()[:200]})
        else:
            kept.append(sentence)
    return " ".join(kept).strip(), findings
