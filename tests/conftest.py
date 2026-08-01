from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

import packages.db.listeners  # noqa: F401  registers eligibility-enforcing event listeners
import packages.db.models  # noqa: F401  registers tables on SQLModel.metadata
from apps.api.deps import get_session
from apps.api.main import create_app
from tests.factories import make_strategy


@pytest.fixture()
def session() -> Iterator[Session]:
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    with Session(engine) as sess:
        yield sess
    engine.dispose()


@pytest.fixture()
def strategy_id(session: Session) -> int:
    """A persisted criminal-cases Strategy row -- the slug matches what
    packages/strategies/criminal_cases actually registers, so tests exercise
    the real dispatch path rather than a stand-in."""
    strategy = make_strategy()
    session.add(strategy)
    session.commit()
    session.refresh(strategy)
    assert strategy.id is not None
    return strategy.id


@pytest.fixture()
def client(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    monkeypatch.setenv("CASEFILE_DB_PATH", ":memory:")

    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)

    with Session(engine) as seed_session:
        seed_session.add(make_strategy())
        seed_session.commit()

    def _override_get_session() -> Iterator[Session]:
        with Session(engine) as session:
            yield session

    app = create_app()
    app.dependency_overrides[get_session] = _override_get_session

    with TestClient(app) as test_client:
        yield test_client

    engine.dispose()
