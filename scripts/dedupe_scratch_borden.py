"""Propose a dedup of subject 8's 1893 Borden claims via clustering.

SCOPE: read-only database access, SELECT only. No Gemini calls, no
writes, zero quota. This measures a proposed dedup -- it does not
apply one. No claim row is touched, modified, or deleted.

Clustering reuses scripts/measure_claim_duplication.py's own
single-linkage logic (ClaimText, _cluster) rather than reimplementing
it, at the same --threshold default. From each cluster this picks one
representative -- the longest statement, on the grounds that it
usually carries the most detail of its cluster-mates -- tie-broken by
the lowest claim_id for a deterministic pick. It then reports the
word budget the deduplicated set would produce at WORDS_PER_CLAIM
next to the raw set's budget, so the effect on
scripts/compose_scratch_borden.py's word_budget calculation is
visible before anyone decides to act on it.

Same subject_id=8, date_anchor LIKE '1893%' filter as
scripts/compose_scratch_borden.py, for the same reason: it isolates
the real Lizzie Borden material from the two unrelated cases sharing
subject 8's row.

Usage:
    uv run python -m scripts.dedupe_scratch_borden
    uv run python -m scripts.dedupe_scratch_borden --threshold 0.8
"""

from __future__ import annotations

import argparse
from pathlib import Path

from sqlalchemy import create_engine
from sqlmodel import Session, col, select

from packages.db.models import Claim
from packages.script.chronological import WORDS_PER_CLAIM
from scripts.measure_claim_duplication import DEFAULT_THRESHOLD, ClaimText, _cluster

DB_PATH = Path("data/casefile.db")

# Deliberate, non-negotiable -- see module docstring and
# scripts/compose_scratch_borden.py for the full reasoning.
SUBJECT_ID = 8
DATE_PREFIX = "1893"


def _fetch_claims(session: Session) -> list[ClaimText]:
    query = (
        select(Claim)
        .where(
            Claim.subject_id == SUBJECT_ID,
            col(Claim.date_anchor).like(f"{DATE_PREFIX}%"),
        )
        .order_by(col(Claim.date_anchor), col(Claim.id))
    )
    claims = session.exec(query).all()
    records: list[ClaimText] = []
    for claim in claims:
        assert claim.id is not None  # a queried, persisted row always has one
        records.append(
            ClaimText(claim_id=claim.id, subject_id=claim.subject_id, statement=claim.statement)
        )
    return records


def _pick_representative(claim_ids: list[int], by_id: dict[int, ClaimText]) -> ClaimText:
    """Longest statement wins -- usually the one carrying the most detail
    of its cluster-mates. Ties broken by lowest claim_id, for a
    deterministic pick rather than an arbitrary one."""
    return min((by_id[cid] for cid in claim_ids), key=lambda c: (-len(c.statement), c.claim_id))


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--threshold",
        type=float,
        default=DEFAULT_THRESHOLD,
        help=f"Similarity score above which a pair counts as linked (default {DEFAULT_THRESHOLD}).",
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    threshold: float = args.threshold

    engine = create_engine(f"sqlite:///file:{DB_PATH}?mode=ro&uri=true")
    with Session(engine) as session:
        claims = _fetch_claims(session)

    by_id = {claim.claim_id: claim for claim in claims}
    pairs_above, clusters = _cluster(claims, threshold)
    representatives = [_pick_representative(members, by_id) for members in clusters.values()]

    print(f"subject_id={SUBJECT_ID}, date_anchor LIKE '{DATE_PREFIX}%'")
    print(f"original count: {len(claims)}")
    print(f"cluster count: {len(clusters)}  ({pairs_above} pairs above {threshold:.2f})")
    print(f"deduplicated count: {len(representatives)}")
    print()

    for members in sorted(clusters.values(), key=min):
        picked = _pick_representative(members, by_id)
        dropped = [by_id[claim_id] for claim_id in sorted(members) if claim_id != picked.claim_id]
        print(f"cluster (claim_ids={sorted(members)}):")
        print(f"  picked   claim_id={picked.claim_id}  {picked.statement}")
        for claim in dropped:
            print(f"  dropped  claim_id={claim.claim_id}  {claim.statement}")
        print()

    raw_budget = len(claims) * WORDS_PER_CLAIM
    dedup_budget = len(representatives) * WORDS_PER_CLAIM
    print(
        f"word budget at {WORDS_PER_CLAIM} words/claim: "
        f"raw={raw_budget}  deduplicated={dedup_budget}  "
        f"difference={raw_budget - dedup_budget}"
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
