from __future__ import annotations

import os
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

import packages.db.listeners  # noqa: F401  registers eligibility-enforcing event listeners
import packages.db.models  # noqa: F401  registers tables on SQLModel.metadata
import packages.db.session
from apps.api.deps import get_session
from apps.api.main import create_app
from tests.factories import make_strategy


@pytest.fixture(scope="session", autouse=True)
def _guard_real_database() -> Iterator[None]:
    """packages.db.session.get_session()/get_engine() is a process-global
    singleton (packages/db/session.py's own module-level `_engine`) that
    defaults to the REAL on-disk data/casefile.db unless CASEFILE_DB_PATH
    is set -- confirmed the hard way while testing scripts/create_episode.py
    (docs/HANDOFF.md): an unpatched test silently queried a different
    database than the one it had populated, because it was talking to the
    real file instead of the test's own in-memory one.

    Session-scoped and autouse, not per-test: `_engine` is itself
    process-global, so a per-test fixture couldn't meaningfully reset it
    between tests anyway, and this must apply before ANY test's first call
    to get_session(), from any test file -- not just the one that found
    the problem.

    Patches get_engine, not get_session, and that choice is load-bearing,
    not stylistic: get_session()'s own body calls get_engine() as a bare
    name, which Python resolves against get_session's DEFINING module's
    globals (packages.db.session.__dict__) at call time -- not against
    whatever module happens to have imported get_session by name (and
    scripts/create_episode.py, scripts/run_episode.py,
    scripts/tag_sections.py, packages/research/gate.py, and others all do
    exactly that). Patching packages.db.session.get_engine here is
    therefore effective for every one of those call sites automatically,
    confirmed empirically (not assumed) by monkeypatching get_engine and
    calling get_session() via a name imported into a different module.

    Forces a single, shared, in-memory engine for the whole test session
    rather than merely raising unconditionally -- a test that calls
    get_session() and expects it to actually work still gets a real,
    working database, just never the real file. tests/test_create_episode.py
    needs its own ISOLATED database (shared with its own `session` fixture,
    not this session-wide one) and monkeypatches get_session locally on
    scripts.create_episode itself for that reason -- a local monkeypatch on
    the importing module's own name binding takes precedence over this
    fixture's patch on get_engine, since that call site never reaches
    packages.db.session.get_session() at all once overridden.

    The RuntimeError below is defense in depth, not the primary mechanism:
    CASEFILE_DB_PATH is forced to ":memory:" for the whole session, so the
    real path is never resolved in ordinary operation -- but a test that
    unsets or overrides that env var (deliberately or by accident) still
    gets a loud failure instead of a silent write to production data.
    """
    test_engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(test_engine)

    def _guarded_get_engine() -> Engine:
        db_path = os.environ.get("CASEFILE_DB_PATH", packages.db.session.DEFAULT_DB_PATH)
        if db_path == packages.db.session.DEFAULT_DB_PATH:
            raise RuntimeError(
                f"packages.db.session.get_engine() would open the real "
                f"{packages.db.session.DEFAULT_DB_PATH!r} during a test run. "
                f"Set CASEFILE_DB_PATH, or monkeypatch get_session locally "
                f"on the importing module, instead."
            )
        return test_engine

    mp = pytest.MonkeyPatch()
    mp.setenv("CASEFILE_DB_PATH", ":memory:")
    mp.setattr(packages.db.session, "get_engine", _guarded_get_engine)
    yield
    mp.undo()


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
