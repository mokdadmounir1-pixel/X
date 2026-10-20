from __future__ import annotations
import hashlib, json


def canonical(obj) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)


def sha256_hex(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def params_hash(kind: str, params: dict) -> str:
    """Empreinte d'une action : type + paramètres. Sert aux approbations."""
    return sha256_hex(canonical({"kind": kind, "params": params}))
