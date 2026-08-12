"""film-tv-news' own category and risk vocabulary, mirroring
packages/strategies/criminal_cases/enums.py's role exactly: one enum for
subject-matter categorization (there, CaseType; here, TopicType), one for
the risk flags a human reviewer tags on a Subject.

TopicType's seven values were checked against real coverage, not guessed --
each one matches a story class actually seen while verifying source
reachability for this package (casting news, a release calendar, a weekend
box-office report, a union vote, quarterly earnings, a festival lineup).

RiskFlag deliberately does not mirror criminal_cases' RiskFlag value-for-
value; criminal-cases' vocabulary describes risk properties of a resolved
historical event (CHILD_VICTIM, GRAPHIC_INJURY_CENTRAL, HATE_MOTIVATED),
and none of those describe what makes a week of film/TV industry news
risky. This vocabulary is built from CLAUDE.md's own forbidden list for
this strategy instead: NAMED_LIVING_INDIVIDUAL_ALLEGATION and
UNVERIFIED_RUMOR_CENTRAL implement "claims about any individual's private
conduct" and "unsourced casting rumors"; UNANNOUNCED_PROJECT_CENTRAL
implements "speculation about unannounced projects presented as
reporting"; ONGOING_LITIGATION mirrors criminal_cases' own flag of the
same name, unchanged, because pending litigation is exactly as real a
legal-risk signal here as it is there. MINOR_INVOLVED has no criminal_cases
counterpart in name, but is the same kind of prudence CHILD_VICTIM
encodes there, scoped to this domain -- a minor being covered in industry
news is not itself the RED-tier event CHILD_VICTIM is, so it is not
automatically RED here (see eligibility.py).

There is no RECENT_EVENT-equivalent flag. criminal_cases' RECENT_EVENT
exists to bias eligibility toward cases that are "legally resolved and
historically distant" (CLAUDE.md's own R7 preference) -- recency is a
risk factor to penalize there. film-tv-news is, by its own definition,
always about the current week's coverage; every subject this strategy
ever produces is recent, so a flag that would be true 100% of the time
carries no signal and is left out rather than added for the sake of a
mirror that doesn't fit.
"""

from __future__ import annotations

from enum import StrEnum


class TopicType(StrEnum):
    CASTING_AND_PRODUCTION = "casting_and_production"
    RELEASE_AND_MARKETING = "release_and_marketing"
    BOX_OFFICE = "box_office"
    STREAMING_AND_TV = "streaming_and_tv"
    INDUSTRY_BUSINESS = "industry_business"
    AWARDS_AND_FESTIVALS = "awards_and_festivals"
    LABOR_AND_LEGAL = "labor_and_legal"


class RiskFlag(StrEnum):
    NAMED_LIVING_INDIVIDUAL_ALLEGATION = "named_living_individual_allegation"
    UNVERIFIED_RUMOR_CENTRAL = "unverified_rumor_central"
    UNANNOUNCED_PROJECT_CENTRAL = "unannounced_project_central"
    ONGOING_LITIGATION = "ongoing_litigation"
    MINOR_INVOLVED = "minor_involved"
