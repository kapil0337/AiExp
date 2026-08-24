"""SQLAlchemy engine/session wiring.

Works in three places with the same code:
  * local venv  -> SQLite file under ./data
  * docker      -> Postgres service
  * Vercel      -> Postgres (Neon/Supabase/Vercel Postgres), pooled per-invocation
"""

from __future__ import annotations

import os
import threading
from collections.abc import Iterator

from sqlalchemy import create_engine, event, inspect
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from sqlalchemy.pool import NullPool

from .config import DATA_DIR, get_settings


class Base(DeclarativeBase):
    pass


def _normalise(url: str) -> str:
    """Accept the shapes hosting providers hand out."""
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql+psycopg://", 1)
    elif url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+psycopg://", 1)
    return url


def _build_engine() -> Engine:
    url = _normalise(get_settings().database_url)

    if url.startswith("sqlite"):
        # On Vercel the filesystem is read-only and per-invocation, so SQLite
        # would either crash on mkdir or silently lose every write. Fail loudly
        # with the actual fix instead.
        if os.getenv("VERCEL"):
            raise RuntimeError(
                "DATABASE_URL is unset or points at SQLite, but this is running "
                "on Vercel, where the filesystem is read-only and thrown away "
                "after each request. Set DATABASE_URL to a hosted Postgres URL "
                "(Neon / Supabase / Vercel Postgres) in Project → Settings → "
                "Environment Variables."
            )
        try:
            DATA_DIR.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise RuntimeError(
                f"Could not create the SQLite data directory {DATA_DIR}: {exc}. "
                "Point DATABASE_URL at a writable location or a Postgres server."
            ) from exc

        engine = create_engine(
            url, connect_args={"check_same_thread": False}, future=True
        )

        @event.listens_for(engine, "connect")
        def _fk_on(dbapi_conn, _record):  # pragma: no cover - trivial
            cur = dbapi_conn.cursor()
            cur.execute("PRAGMA foreign_keys=ON")
            cur.close()

        return engine

    # Serverless: every invocation is a fresh container, so pooling across
    # them is a liability, not a win. NullPool + pre_ping keeps it honest.
    return create_engine(url, poolclass=NullPool, pool_pre_ping=True, future=True)


engine = _build_engine()
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

_init_lock = threading.Lock()
_initialised = False


def init_db() -> None:
    """Create tables once per process (cheap no-op afterwards)."""
    global _initialised
    if _initialised:
        return
    with _init_lock:
        if _initialised:
            return
        from . import models  # noqa: F401  (registers mappers)

        try:
            Base.metadata.create_all(bind=engine)
        except Exception:
            # Two serverless cold starts can race to CREATE TABLE. If the
            # tables are there now, the other invocation won and we're fine.
            if not inspect(engine).has_table("budgets"):
                raise
        _assert_schema_current()
        _initialised = True


def _assert_schema_current() -> None:
    """Fail fast when the models have columns the database doesn't.

    create_all() creates missing *tables* but never adds *columns* to tables
    that already exist. Without this check, adding a field to a model turns
    every request against an older database into an opaque 500.
    """
    insp = inspect(engine)
    drift = []
    for table in Base.metadata.sorted_tables:
        if not insp.has_table(table.name):
            continue
        present = {c["name"] for c in insp.get_columns(table.name)}
        missing = sorted({c.name for c in table.columns} - present)
        if missing:
            drift.append(f"{table.name} is missing {missing}")
    if drift:
        raise RuntimeError(
            "Database schema is out of date — " + "; ".join(drift) + ". "
            "create_all() cannot add columns to existing tables. Either "
            "recreate the database (locally: `docker compose down -v && "
            "docker compose up`, or delete data/bloom.db) or add the columns "
            "with a migration."
        )


def get_db() -> Iterator[Session]:
    init_db()
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
