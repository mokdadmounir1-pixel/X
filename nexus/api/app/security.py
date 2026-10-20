from __future__ import annotations
import base64, hashlib, hmac, os, re, secrets, time
from dataclasses import dataclass
from .errors import Forbidden, Invalid, Unauthorized

ROLES = ("lecture", "operateur", "fondateur")
RANK = {r: i for i, r in enumerate(ROLES)}
_WEAK = {"password", "motdepasse", "changeme", "123456789012", "administrator", "nexus", "azerty", "qwerty"}


def check_password_policy(username: str, password: str) -> None:
    if len(password) < 12:
        raise Invalid("Mot de passe : 12 caractères minimum")
    low = password.lower()
    if low == username.lower() or any(w in low for w in _WEAK) or len(set(password)) < 5:
        raise Invalid("Mot de passe trop faible")


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    n, r, p = 2 ** 14, 8, 1
    h = hashlib.scrypt(password.encode(), salt=salt, n=n, r=r, p=p, dklen=32)
    return f"scrypt${n}${r}${p}${base64.b64encode(salt).decode()}${base64.b64encode(h).decode()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        _, n, r, p, salt, h = stored.split("$")
        calc = hashlib.scrypt(password.encode(), salt=base64.b64decode(salt), n=int(n), r=int(r), p=int(p), dklen=32)
        return hmac.compare_digest(calc, base64.b64decode(h))
    except Exception:
        return False


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def new_token() -> str:
    return secrets.token_urlsafe(32)


@dataclass(frozen=True)
class Principal:
    user_id: str
    username: str
    role: str

    def require(self, minimum: str) -> None:
        if RANK[self.role] < RANK[minimum]:
            raise Forbidden(f"Rôle {self.role} insuffisant : {minimum} requis")


def principal_from_token(conn, token: str | None) -> Principal:
    if not token:
        raise Unauthorized("Jeton absent")
    row = conn.execute(
        """SELECT u.id, u.username, u.role FROM sessions s JOIN users u ON u.id = s.user_id
           WHERE s.token_hash = %s AND NOT s.revoked AND s.expires_at > now() AND u.active""",
        (token_hash(token),)).fetchone()
    if not row:
        raise Unauthorized("Session invalide ou expirée")
    return Principal(str(row["id"]), row["username"], row["role"])


class LoginThrottle:
    """Limite en mémoire : 5 échecs → blocage de 60 s par nom d'utilisateur."""
    def __init__(self, limit=5, window=60.0):
        self.limit, self.window, self.fails = limit, window, {}

    def check(self, username: str) -> None:
        now = time.monotonic()
        recent = [t for t in self.fails.get(username, []) if now - t < self.window]
        self.fails[username] = recent
        if len(recent) >= self.limit:
            raise Forbidden("Trop d'échecs : réessayer dans une minute", code="login_throttled")

    def fail(self, username: str) -> None:
        self.fails.setdefault(username, []).append(time.monotonic())


class RedactFilter:
    """Filtre de journalisation : masque jetons, mots de passe et URL de base de données."""
    import logging as _l
    PATTERNS = [
        (re.compile(r"(?i)(bearer\s+)[A-Za-z0-9_\-\.]{16,}"), r"\1[REDACTED]"),
        (re.compile(r"(?i)(password|passwd|secret|token)(['\"]?\s*[:=]\s*['\"]?)[^\s'\",}]+"), r"\1\2[REDACTED]"),
        (re.compile(r"(postgres(?:ql)?://[^:/\s]+:)[^@\s]+(@)"), r"\1[REDACTED]\2"),
    ]

    @classmethod
    def redact(cls, text: str) -> str:
        for rx, rep in cls.PATTERNS:
            text = rx.sub(rep, text)
        return text

    def filter(self, record) -> bool:
        record.msg = self.redact(record.getMessage())
        record.args = ()
        return True
