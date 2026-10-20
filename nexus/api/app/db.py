from __future__ import annotations
from contextlib import contextmanager
import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb


def connect(url: str) -> psycopg.Connection:
    return psycopg.connect(url, row_factory=dict_row, autocommit=False)


@contextmanager
def tx(url: str):
    """Une transaction : commit à la sortie, rollback sur exception."""
    conn = connect(url)
    try:
        yield conn
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    finally:
        conn.close()


def J(value) -> Jsonb:
    return Jsonb(value)
