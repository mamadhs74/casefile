"""Insert the film-tv-news Strategy row into data/casefile.db.

Tier 2: this writes to data/casefile.db. Written but not run -- see
CLAUDE.md's Tier 2 rule and the task this was built under.

Idempotent the same way scripts/seed_dev.py's own Strategy insert is: if a
row with this slug already exists, this leaves it alone and reports the
existing row rather than inserting a second one or overwriting field
values a human may have already edited.

description, unlike every other field here, was not specified in the
task that produced this script -- the rest (name, subject noun,
min_verified_sources/min_primary_records/min_distinct_domains, style
guide tone/forbidden list, allowed archives) came verbatim from that
task. This one line is this script's own addition, written to match
criminal-cases' Strategy.description in tone; check it before running.

Usage (module form -- `packages` isn't importable when this file is run as
a bare script path, since this project isn't installed as a package; see
docs/SCHEMA.md):
    uv run python -m scripts.seed_film_tv_strategy
"""

from __future__ import annotations

from sqlmodel import select

from packages.db.models import Strategy
from packages.db.session import create_all, get_session
from packages.domain.enums import ArchiveProvider

SLUG = "film-tv-news"


def seed() -> None:
    create_all()
    with get_session() as session:
        existing = session.exec(select(Strategy).where(Strategy.slug == SLUG)).first()
        if existing is not None:
            print(f"strategy {SLUG!r} already exists (id={existing.id}) -- not reinserting.")
            return

        strategy = Strategy(
            slug=SLUG,
            name="Film and TV News",
            description=(
                "Weekly film and TV industry news, sourced across independent "
                "trade and business outlets."
            ),
            subject_noun_singular="topic",
            subject_noun_plural="topics",
            min_verified_sources=3,
            min_primary_records=1,
            min_distinct_domains=3,
            style_guide={
                "tone": "factual, industry-analytical",
                "forbidden": [
                    "unsourced casting rumors",
                    "box office projections presented as fact",
                    "personal-life or relationship gossip",
                    "claims about any individual's private conduct",
                    "\"you won't believe\" hooks",
                    "speculation about unannounced projects presented as reporting",
                ],
            },
            allowed_archive_providers=[
                ArchiveProvider.WIKIMEDIA_COMMONS,
                ArchiveProvider.PEXELS,
                ArchiveProvider.PIXABAY,
            ],
        )
        session.add(strategy)
        session.commit()
        session.refresh(strategy)
        print(f"inserted strategy {SLUG!r} (id={strategy.id})")


if __name__ == "__main__":
    seed()
