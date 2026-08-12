"""Measure near-duplicate claims per subject via pairwise text similarity.

SCOPE: read-only database access, SELECT only. No Gemini calls, no writes,
zero quota.

For every subject, every pair of claims' lowercased statements is compared
with difflib.SequenceMatcher.ratio(). Pairs scoring above --threshold are
treated as an edge in a similarity graph; connected components of that
graph (single-linkage clustering, via union-find) give an estimated
distinct-claim count. scripts/compose_scratch_borden.py's claim-coverage
run turned up six claims that were really one fact restated six ways --
this measures that kind of duplication directly, across every subject,
instead of noticing it as a side effect.

0.75 is a starting threshold, not a validated one -- retune with
--threshold rather than editing this file.

Usage:
    uv run python -m scripts.measure_claim_duplication
    uv run python -m scripts.measure_claim_duplication --threshold 0.8
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from difflib import SequenceMatcher
from itertools import combinations
from pathlib import Path

from sqlalchemy import create_engine
from sqlmodel import Session, col, select

from packages.db.models import Claim

DB_PATH = Path("data/casefile.db")
DEFAULT_THRESHOLD = 0.75
DETAIL_SUBJECT_ID = 8
TRUNCATE_LENGTH = 70


@dataclass(frozen=True)
class ClaimText:
    claim_id: int
    subject_id: int
    statement: str


def _fetch_claims(session: Session) -> list[ClaimText]:
    query = select(Claim).order_by(col(Claim.subject_id), col(Claim.id))
    claims = session.exec(query).all()
    records: list[ClaimText] = []
    for claim in claims:
        assert claim.id is not None
        records.append(
            ClaimText(claim_id=claim.id, subject_id=claim.subject_id, statement=claim.statement)
        )
    return records


class _UnionFind:
    """Plain union-find, no external dependency -- the claim counts here
    (tens to low hundreds per subject) don't warrant pulling in scipy or
    networkx for connected components."""

    def __init__(self, items: list[int]) -> None:
        self._parent = {item: item for item in items}

    def find(self, item: int) -> int:
        root = item
        while self._parent[root] != root:
            root = self._parent[root]
        while self._parent[item] != root:
            self._parent[item], item = root, self._parent[item]
        return root

    def union(self, a: int, b: int) -> None:
        root_a, root_b = self.find(a), self.find(b)
        if root_a != root_b:
            self._parent[root_a] = root_b


def _cluster(
    claims: list[ClaimText], threshold: float
) -> tuple[int, dict[int, list[int]]]:
    """Single-linkage clustering over the pairwise-similarity graph: any
    pair scoring above threshold is an edge, connected components are
    clusters. Returns (pairs_above_threshold, {root_claim_id: [claim_ids]}).
    Single-linkage chains transitively -- A~B and B~C clusters A with C
    even if A and C alone score below threshold. That's the requested
    method, not an oversight.
    """
    uf = _UnionFind([claim.claim_id for claim in claims])
    pairs_above = 0
    for a, b in combinations(claims, 2):
        ratio = SequenceMatcher(None, a.statement.lower(), b.statement.lower()).ratio()
        if ratio > threshold:
            pairs_above += 1
            uf.union(a.claim_id, b.claim_id)

    clusters: dict[int, list[int]] = {}
    for claim in claims:
        root = uf.find(claim.claim_id)
        clusters.setdefault(root, []).append(claim.claim_id)
    return pairs_above, clusters


def _print_subject_detail(
    subject_id: int, claims: list[ClaimText], clusters: dict[int, list[int]]
) -> None:
    by_id = {claim.claim_id: claim for claim in claims}
    multi_clusters = [members for members in clusters.values() if len(members) >= 2]

    print()
    print(f"subject_id={subject_id} clusters of 2 or more claims:")
    if not multi_clusters:
        print("  none")
        return
    for members in sorted(multi_clusters, key=min):
        print(f"  cluster ({len(members)} claims):")
        for claim_id in sorted(members):
            statement = by_id[claim_id].statement[:TRUNCATE_LENGTH]
            print(f"    claim_id={claim_id}  {statement}")


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

    by_subject: dict[int, list[ClaimText]] = {}
    for claim in claims:
        by_subject.setdefault(claim.subject_id, []).append(claim)

    detail_claims: list[ClaimText] = []
    detail_clusters: dict[int, list[int]] = {}
    for subject_id in sorted(by_subject):
        subject_claims = by_subject[subject_id]
        pairs_above, clusters = _cluster(subject_claims, threshold)
        print(
            f"subject_id={subject_id}: {len(subject_claims)} claims, "
            f"{pairs_above} pairs above {threshold:.2f}, "
            f"estimated distinct claims: {len(clusters)}"
        )
        if subject_id == DETAIL_SUBJECT_ID:
            detail_claims = subject_claims
            detail_clusters = clusters

    _print_subject_detail(DETAIL_SUBJECT_ID, detail_claims, detail_clusters)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
