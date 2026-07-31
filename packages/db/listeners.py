"""Persistence-layer enforcement of computed fields.

Values a caller must not be able to hand-set are recomputed in before_insert
and before_update listeners, unconditionally, so no code path -- API, script,
direct session use -- can slip past them.
"""

from __future__ import annotations

from typing import Any

import tldextract
from sqlalchemy import event
from sqlalchemy.engine import Connection
from sqlalchemy.orm import Mapper

from packages.db.models import Case, Source
from packages.research.eligibility import score_case

# suffix_list_urls=() disables tldextract's live fetch of the Public Suffix
# List, so domain derivation never makes a network call and is deterministic
# in tests and CI -- it uses the snapshot bundled with the package.
_extract = tldextract.TLDExtract(suffix_list_urls=())


def _derive_domain(url: str) -> str:
    extracted = _extract(url)
    if extracted.suffix:
        return f"{extracted.domain}.{extracted.suffix}".lower()
    return extracted.domain.lower()


@event.listens_for(Case, "before_insert")
@event.listens_for(Case, "before_update")
def _recompute_eligibility(mapper: Mapper[Any], connection: Connection, target: Case) -> None:
    result = score_case(target)
    target.monetization_tier = result.tier
    target.legal_risk = result.legal_risk
    target.eligibility_notes = result.notes


@event.listens_for(Source, "before_insert")
@event.listens_for(Source, "before_update")
def _derive_source_domain(mapper: Mapper[Any], connection: Connection, target: Source) -> None:
    target.domain = _derive_domain(target.url)
