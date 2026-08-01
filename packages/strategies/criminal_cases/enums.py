"""criminal-cases' own category and risk vocabulary.

Relocated from packages/domain/enums.py unchanged in content -- see
docs/SCHEMA.md. Not split or renamed on migration; revisit only when a
second strategy actually claims one of these values.
"""

from __future__ import annotations

from enum import StrEnum


class CaseType(StrEnum):
    HOMICIDE = "homicide"
    DISAPPEARANCE = "disappearance"
    UNEXPLAINED_EVENT = "unexplained_event"
    HISTORICAL_HORROR = "historical_horror"
    MARITIME = "maritime"
    DISASTER = "disaster"
    INSTITUTIONAL_ABUSE = "institutional_abuse"


class RiskFlag(StrEnum):
    CHILD_VICTIM = "child_victim"
    SEXUAL_VIOLENCE = "sexual_violence"
    GRAPHIC_INJURY_CENTRAL = "graphic_injury_central"
    SUICIDE_CENTRAL = "suicide_central"
    ONGOING_LITIGATION = "ongoing_litigation"
    NAMED_LIVING_SUSPECT = "named_living_suspect"
    RECENT_EVENT = "recent_event"
    POLITICAL_VIOLENCE = "political_violence"
    HATE_MOTIVATED = "hate_motivated"
