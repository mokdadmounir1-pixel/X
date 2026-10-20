"""Fixtures : un vrai PostgreSQL 16 temporaire (cluster jetable) et une base neuve par test."""
from __future__ import annotations
import os, shutil, socket, subprocess, tempfile, uuid
from pathlib import Path
import pytest

PG_BIN = os.environ.get("PG_BIN", "/usr/lib/postgresql/16/bin")


def _free_port() -> int:
    s = socket.socket(); s.bind(("127.0.0.1", 0)); p = s.getsockname()[1]; s.close(); return p


def _as_pg(cmd: list[str], **kw):
    return subprocess.run(["runuser", "-u", "postgres", "--"] + cmd, check=True, capture_output=True, text=True, **kw)


class Cluster:
    def __init__(self):
        base = Path(os.environ.get("NEXUS_TEST_TMP") or tempfile.gettempdir())
        self.dir = Path(tempfile.mkdtemp(prefix="nexus-pg-", dir=base))
        os.chmod(self.dir, 0o755)
        shutil.chown(self.dir, "postgres", "postgres")
        self.port = _free_port()
        self.data = self.dir / "data"
        _as_pg([f"{PG_BIN}/initdb", "-D", str(self.data), "-A", "trust", "-U", "postgres", "-E", "UTF8"])
        self.start()

    def start(self):
        _as_pg([f"{PG_BIN}/pg_ctl", "-D", str(self.data), "-o", f"-p {self.port} -c unix_socket_directories= -c listen_addresses=127.0.0.1",
                "-l", str(self.dir / "pg.log"), "-w", "start"])

    def stop(self):
        _as_pg([f"{PG_BIN}/pg_ctl", "-D", str(self.data), "-m", "fast", "-w", "stop"])

    def url(self, db: str) -> str:
        return f"postgresql://postgres@127.0.0.1:{self.port}/{db}"

    def destroy(self):
        try:
            self.stop()
        except Exception:
            pass
        shutil.rmtree(self.dir, ignore_errors=True)


@pytest.fixture(scope="session")
def cluster():
    c = Cluster()
    yield c
    c.destroy()


@pytest.fixture()
def dburl(cluster):
    import psycopg
    name = "t_" + uuid.uuid4().hex[:10]
    with psycopg.connect(cluster.url("postgres"), autocommit=True) as c:
        c.execute(f'CREATE DATABASE "{name}"')
    return cluster.url(name)


class FakeLLM:
    """Remplace Ollama dans les tests. `reply` peut être une fonction (system, user) -> str."""
    def __init__(self, reply=None, down=False):
        self.reply, self.down, self.calls = reply, down, []

    def chat(self, system, user, json_mode=False):
        from app.errors import LLMUnavailable
        self.calls.append((system, user))
        if self.down:
            raise LLMUnavailable("Ollama indisponible : ConnectError")
        return self.reply(system, user) if self.reply else "ok"


@pytest.fixture()
def fake_llm():
    return FakeLLM


@pytest.fixture()
def env(dburl, cluster):
    from fastapi.testclient import TestClient
    from app.api import create_app
    from app.config import Settings
    from app.db import tx
    from app.migrate import migrate
    from app import audit
    from app.security import hash_password
    migrate(dburl)
    with tx(dburl) as c:
        for name, role in (("fondateur1", "fondateur"), ("operateur1", "operateur"), ("lecteur1", "lecture")):
            c.execute("INSERT INTO users(username,password_hash,role) VALUES (%s,%s,%s)", (name, hash_password("Un-Mot-De-Passe-Solide-1"), role))
    settings = Settings(database_url=dburl, worker_enabled=False, retry_backoff_s=0.0)

    class E:
        pass
    e = E()
    e.url, e.settings, e.cluster = dburl, settings, cluster
    e.llm = FakeLLM()

    def make_client(llm=None):
        app = create_app(settings, llm or e.llm)
        return TestClient(app)
    e.make_client = make_client
    e.client = make_client()

    def login(user, client=None):
        r = (client or e.client).post("/api/auth/login", json={"username": user, "password": "Un-Mot-De-Passe-Solide-1"})
        assert r.status_code == 200, r.text
        return {"Authorization": f"Bearer {r.json()['token']}"}
    e.login = login
    e.F, e.O, e.L = login("fondateur1"), login("operateur1"), login("lecteur1")
    return e
