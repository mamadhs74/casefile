"""Recompute tier for film-tv-news Source rows fetched before
assign_initial_tier became strategy-aware (packages/research/tiering.py).

Tier 2: this writes to data/casefile.db. Written and run only after
explicit confirmation -- see CLAUDE.md's Tier 2 rule and the task this
was built under.

Does not re-fetch or re-extract -- only recomputes tier from the URL
already stored on each row, via the same assign_initial_tier() the live
fetch path calls, and writes it back only where it changed. Uses the
normal SQLModel session, unlike scripts/migrate_*.py: those drop to raw
sqlite3 because the live table doesn't match the model yet at that point;
here the schema is unchanged, only a value needs recomputing.

Scope is every Source whose Subject belongs to the film-tv-news
strategy, not a hardcoded pair of source ids -- source 12 (variety.com)
and 13 (hollywoodreporter.com) on subject 10 are the two known stale
rows this was built for, but the fix is "recompute what's stale," not
"fix these two ids." Rerunning this script is a no-op past the first
time: nothing is written for a row whose recomputed tier already
matches what's stored.

Safety:
1. Refuses to run unless data/casefile.db.bak already exists -- this
   script does not make its own backup.
2. Only Source rows under a film-tv-news Subject are read or written;
   every other strategy's sources are untouched.
3. Snapshots every touched row before the update and asserts, after
   commit, that every column except tier is byte-identical to its
   snapshot -- not just "no schema violation," a direct check that
   nothing besides tier moved. updated_at is included in that check:
   no listener bumps it on update (confirmed against
   packages/db/listeners.py), so it isn't expected to change either.
4. PRAGMA foreign_key_check after commit.
5. Prints every film-tv-news source considered (changed or not), then
   every source row for subject 10 specifically, in full.

Usage (module form -- `packages` isn't importable when this file is run as
a bare script path, since this project isn't installed as a package; see
docs/SCHEMA.md):
    uv run python -m scripts.retier_stale_film_tv_sources
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import text
from sqlmodel import Session, col, select

from packages.db.models import Source, Strategy, Subject
from packages.db.session import get_session
from packages.research.tiering import assign_initial_tier
from packages.strategies.film_tv_news import SLUG as FILM_TV_NEWS_SLUG

BACKUP_PATH = Path("data/casefile.db.bak")

SUBJECT_ID_TO_PRINT = 10  # the subject this was built for; print-only, not a filter on the update


@dataclass(frozen=True)
class _Snapshot:
    id: int
    subject_id: int
    url: str
    domain: str
    publisher: str
    title: str
    tier: str
    text_path: str
    text_sha256: str
    word_count: int
    updated_at: object


def _snapshot(source: Source) -> _Snapshot:
    assert source.id is not None
    return _Snapshot(
        id=source.id,
        subject_id=source.subject_id,
        url=source.url,
        domain=source.domain,
        publisher=source.publisher,
        title=source.title,
        tier=source.tier.value,
        text_path=source.text_path,
        text_sha256=source.text_sha256,
        word_count=source.word_count,
        updated_at=source.updated_at,
    )


def _require_backup() -> None:
    if not BACKUP_PATH.exists():
        print(
            f"refusing to run: {BACKUP_PATH} does not exist. "
            f"This script does not make its own backup -- copy "
            f"data/casefile.db to {BACKUP_PATH} first.",
            file=sys.stderr,
        )
        raise SystemExit(1)
    print(f"backup present: {BACKUP_PATH} ({BACKUP_PATH.stat().st_size} bytes)")


def _film_tv_news_sources(session: Session) -> list[Source]:
    return list(
        session.exec(
            select(Source)
            .join(Subject, Subject.id == Source.subject_id)  # type: ignore[arg-type]
            .join(Strategy, Strategy.id == Subject.strategy_id)  # type: ignore[arg-type]
            .where(Strategy.slug == FILM_TV_NEWS_SLUG)
            .order_by(col(Source.id))
        )
    )


def retier() -> int:
    _require_backup()

    with get_session() as session:
        sources = _film_tv_news_sources(session)
        print(f"{len(sources)} film-tv-news source row(s) found")

        before: dict[int, _Snapshot] = {}
        changed_ids: list[int] = []

        for source in sources:
            assert source.id is not None
            before[source.id] = _snapshot(source)

            new_tier = assign_initial_tier(source.url, FILM_TV_NEWS_SLUG)
            if new_tier == source.tier:
                print(f"  source {source.id} ({source.domain}): {source.tier.value} -- unchanged")
                continue

            print(
                f"  source {source.id} ({source.domain}): "
                f"{source.tier.value} -> {new_tier.value}"
            )
            source.tier = new_tier
            session.add(source)
            changed_ids.append(source.id)

        if not changed_ids:
            print("nothing to update")
            return 0

        session.commit()

        violations = session.execute(text("PRAGMA foreign_key_check")).all()
        if violations:
            print(f"foreign_key_check FAILED: {violations}", file=sys.stderr)
            return 1
        print("foreign_key_check: clean")

        for source_id in changed_ids:
            updated_source = session.get(Source, source_id)
            assert updated_source is not None
            after = _snapshot(updated_source)
            expected = before[source_id]
            for field_name in _Snapshot.__dataclass_fields__:
                if field_name in ("id", "tier"):
                    continue
                before_value = getattr(expected, field_name)
                after_value = getattr(after, field_name)
                if before_value != after_value:
                    print(
                        f"ABORTING CHECK: source {source_id}.{field_name} changed "
                        f"({before_value!r} -> {after_value!r}), not just tier",
                        file=sys.stderr,
                    )
                    return 1
        print(f"confirmed: only tier changed on {len(changed_ids)} row(s)")

        print(f"\n=== all source rows for subject {SUBJECT_ID_TO_PRINT} ===")
        subject_sources = session.exec(
            select(Source)
            .where(Source.subject_id == SUBJECT_ID_TO_PRINT)
            .order_by(col(Source.id))
        ).all()
        for source in subject_sources:
            print(
                f"  id={source.id}  tier={source.tier.value:<14}  "
                f"domain={source.domain:<24}  url={source.url}"
            )

    return 0


if __name__ == "__main__":
    sys.exit(retier())
