"""Seed data/casefile.db with cases spanning every monetization tier and
legal-risk level, for exercising the case library UI against real data.

monetization_tier, legal_risk, eligibility_notes, and Source.domain are all
computed by packages/db/listeners.py on insert -- this script never sets
them directly, same as the API never accepts them from a client.

Run with: uv run python scripts/seed_dev.py
"""

from __future__ import annotations

from datetime import UTC, date, datetime

from sqlmodel import select

from packages.db.models import Case, Source
from packages.db.session import create_all, get_session
from packages.domain.enums import CaseStatus, CaseType, ResolutionStatus, RiskFlag, SourceTier


def seed() -> None:
    create_all()
    with get_session() as session:
        if session.exec(select(Case)).first() is not None:
            print("data/casefile.db already has cases -- not reseeding.")
            return

        meridian = Case(
            slug="green-1948-vanished-liner",
            title="The Vanishing of the SS Meridian",
            case_type=CaseType.MARITIME,
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
            status=CaseStatus.READY,
        )
        fairmount = Case(
            slug="green-1962-institution-inquest",
            title="The Fairmount Home Inquest",
            case_type=CaseType.INSTITUTIONAL_ABUSE,
            event_year=1962,
            country="Canada",
            region="Ontario",
            summary="A provincial inquest into conditions at a since-closed institution.",
            resolution_status=ResolutionStatus.OFFICIALLY_RULED,
            living_persons_involved=False,
            risk_flags=[],
            documentation_score=6,
            estimated_runtime_min=28,
            status=CaseStatus.CANDIDATE,
        )
        route_9 = Case(
            slug="yellow-2019-disappearance",
            title="Last Seen on Route 9",
            case_type=CaseType.DISAPPEARANCE,
            event_year=2019,
            country="United States",
            region="Vermont",
            summary="A hiker disappears from a marked trail; the case remains open.",
            resolution_status=ResolutionStatus.UNSOLVED,
            living_persons_involved=True,
            risk_flags=[RiskFlag.RECENT_EVENT],
            documentation_score=5,
            estimated_runtime_min=None,
            status=CaseStatus.RESEARCHING,
        )
        cedar_street = Case(
            slug="yellow-1991-hate-motivated",
            title="The Cedar Street Fire",
            case_type=CaseType.DISASTER,
            event_year=1991,
            country="United States",
            region="Ohio",
            summary="An arson case with a politically charged aftermath.",
            resolution_status=ResolutionStatus.CONVICTED,
            living_persons_involved=False,
            risk_flags=[RiskFlag.POLITICAL_VIOLENCE],
            documentation_score=4,
            estimated_runtime_min=24,
            status=CaseStatus.CANDIDATE,
        )
        blocked_example = Case(
            slug="red-child-victim-case",
            title="[Placeholder] Blocked case example",
            case_type=CaseType.HOMICIDE,
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
            status=CaseStatus.REJECTED,
        )
        harrow_quarry = Case(
            slug="red-named-living-suspect",
            title="The Harrow Quarry Case",
            case_type=CaseType.UNEXPLAINED_EVENT,
            event_year=2015,
            country="United States",
            region="Colorado",
            summary="A named, unconvicted living suspect with ongoing litigation.",
            resolution_status=ResolutionStatus.DISPUTED,
            living_persons_involved=True,
            risk_flags=[RiskFlag.NAMED_LIVING_SUSPECT, RiskFlag.ONGOING_LITIGATION],
            documentation_score=5,
            estimated_runtime_min=None,
            status=CaseStatus.CANDIDATE,
        )
        blackwater = Case(
            slug="unknown-not-scored",
            title="The Blackwater Ledger",
            case_type=CaseType.HISTORICAL_HORROR,
            event_year=1904,
            country="United States",
            region="Louisiana",
            summary="Research just started -- no documentation score assigned yet.",
            resolution_status=ResolutionStatus.DISPUTED,
            living_persons_involved=False,
            risk_flags=[],
            documentation_score=None,
            estimated_runtime_min=None,
            status=CaseStatus.CANDIDATE,
        )

        cases = [
            meridian,
            fairmount,
            route_9,
            cedar_street,
            blocked_example,
            harrow_quarry,
            blackwater,
        ]
        session.add_all(cases)
        session.commit()
        for case in cases:
            session.refresh(case)

        # meridian gets a full, passing source gate (3 verified, 1 primary, 3 domains).
        sources = [
            Source(
                case_id=meridian.id,
                url="https://www.nationalarchives.gov.uk/inquiry/meridian-1948",
                publisher="The National Archives (UK)",
                title="Board of Trade Inquiry into the Loss of SS Meridian",
                published_date=date(1949, 3, 2),
                retrieved_at=datetime.now(UTC),
                tier=SourceTier.PRIMARY_RECORD,
                text_path="cases/green-1948-vanished-liner/sources/1.txt",
                text_sha256="a" * 64,
                word_count=4200,
            ),
            Source(
                case_id=meridian.id,
                url="https://www.lloydslist.com/archive/meridian-inquiry",
                publisher="Lloyd's List",
                title="Inquiry Opens Into Meridian Disappearance",
                published_date=date(1948, 11, 14),
                retrieved_at=datetime.now(UTC),
                tier=SourceTier.CONTEMPORANEOUS,
                text_path="cases/green-1948-vanished-liner/sources/2.txt",
                text_sha256="b" * 64,
                word_count=850,
            ),
            Source(
                case_id=meridian.id,
                url="https://www.bbc.co.uk/history/meridian-mystery",
                publisher="BBC History",
                title="Britain's Cold War Ghost Ship",
                published_date=date(2011, 5, 6),
                retrieved_at=datetime.now(UTC),
                tier=SourceTier.RETROSPECTIVE,
                text_path="cases/green-1948-vanished-liner/sources/3.txt",
                text_sha256="c" * 64,
                word_count=1600,
            ),
            # fairmount gets one source -- a source gate that still fails, to
            # exercise the gate's "not yet clear" state on the detail page.
            Source(
                case_id=fairmount.id,
                url="https://www.cbc.ca/news/fairmount-inquest",
                publisher="CBC News",
                title="Provincial Inquest Opens Into Fairmount Home",
                published_date=date(1963, 1, 20),
                retrieved_at=datetime.now(UTC),
                tier=SourceTier.CONTEMPORANEOUS,
                text_path="cases/green-1962-institution-inquest/sources/1.txt",
                text_sha256="d" * 64,
                word_count=620,
            ),
        ]
        session.add_all(sources)
        session.commit()

        for case in cases:
            print(f"{case.id:>3}  {case.title:<45} {case.monetization_tier:<8} {case.legal_risk}")


if __name__ == "__main__":
    seed()
