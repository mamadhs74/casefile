"""Persistence-layer enforcement of Case eligibility.

Eligibility must not depend on every caller remembering to recompute it
before a write. These listeners recompute monetization_tier, legal_risk, and
eligibility_notes from score_case() on every insert and update, overwriting
any hand-set values unconditionally.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import event
from sqlalchemy.engine import Connection
from sqlalchemy.orm import Mapper

from packages.db.models import Case
from packages.research.eligibility import score_case


@event.listens_for(Case, "before_insert")
@event.listens_for(Case, "before_update")
def _recompute_eligibility(mapper: Mapper[Any], connection: Connection, target: Case) -> None:
    result = score_case(target)
    target.monetization_tier = result.tier
    target.legal_risk = result.legal_risk
    target.eligibility_notes = result.notes
