"""film-tv-news' eligibility scoring. Pure function, no DB access, fully
unit-testable -- same contract as
packages/strategies/criminal_cases/eligibility.py::score_case, reached only
through packages/research/dispatch.py::score_subject.

The scoring logic itself is not a value-for-value copy of score_case's,
deliberately: criminal_cases' GREEN path rewards a subject that is *not*
recent and has *no* living persons involved, because for a historical
criminal case those are real risk-reducing properties (CLAUDE.md's R7:
"prefer cases that are legally resolved and historically distant"). Every
film-tv-news subject is, by construction, about current industry news
concerning people who are almost always alive -- copying that gate over
unchanged would make GREEN structurally unreachable for this strategy.
Tier and legal-risk logic here are instead built from this strategy's own
RiskFlag vocabulary (see enums.py's docstring for why those flags exist).

subject.resolution_status is part of the shared TypedEligibilityInput
contract but is not read here. ResolutionStatus's five values (CONVICTED,
ACQUITTED, UNSOLVED, OFFICIALLY_RULED, DISPUTED) are criminal-justice
vocabulary with no meaningful film-tv-news analog -- there is no reading
of "a casting announcement was ACQUITTED." Subject.resolution_status is a
required, non-nullable column shared by every strategy (see
packages/db/models.py), so a real film-tv-news Subject will still have to
carry some value in it; that is a genuine mismatch worth resolving before
any real film-tv-news Subject is created, not something this scorer can
paper over by pretending one of the five values fits.
"""

from __future__ import annotations

from packages.domain.enums import LegalRisk, MonetizationTier
from packages.research.dispatch import TypedEligibilityInput
from packages.research.eligibility import EligibilityResult
from packages.strategies.film_tv_news.enums import RiskFlag

GREEN_MIN_DOCUMENTATION_SCORE = 3

_YELLOW_FLAGS = frozenset(
    {
        RiskFlag.ONGOING_LITIGATION,
        RiskFlag.UNVERIFIED_RUMOR_CENTRAL,
        RiskFlag.UNANNOUNCED_PROJECT_CENTRAL,
        RiskFlag.MINOR_INVOLVED,
        RiskFlag.NAMED_LIVING_INDIVIDUAL_ALLEGATION,
    }
)


def score_topic(subject: TypedEligibilityInput[RiskFlag]) -> EligibilityResult:
    flags = set(subject.risk_flags)
    tier, tier_notes = _score_tier(subject, flags)
    legal_risk, risk_notes = _score_legal_risk(subject, flags)
    return EligibilityResult(tier=tier, legal_risk=legal_risk, notes=[*tier_notes, *risk_notes])


def _unverified_named_allegation(flags: set[RiskFlag]) -> bool:
    """The closest analog to criminal_cases' "NAMED_LIVING_SUSPECT with
    resolution_status != CONVICTED": an allegation about a named living
    individual that rests on unverified/rumor sourcing rather than
    confirmed reporting, not one this strategy's own gate (R1, 3
    independent sources) has actually cleared."""
    return RiskFlag.NAMED_LIVING_INDIVIDUAL_ALLEGATION in flags and (
        RiskFlag.UNVERIFIED_RUMOR_CENTRAL in flags
    )


def _score_tier(
    subject: TypedEligibilityInput[RiskFlag], flags: set[RiskFlag]
) -> tuple[MonetizationTier, list[str]]:
    if RiskFlag.MINOR_INVOLVED in flags and (
        RiskFlag.UNVERIFIED_RUMOR_CENTRAL in flags
        or RiskFlag.NAMED_LIVING_INDIVIDUAL_ALLEGATION in flags
    ):
        return (
            MonetizationTier.RED,
            [
                "MINOR_INVOLVED combined with an unverified or allegation-centered "
                "story: no framing rescues this"
            ],
        )

    if _unverified_named_allegation(flags):
        return (
            MonetizationTier.RED,
            [
                "NAMED_LIVING_INDIVIDUAL_ALLEGATION resting on UNVERIFIED_RUMOR_CENTRAL: "
                "direct defamation exposure, no framing rescues this"
            ],
        )

    if subject.documentation_score is None:
        return (
            MonetizationTier.UNKNOWN,
            ["documentation_score is null: cannot score without knowing record depth"],
        )

    yellow_flags = flags & _YELLOW_FLAGS
    if yellow_flags:
        notes = [
            f"{flag.value} present: default yellow, may promote to green after script-level "
            "style pass"
            for flag in sorted(yellow_flags, key=lambda f: f.value)
        ]
        return MonetizationTier.YELLOW, notes

    if subject.documentation_score < GREEN_MIN_DOCUMENTATION_SCORE:
        return (
            MonetizationTier.YELLOW,
            [
                f"documentation_score {subject.documentation_score} is below the green "
                f"threshold of {GREEN_MIN_DOCUMENTATION_SCORE}"
            ],
        )

    return MonetizationTier.GREEN, []


def _score_legal_risk(
    subject: TypedEligibilityInput[RiskFlag], flags: set[RiskFlag]
) -> tuple[LegalRisk, list[str]]:
    if _unverified_named_allegation(flags):
        return (
            LegalRisk.HIGH,
            [
                "NAMED_LIVING_INDIVIDUAL_ALLEGATION resting on UNVERIFIED_RUMOR_CENTRAL: "
                "defamation exposure, do not produce"
            ],
        )

    if RiskFlag.ONGOING_LITIGATION in flags:
        return (
            LegalRisk.HIGH,
            ["ONGOING_LITIGATION present: high legal risk, do not produce"],
        )

    elevated = (
        RiskFlag.NAMED_LIVING_INDIVIDUAL_ALLEGATION in flags
        or RiskFlag.MINOR_INVOLVED in flags
        or subject.living_persons_involved
    )
    if elevated:
        return (
            LegalRisk.MEDIUM,
            [
                "named-individual, minor, or living-person exposure: elevated but "
                "non-blocking legal risk"
            ],
        )

    return LegalRisk.LOW, []
