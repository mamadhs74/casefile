"""FastAPI dependencies."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Annotated

from fastapi import Depends, HTTPException
from sqlmodel import Session, select

from packages.db.models import Strategy, Subject
from packages.db.session import get_engine


def get_session() -> Iterator[Session]:
    with Session(get_engine()) as session:
        yield session


SessionDep = Annotated[Session, Depends(get_session)]


def get_subject_or_404(session: Session, subject_id: int) -> Subject:
    subject = session.get(Subject, subject_id)
    if subject is None:
        raise HTTPException(status_code=404, detail="subject not found")
    return subject


def get_strategy_or_404(session: Session, slug: str) -> Strategy:
    strategy = session.exec(select(Strategy).where(Strategy.slug == slug)).first()
    if strategy is None:
        raise HTTPException(status_code=404, detail="strategy not found")
    return strategy
