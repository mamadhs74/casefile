"""Source.domain must be derived at the persistence layer, not by caller discipline.

Mirrors tests/test_subject_persistence.py: hand-set a wrong domain, confirm the
before_insert/before_update listener on Source (packages/db/listeners.py)
overwrites it from url regardless -- including calls that go straight through
a session, bypassing the API's SourceCreate schema entirely.
"""

from __future__ import annotations

from sqlmodel import Session

from packages.db.models import Source
from tests.factories import make_source, make_subject


def _persist_subject_id(session: Session, strategy_id: int) -> int:
    subject = make_subject(strategy_id)
    session.add(subject)
    session.commit()
    session.refresh(subject)
    assert subject.id is not None
    return subject.id


def test_domain_is_derived_from_url_bypassing_the_api(session: Session, strategy_id: int) -> None:
    subject_id = _persist_subject_id(session, strategy_id)
    source = make_source(subject_id, url="https://WWW.BBC.co.uk/news/some-article")
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


def test_domain_recomputes_on_update_when_url_changes(
    session: Session, strategy_id: int
) -> None:
    subject_id = _persist_subject_id(session, strategy_id)
    source = make_source(subject_id, url="https://example.com/first")
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
