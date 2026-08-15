"""The film-tv-news strategy: mirrors
packages/strategies/criminal_cases/__init__.py's structure and
registration pattern exactly -- see that module's own docstring for why
importing this package registers it with packages.research.dispatch as a
side effect.

Also imports .tiering for its own import-time side effect: registering
this strategy's tier assigner with packages.research.tiering, the same
pattern used for dispatch just above. See packages/strategies/
film_tv_news/tiering.py's own docstring for why this strategy, unlike
criminal_cases, has one at all.

packages/db/listeners.py imports this package for both side effects --
that import is Tier 2 per CLAUDE.md (it names listeners.py explicitly).
"""

from __future__ import annotations

import packages.strategies.film_tv_news.tiering  # noqa: F401  registers the tier assigner
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
