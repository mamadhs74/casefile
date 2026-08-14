"""Insert one film-tv-news Subject into data/casefile.db.

Tier 2: this writes to data/casefile.db. Written and run only after
explicit confirmation -- see CLAUDE.md's Tier 2 rule and the task this
was built under.

Idempotent on title: scripts/seed_film_tv_strategy.py checks slug
instead, because slug carries the real uniqueness constraint on
Strategy -- Subject.slug is also unique, but this checks title
directly, per the task this was built under.

resolution_status=OFFICIALLY_RULED is an inert placeholder, not a real
answer -- see docs/HANDOFF.md finding #33. film-tv-news's own scorer
reads nothing from this field.

monetization_tier, legal_risk, and eligibility_notes are not set here:
packages/db/listeners.py's before_insert listener recomputes all three
from film-tv-news's real scorer unconditionally, the same guarantee
every Subject write gets.

Usage (module form -- `packages` isn't importable when this file is run as
a bare script path, since this project isn't installed as a package; see
docs/SCHEMA.md):
    uv run python -m scripts.seed_film_tv_subject
"""

from __future__ import annotations

import sys

from sqlmodel import select

from packages.db.models import Strategy, Subject
from packages.db.session import create_all, get_session
from packages.domain.enums import ResolutionStatus
from packages.strategies.film_tv_news import SLUG as FILM_TV_NEWS_SLUG
from packages.strategies.film_tv_news.enums import TopicType

TITLE = "Hollywood consolidation and the record summer, August 2026"


def seed() -> int:
    create_all()
    with get_session() as session:
        existing = session.exec(select(Subject).where(Subject.title == TITLE)).first()
        if existing is not None:
            print(f"subject {TITLE!r} already exists (id={existing.id}) -- not reinserting.")
            return 0

        strategy = session.exec(select(Strategy).where(Strategy.slug == FILM_TV_NEWS_SLUG)).first()
        if strategy is None:
            print(
                f"no strategy with slug={FILM_TV_NEWS_SLUG!r} -- run seed_film_tv_strategy first.",
                file=sys.stderr,
            )
            return 1
        assert strategy.id is not None

        subject = Subject(
            strategy_id=strategy.id,
            slug="2026-08-hollywood-consolidation-record-summer",
            title=TITLE,
            event_year=2026,
            country="United States",
            summary=(
                "Weekly film-and-TV-industry digest covering consolidation, box "
                "office, and earnings coverage across trade press for August 2026."
            ),
            resolution_status=ResolutionStatus.OFFICIALLY_RULED,
            living_persons_involved=True,
            attributes={"topic_type": TopicType.INDUSTRY_BUSINESS.value},
        )
        session.add(subject)
        session.commit()
        session.refresh(subject)
        print(f"inserted subject {TITLE!r} (id={subject.id})")
        return 0


if __name__ == "__main__":
    sys.exit(seed())
