"""Orchestrates automatic Section tagging across a subject's sources,
one Gemini call per source, with an on-disk JSON cache keyed by
source_id -- same resumability shape as
scripts/compose_subject10_episode.py's CachingCompositionProvider, but
built at the package level (not a script-local wrapper) since a future
caller (scripts/run_episode.py) needs to invoke this as one pipeline
stage, not just run it standalone.

Writes Claim.section through the ORM (session.add, caller flushes/
commits), never raw SQL -- packages/domain/enums.py's Section is a
SQLAlchemy Enum column that stores member NAMES ("GROUND"), not member
values ("ground"); a prior raw-SQL write got this backwards once
already (docs/HANDOFF.md finding #43's own correction), which is
exactly the class of bug going through the ORM with real Section
members (not raw strings) prevents structurally.

compute_subject_tags and apply_tags_to_db are deliberately separate:
the first is pure computation (network calls, no DB writes) that a
--verify mode can call safely; the second is the only function in this
module that touches Claim rows, so a caller choosing not to persist
never imports or calls it.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import cast

from sqlmodel import Session, col, select

from packages.db.models import Claim, ClaimSource
from packages.domain.enums import Section
from packages.script.section_tagging_provider import ClaimForTagging, SectionTaggingProvider


def _load_cache(path: Path) -> dict[str, dict[str, str | None]]:
    if not path.exists():
        return {}
    return cast("dict[str, dict[str, str | None]]", json.loads(path.read_text()))


def _save_cache(path: Path, cache: dict[str, dict[str, str | None]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(cache, indent=2))


def claims_by_source(session: Session, subject_id: int) -> dict[int, list[Claim]]:
    """Every claim for subject_id, grouped by the source_id(s) that cite
    it via ClaimSource -- ascending source_id, then claim id within each
    group. docs/SCHEMA.md's "exactly one ClaimSource per claim" finding
    means this is a 1:1 grouping in practice today, but the query goes
    through the real join rather than assuming that."""
    query = (
        select(ClaimSource.source_id, Claim)
        .join(Claim, col(Claim.id) == col(ClaimSource.claim_id))
        .where(Claim.subject_id == subject_id)
        .order_by(col(ClaimSource.source_id), col(Claim.id))
    )
    rows = session.exec(query).all()
    grouped: dict[int, list[Claim]] = {}
    for source_id, claim in rows:
        grouped.setdefault(source_id, []).append(claim)
    return grouped


def _to_tagging_input(claim: Claim) -> ClaimForTagging:
    assert claim.id is not None  # a queried, persisted row always has one
    return ClaimForTagging(
        claim_id=claim.id,
        statement=claim.statement,
        claim_type=claim.claim_type.name,
        confidence=claim.confidence.name,
        date_anchor=claim.date_anchor,
    )


async def compute_subject_tags(
    grouped: dict[int, list[Claim]],
    provider: SectionTaggingProvider,
    cache_path: Path,
) -> dict[int, dict[int, str | None]]:
    """Pure computation of tags, keyed [source_id][claim_id] -> section
    string or None. Never touches the DB -- see module docstring. A
    cache hit for a source makes zero provider calls; a failure on a
    cache-miss source propagates immediately (no retry), leaving every
    already-cached source -- including ones that succeeded earlier in
    this same call -- on disk for the next attempt."""
    cache = _load_cache(cache_path)

    for source_id, claims in sorted(grouped.items()):
        key = str(source_id)
        if key in cache:
            print(f"  source {source_id}: cache hit, skipping Gemini call")
            continue
        print(f"  source {source_id}: not cached, calling Gemini ({len(claims)} claims)...")
        tagging_input = [_to_tagging_input(c) for c in claims]
        tagged = await provider.tag_source_claims(source_id, tagging_input)
        cache[key] = {str(t.claim_id): t.section for t in tagged}
        _save_cache(cache_path, cache)
        print(f"  source {source_id}: tagged, cached")

    return {
        int(source_id): {int(claim_id): section for claim_id, section in tags.items()}
        for source_id, tags in cache.items()
    }


def apply_tags_to_db(
    session: Session,
    grouped: dict[int, list[Claim]],
    tags: dict[int, dict[int, str | None]],
) -> int:
    """Writes Claim.section through the ORM -- see module docstring on
    why this must never be raw SQL. Only touches claims present in
    `grouped` (i.e. real claims actually queried for this subject); a
    cache entry for a claim_id outside that set is ignored, not an
    error. Skips a claim already at its target value. Returns the
    number of rows actually changed. Caller commits (or rolls back)."""
    changed = 0
    for source_id, claims in grouped.items():
        source_tags = tags.get(source_id, {})
        for claim in claims:
            assert claim.id is not None
            raw = source_tags.get(claim.id)
            target = Section(raw.lower()) if raw else None
            if claim.section != target:
                claim.section = target
                session.add(claim)
                changed += 1
    return changed
