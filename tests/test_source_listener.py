"""Source.domain must be derived at the persistence layer, not by caller discipline.

Mirrors tests/test_case_persistence.py: hand-set a wrong domain, confirm the
before_insert/before_update listener on Source (packages/db/listeners.py)
overwrites it from url regardless -- including calls that go straight through
a session, bypassing the API's SourceCreate schema entirely.
"""

from __future__ import annotations

from sqlmodel import Session

from packages.db.models import Source
from tests.factories import make_case, make_source


def _persist_case_id(session: Session) -> int:
    case = make_case()
    session.add(case)
    session.commit()
    session.refresh(case)
    assert case.id is not None
    return case.id


def test_domain_is_derived_from_url_bypassing_the_api(session: Session) -> None:
    case_id = _persist_case_id(session)
    source = make_source(case_id, url="https://WWW.BBC.co.uk/news/some-article")
    source.domain = "deliberately-wrong.example"  # caller-set value must not survive

    session.add(source)
    session.commit()
    source_id = source.id
    assert source_id is not None

    engine = session.get_bind()
    session.close()

    with Session(engine) as fresh_session:
        reloaded = fresh_session.get(Source, source_id)
        assert reloaded is not None
        assert reloaded.domain == "bbc.co.uk"


def test_domain_recomputes_on_update_when_url_changes(session: Session) -> None:
    case_id = _persist_case_id(session)
    source = make_source(case_id, url="https://example.com/first")
    session.add(source)
    session.commit()
    assert source.domain == "example.com"

    source.url = "https://www.nytimes.com/second"
    source.domain = "still-wrong.example"
    session.add(source)
    session.commit()
    source_id = source.id

    engine = session.get_bind()
    session.close()

    with Session(engine) as fresh_session:
        reloaded = fresh_session.get(Source, source_id)
        assert reloaded is not None
        assert reloaded.domain == "nytimes.com"
