"""Engine and session factory for the casefile SQLite database."""

from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import Engine
from sqlmodel import Session, SQLModel, create_engine

import packages.db.listeners  # noqa: F401  registers eligibility-enforcing event listeners
import packages.db.models  # noqa: F401  registers tables on SQLModel.metadata

DEFAULT_DB_PATH = "data/casefile.db"

_engine: Engine | None = None


def get_engine() -> Engine:
    global _engine
    if _engine is None:
        db_path = os.environ.get("CASEFILE_DB_PATH", DEFAULT_DB_PATH)
        _engine = create_engine(f"sqlite:///{db_path}")
    return _engine


def create_all() -> None:
    SQLModel.metadata.create_all(get_engine())


def get_session() -> Session:
    return Session(get_engine())


@contextmanager
def session_scope() -> Iterator[Session]:
    session = get_session()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
