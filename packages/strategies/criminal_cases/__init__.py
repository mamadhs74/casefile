"""The criminal-cases strategy: the first strategy, migrated from what used
to be the only content model casefile had.

Importing this package registers it with packages.research.dispatch as a
side effect -- packages/db/listeners.py imports it for exactly that reason,
the same pattern packages/db/session.py already uses to register the
before_insert/before_update listeners themselves.
"""

from __future__ import annotations

from packages.research.dispatch import StrategyDefinition, register_strategy
from packages.strategies.criminal_cases.attributes import Attributes
from packages.strategies.criminal_cases.eligibility import score_case
from packages.strategies.criminal_cases.enums import RiskFlag

SLUG = "criminal-cases"

register_strategy(
    StrategyDefinition(
        slug=SLUG,
        risk_flag_enum=RiskFlag,
        scorer=score_case,
        attributes_model=Attributes,
    )
)
