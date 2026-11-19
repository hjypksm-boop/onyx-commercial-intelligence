"""Database access helpers (SQLAlchemy Core, raw parameterised SQL)."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import pandas as pd
from sqlalchemy import bindparam, create_engine, event, text
from sqlalchemy.engine import Engine

from services import config, dialect


@lru_cache(maxsize=16)
def get_engine(url: str) -> Engine:
    if url.startswith("sqlite"):
        Path(url.replace("sqlite:///", "")).parent.mkdir(parents=True, exist_ok=True)
        eng = create_engine(url, connect_args={"check_same_thread": False, "timeout": 30})

        @event.listens_for(eng, "connect")
        def _fk_on(dbapi_conn, _):  # pragma: no cover - trivial
            cur = dbapi_conn.cursor()
            cur.execute("PRAGMA foreign_keys=ON")
            cur.close()

        return eng
    return create_engine(url, pool_pre_ping=True)


def dispose(url: str) -> None:
    """Close pooled connections (needed before replacing a SQLite file)."""
    try:
        get_engine(url).dispose()
    except Exception:  # pragma: no cover
        pass


def dialect_name(engine: Engine) -> str:
    return engine.dialect.name


def read_sql_file(rel: str) -> str:
    return (config.SQL_DIR / rel).read_text()


def render_sql(engine: Engine, sql: str, param_as_of: bool = False) -> str:
    return dialect.render(sql, dialect_name(engine), param_as_of)


def load_query(engine: Engine, name: str, param_as_of: bool = False) -> str:
    """Load sql/queries/<name>.sql (comment lines stripped) rendered for this engine."""
    body = "\n".join(ln for ln in read_sql_file(f"queries/{name}.sql").splitlines() if not ln.strip().startswith("--"))
    return render_sql(engine, body.strip().rstrip(";"), param_as_of)


def query_text(name: str) -> str:
    """Raw (unrendered) SQL of a query file — used by 'Show SQL' expanders."""
    return read_sql_file(f"queries/{name}.sql")


def _prepare(sql: str, params: dict | None):
    stmt = text(sql)
    params = dict(params or {})
    expanding = [k for k, v in params.items() if isinstance(v, (list, tuple, set))]
    for k in expanding:
        params[k] = list(params[k]) or ["__none__"]
        stmt = stmt.bindparams(bindparam(k, expanding=True))
    return stmt, params


def query_df(engine: Engine, sql: str, params: dict | None = None) -> pd.DataFrame:
    stmt, params = _prepare(sql, params)
    with engine.connect() as conn:
        res = conn.execute(stmt, params)
        rows = res.fetchall()
        return pd.DataFrame(rows, columns=list(res.keys()))


def query_one(engine: Engine, sql: str, params: dict | None = None) -> dict | None:
    stmt, params = _prepare(sql, params)
    with engine.connect() as conn:
        row = conn.execute(stmt, params).mappings().first()
        return dict(row) if row else None


def scalar(engine: Engine, sql: str, params: dict | None = None) -> Any:
    stmt, params = _prepare(sql, params)
    with engine.connect() as conn:
        return conn.execute(stmt, params).scalar()


def execute(conn, sql: str, params: dict | None = None):
    stmt, params = _prepare(sql, params)
    return conn.execute(stmt, params)


def insert_returning_id(conn, sql: str, params: dict) -> int:
    """sql must end with RETURNING <id column> (supported by SQLite ≥3.35 and PostgreSQL)."""
    return int(execute(conn, sql, params).scalar())


def _resolve_includes(sql: str) -> str:
    import re

    def repl(m):
        body = read_sql_file(m.group(1))
        body = "\n".join(ln for ln in body.splitlines() if not ln.strip().startswith("--"))
        return body.strip().rstrip(";")

    return re.sub(r"@INCLUDE\(([^)]+)\)", repl, sql)


def run_script(engine: Engine, rel_path: str) -> None:
    sql = render_sql(engine, _resolve_includes(read_sql_file(rel_path)))
    with engine.begin() as conn:
        for stmt in dialect.split_statements(sql):
            conn.execute(text(stmt))


def as_of(engine: Engine) -> str:
    return scalar(engine, "SELECT value FROM app_config WHERE key = 'as_of_date'")


def table_exists(engine: Engine, name: str) -> bool:
    from sqlalchemy import inspect

    return inspect(engine).has_table(name)
