"""The shape of Subject.attributes for a criminal-cases subject.

Validated by packages/research/dispatch.py::validate_attributes on every
Subject write, via packages/db/listeners.py -- not by caller discipline.
extra="forbid" for the same reason SubjectCreate uses it: an attempt to
smuggle in an unrecognized key is a 422, not a silent no-op.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from packages.strategies.criminal_cases.enums import CaseType


class Attributes(BaseModel):
    model_config = ConfigDict(extra="forbid")

    case_type: CaseType
