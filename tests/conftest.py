from __future__ import annotations

from collections.abc import Iterator

import pytest
from sqlmodel import Session, SQLModel, create_engine

import packages.db.listeners  # noqa: F401  registers eligibility-enforcing event listeners
import packages.db.models  # noqa: F401  registers tables on SQLModel.metadata


@pytest.fixture()
def session() -> Iterator[Session]:
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    with Session(engine) as sess:
        yield sess
    engine.dispose()
