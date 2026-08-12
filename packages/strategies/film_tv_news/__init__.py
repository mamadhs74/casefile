"""The film-tv-news strategy: mirrors
packages/strategies/criminal_cases/__init__.py's structure and
registration pattern exactly -- see that module's own docstring for why
importing this package registers it with packages.research.dispatch as a
side effect.

Unlike criminal_cases, nothing here imports this package for that side
effect yet: packages/db/listeners.py's registration import is Tier 2 per
CLAUDE.md (it names listeners.py explicitly), so it is not touched by this
change. Until something imports packages.strategies.film_tv_news, this
strategy is defined and independently testable but not reachable through
the live dispatch registry the API and DB listeners use.
"""

from __future__ import annotations

from packages.research.dispatch import StrategyDefinition, register_strategy
from packages.strategies.film_tv_news.attributes import Attributes
from packages.strategies.film_tv_news.eligibility import score_topic
from packages.strategies.film_tv_news.enums import RiskFlag

SLUG = "film-tv-news"

register_strategy(
    StrategyDefinition(
        slug=SLUG,
        risk_flag_enum=RiskFlag,
        scorer=score_topic,
        attributes_model=Attributes,
    )
)
