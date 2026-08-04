"""The same real-world account should never be registered as two Channel
rows -- enforced at the database level, not just by API-layer discipline.
"""

from __future__ import annotations

import pytest
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session

from packages.domain.enums import Platform
from tests.factories import make_channel


def test_duplicate_platform_and_external_account_id_is_rejected(
    session: Session, strategy_id: int
) -> None:
    session.add(
        make_channel(
            strategy_id,
            external_account_id="UC1234567890",
            is_active=True,
        )
    )
    session.commit()

    session.add(
        make_channel(
            strategy_id,
            external_account_id="UC1234567890",
            is_active=True,
        )
    )
    with pytest.raises(IntegrityError):
        session.commit()


def test_same_external_account_id_on_different_platform_is_allowed(
    session: Session, strategy_id: int
) -> None:
    session.add(make_channel(strategy_id, platform=Platform.YOUTUBE, external_account_id="same-id"))
    session.commit()

    session.add(make_channel(strategy_id, platform=Platform.TIKTOK, external_account_id="same-id"))
    session.commit()  # must not raise
