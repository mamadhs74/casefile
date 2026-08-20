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

Also imports .publish_template, same shape again: registers this
strategy's YouTube title/description/tags template with
packages.publish.templates. criminal-cases has no equivalent import --
no template file exists for it yet, by design (see the task this was
built under), so packages.publish.templates.get_publish_template
raises UnknownPublishTemplateError if anything ever asks for one.

packages/db/listeners.py imports this package for both of the first two
side effects -- that import is Tier 2 per CLAUDE.md (it names
listeners.py explicitly). The publish_template import doesn't change
that: listeners.py itself is untouched by this addition.
"""

from __future__ import annotations

import packages.strategies.film_tv_news.publish_template  # noqa: F401  registers the publish template
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
