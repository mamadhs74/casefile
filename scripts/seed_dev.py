"""Seed data/casefile.db with the criminal-cases strategy and subjects
spanning every monetization tier and legal-risk level, for exercising the
case library UI against real data.

monetization_tier, legal_risk, eligibility_notes, Subject.attributes, and
Source.domain are all computed/validated by packages/db/listeners.py on
insert -- this script never sets the computed ones directly, same as the
API never accepts them from a client.

Run with: uv run python scripts/seed_dev.py
"""

from __future__ import annotations

from datetime import UTC, date, datetime

from sqlmodel import select

from packages.db.models import (
    Channel,
    Claim,
    ClaimEntity,
    ClaimSource,
    Entity,
    Source,
    Strategy,
    Subject,
)
from packages.db.session import create_all, get_session
from packages.domain.enums import (
    ArchiveProvider,
    ClaimCategory,
    ClaimConfidence,
    ClaimType,
    EntityRole,
    ImageRights,
    Platform,
    ResolutionStatus,
    SourceTier,
    SubjectStatus,
)
from packages.strategies.criminal_cases import SLUG as CRIMINAL_CASES_SLUG
from packages.strategies.criminal_cases.enums import CaseType, RiskFlag


def seed() -> None:
    create_all()
    with get_session() as session:
        if session.exec(select(Subject)).first() is not None:
            print("data/casefile.db already has subjects -- not reseeding.")
            return

        strategy = session.exec(
            select(Strategy).where(Strategy.slug == CRIMINAL_CASES_SLUG)
        ).first()
        if strategy is None:
            strategy = Strategy(
                slug=CRIMINAL_CASES_SLUG,
                name="Criminal Cases",
                description="Well-documented criminal cases with primary-record sourcing.",
                subject_noun_singular="case",
                subject_noun_plural="cases",
                min_verified_sources=3,
                min_primary_records=1,
                min_distinct_domains=3,
                style_guide={
                    "tone": "factual, investigative",
                    "forbidden": [
                        "gore description beyond what a news report would carry",
                        "speculation presented as fact",
                        "victim-blaming framing",
                        "recreations of the moment of death",
                        "you won't believe what happened next",
                    ],
                },
                allowed_archive_providers=list(ArchiveProvider),
            )
            session.add(strategy)
            session.commit()
            session.refresh(strategy)
        assert strategy.id is not None
        strategy_id = strategy.id

        meridian = Subject(
            strategy_id=strategy_id,
            slug="green-1948-vanished-liner",
            title="The Vanishing of the SS Meridian",
            attributes={"case_type": CaseType.MARITIME},
            event_year=1948,
            country="United Kingdom",
            region="Southampton",
            summary=(
                "A passenger liner departs Southampton and is never seen again. "
                "Reconstructed from Admiralty inquiry records, insurance filings, "
                "and contemporaneous shipping press."
            ),
            resolution_status=ResolutionStatus.OFFICIALLY_RULED,
            living_persons_involved=False,
            risk_flags=[],
            documentation_score=8,
            estimated_runtime_min=22,
            status=SubjectStatus.READY,
        )
        fairmount = Subject(
            strategy_id=strategy_id,
            slug="green-1962-institution-inquest",
            title="The Fairmount Home Inquest",
            attributes={"case_type": CaseType.INSTITUTIONAL_ABUSE},
            event_year=1962,
            country="Canada",
            region="Ontario",
            summary="A provincial inquest into conditions at a since-closed institution.",
            resolution_status=ResolutionStatus.OFFICIALLY_RULED,
            living_persons_involved=False,
            risk_flags=[],
            documentation_score=6,
            estimated_runtime_min=28,
            status=SubjectStatus.CANDIDATE,
        )
        route_9 = Subject(
            strategy_id=strategy_id,
            slug="yellow-2019-disappearance",
            title="Last Seen on Route 9",
            attributes={"case_type": CaseType.DISAPPEARANCE},
            event_year=2019,
            country="United States",
            region="Vermont",
            summary="A hiker disappears from a marked trail; the case remains open.",
            resolution_status=ResolutionStatus.UNSOLVED,
            living_persons_involved=True,
            risk_flags=[RiskFlag.RECENT_EVENT],
            documentation_score=5,
            estimated_runtime_min=None,
            status=SubjectStatus.RESEARCHING,
        )
        cedar_street = Subject(
            strategy_id=strategy_id,
            slug="yellow-1991-hate-motivated",
            title="The Cedar Street Fire",
            attributes={"case_type": CaseType.DISASTER},
            event_year=1991,
            country="United States",
            region="Ohio",
            summary="An arson case with a politically charged aftermath.",
            resolution_status=ResolutionStatus.CONVICTED,
            living_persons_involved=False,
            risk_flags=[RiskFlag.POLITICAL_VIOLENCE],
            documentation_score=4,
            estimated_runtime_min=24,
            status=SubjectStatus.CANDIDATE,
        )
        blocked_example = Subject(
            strategy_id=strategy_id,
            slug="red-child-victim-case",
            title="[Placeholder] Blocked case example",
            attributes={"case_type": CaseType.HOMICIDE},
            event_year=1985,
            country="United States",
            region="Illinois",
            summary=(
                "Seed data exercising the RED tier -- child victim flag blocks "
                "monetization outright."
            ),
            resolution_status=ResolutionStatus.CONVICTED,
            living_persons_involved=False,
            risk_flags=[RiskFlag.CHILD_VICTIM],
            documentation_score=7,
            estimated_runtime_min=20,
            status=SubjectStatus.REJECTED,
        )
        harrow_quarry = Subject(
            strategy_id=strategy_id,
            slug="red-named-living-suspect",
            title="The Harrow Quarry Case",
            attributes={"case_type": CaseType.UNEXPLAINED_EVENT},
            event_year=2015,
            country="United States",
            region="Colorado",
            summary="A named, unconvicted living suspect with ongoing litigation.",
            resolution_status=ResolutionStatus.DISPUTED,
            living_persons_involved=True,
            risk_flags=[RiskFlag.NAMED_LIVING_SUSPECT, RiskFlag.ONGOING_LITIGATION],
            documentation_score=5,
            estimated_runtime_min=None,
            status=SubjectStatus.CANDIDATE,
        )
        blackwater = Subject(
            strategy_id=strategy_id,
            slug="unknown-not-scored",
            title="The Blackwater Ledger",
            attributes={"case_type": CaseType.HISTORICAL_HORROR},
            event_year=1904,
            country="United States",
            region="Louisiana",
            summary="Research just started -- no documentation score assigned yet.",
            resolution_status=ResolutionStatus.DISPUTED,
            living_persons_involved=False,
            risk_flags=[],
            documentation_score=None,
            estimated_runtime_min=None,
            status=SubjectStatus.CANDIDATE,
        )

        subjects = [
            meridian,
            fairmount,
            route_9,
            cedar_street,
            blocked_example,
            harrow_quarry,
            blackwater,
        ]
        session.add_all(subjects)
        session.commit()
        for subject in subjects:
            session.refresh(subject)

        # meridian gets a full, passing source gate (3 verified, 1 primary, 3 domains).
        sources = [
            Source(
                subject_id=meridian.id,
                url="https://www.nationalarchives.gov.uk/inquiry/meridian-1948",
                publisher="The National Archives (UK)",
                title="Board of Trade Inquiry into the Loss of SS Meridian",
                published_date=date(1949, 3, 2),
                retrieved_at=datetime.now(UTC),
                tier=SourceTier.PRIMARY_RECORD,
                text_path="subjects/green-1948-vanished-liner/sources/1.txt",
                text_sha256="a" * 64,
                word_count=4200,
            ),
            Source(
                subject_id=meridian.id,
                url="https://www.lloydslist.com/archive/meridian-inquiry",
                publisher="Lloyd's List",
                title="Inquiry Opens Into Meridian Disappearance",
                published_date=date(1948, 11, 14),
                retrieved_at=datetime.now(UTC),
                tier=SourceTier.CONTEMPORANEOUS,
                text_path="subjects/green-1948-vanished-liner/sources/2.txt",
                text_sha256="b" * 64,
                word_count=850,
            ),
            Source(
                subject_id=meridian.id,
                url="https://www.bbc.co.uk/history/meridian-mystery",
                publisher="BBC History",
                title="Britain's Cold War Ghost Ship",
                published_date=date(2011, 5, 6),
                retrieved_at=datetime.now(UTC),
                tier=SourceTier.RETROSPECTIVE,
                text_path="subjects/green-1948-vanished-liner/sources/3.txt",
                text_sha256="c" * 64,
                word_count=1600,
            ),
            # fairmount gets one source -- a source gate that still fails, to
            # exercise the gate's "not yet clear" state on the detail page.
            Source(
                subject_id=fairmount.id,
                url="https://www.cbc.ca/news/fairmount-inquest",
                publisher="CBC News",
                title="Provincial Inquest Opens Into Fairmount Home",
                published_date=date(1963, 1, 20),
                retrieved_at=datetime.now(UTC),
                tier=SourceTier.CONTEMPORANEOUS,
                text_path="subjects/green-1962-institution-inquest/sources/1.txt",
                text_sha256="d" * 64,
                word_count=620,
            ),
        ]
        session.add_all(sources)
        session.commit()
        for source in sources:
            session.refresh(source)
        meridian_primary, meridian_contemporaneous, meridian_retrospective, _ = sources

        # Claims and entities for meridian only -- it's the one subject with
        # a passing source gate, so it's the one where a real narratable
        # claim (Tier A sourcing, enforced by packages/db/listeners.py) and
        # a real non-narratable one (Tier B only) can both be shown
        # honestly. narratable can't be set at creation -- see
        # NarratableSourcingError -- so claims are created False, sourced,
        # then flipped in a second write, same sequence the invariant
        # requires of any caller.
        departure_claim = Claim(
            subject_id=meridian.id,
            statement=(
                "The SS Meridian departed Southampton on 12 November 1948 "
                "and was never sighted again."
            ),
            category=ClaimCategory.EVENT,
            claim_type=ClaimType.FACT,
            confidence=ClaimConfidence.ESTABLISHED,
            date_anchor="1948-11-12",
        )
        inquiry_opened_claim = Claim(
            subject_id=meridian.id,
            statement=(
                "Lloyd's List reported the Board of Trade inquiry had opened "
                "by mid-November 1948."
            ),
            category=ClaimCategory.TIMELINE,
            claim_type=ClaimType.CONTEMPORANEOUS_REPORT,
            confidence=ClaimConfidence.REPORTED,
            date_anchor="1948-11-14",
        )
        cold_war_speculation_claim = Claim(
            subject_id=meridian.id,
            statement=(
                "Some retrospective accounts frame the disappearance within Cold War "
                "intelligence speculation, though no primary record supports this."
            ),
            category=ClaimCategory.EVENT,
            claim_type=ClaimType.DISPUTED,
            confidence=ClaimConfidence.CONTESTED,
            contested_note="No primary or contemporaneous source corroborates this reading.",
            date_anchor=None,
        )
        claims = [departure_claim, inquiry_opened_claim, cold_war_speculation_claim]
        session.add_all(claims)
        session.commit()
        for claim in claims:
            session.refresh(claim)

        session.add_all(
            [
                ClaimSource(claim_id=departure_claim.id, source_id=meridian_primary.id),
                ClaimSource(
                    claim_id=inquiry_opened_claim.id, source_id=meridian_contemporaneous.id
                ),
                ClaimSource(
                    claim_id=cold_war_speculation_claim.id, source_id=meridian_retrospective.id
                ),
            ]
        )
        session.commit()

        # Only the two Tier A-sourced claims can become narratable -- the
        # retrospective-only one is left False, exactly as the gate
        # requires: it may inform research, it may never be narrated.
        departure_claim.narratable = True
        inquiry_opened_claim.narratable = True
        session.add(departure_claim)
        session.add(inquiry_opened_claim)
        session.commit()

        captain = Entity(
            subject_id=meridian.id,
            name="Captain of the SS Meridian",
            role=EntityRole.VICTIM,
            living=False,
            adjudicated=False,
            image_rights=ImageRights.PUBLIC_DOMAIN,
        )
        inquiry_chair = Entity(
            subject_id=meridian.id,
            name="Board of Trade Inquiry Chair",
            role=EntityRole.INVESTIGATOR,
            living=False,
            adjudicated=False,
            image_rights=ImageRights.PUBLIC_DOMAIN,
        )
        entities = [captain, inquiry_chair]
        session.add_all(entities)
        session.commit()
        for entity in entities:
            session.refresh(entity)

        session.add(ClaimEntity(claim_id=departure_claim.id, entity_id=captain.id))
        session.commit()

        # One inactive placeholder channel per platform -- nothing is
        # actually connected (no OAuth flow exists yet, see
        # apps/api/routers/channels.py), but the publishing UI needs a row
        # to render per platform. Left empty rather than filled with
        # plausible-looking fake names: is_active=False is what tells the
        # frontend "not connected," and it must never depend on whether
        # these string fields happen to be non-empty.
        channels = [
            Channel(
                strategy_id=strategy_id,
                platform=platform,
                display_name="",
                external_account_id="",
                credentials_ref="",
                is_active=False,
            )
            for platform in Platform
        ]
        session.add_all(channels)
        session.commit()

        for subject in subjects:
            print(
                f"{subject.id:>3}  {subject.title:<45} "
                f"{subject.monetization_tier:<8} {subject.legal_risk}"
            )


if __name__ == "__main__":
    seed()
