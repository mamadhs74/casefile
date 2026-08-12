"""The shape of Subject.attributes for a film-tv-news subject. Mirrors
packages/strategies/criminal_cases/attributes.py exactly: one field naming
this subject's category, extra="forbid" so an unrecognized key is a 422,
not a silent no-op. Validated the same way, on every Subject write, via
packages/research/dispatch.py::validate_attributes.

This is also where the "one subject is a weekly topic covering roughly
five separate stories" difference would live, if criminal_cases encoded
any assumption about subject shape for this module to mirror -- it
doesn't. criminal_cases' own Attributes carries exactly one field
(case_type) and says nothing about how many stories, sections, or claims
belong to one case; that shape lives downstream, per Claim (see
packages/db/models.py's Section/Claim.section docstrings), not on
Subject.attributes. There is no equivalent slot here to put a story count
in, so none is added -- inventing one would not be mirroring
criminal_cases, it would be a new assumption with nothing to check it
against.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from packages.strategies.film_tv_news.enums import TopicType


class Attributes(BaseModel):
    model_config = ConfigDict(extra="forbid")

    topic_type: TopicType
