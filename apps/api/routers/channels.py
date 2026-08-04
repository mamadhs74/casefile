"""Channels: a strategy's credentialed platform accounts.

No token handling anywhere here -- ChannelCreate/ChannelUpdate/ChannelRead
only ever carry credentials_ref (a Keychain entry name), never a secret.
There is no DELETE: a channel that's no longer usable gets deactivated
(PATCH is_active=false), not removed, since a Publication may already
reference it.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from sqlmodel import select

from apps.api.deps import SessionDep, get_strategy_or_404
from apps.api.schemas import ChannelCreate, ChannelRead, ChannelUpdate
from packages.db.models import Channel

router = APIRouter(prefix="/strategies", tags=["channels"])


def _get_channel_or_404(session: SessionDep, strategy_id: int, channel_id: int) -> Channel:
    channel = session.get(Channel, channel_id)
    if channel is None or channel.strategy_id != strategy_id:
        raise HTTPException(status_code=404, detail="channel not found")
    return channel


@router.get("/{slug}/channels", response_model=list[ChannelRead])
def list_channels(slug: str, session: SessionDep) -> list[ChannelRead]:
    strategy = get_strategy_or_404(session, slug)
    channels = session.exec(select(Channel).where(Channel.strategy_id == strategy.id))
    return [ChannelRead.model_validate(channel) for channel in channels]


@router.post("/{slug}/channels", response_model=ChannelRead, status_code=201)
def create_channel(slug: str, payload: ChannelCreate, session: SessionDep) -> ChannelRead:
    strategy = get_strategy_or_404(session, slug)
    channel = Channel(strategy_id=strategy.id, **payload.model_dump())
    session.add(channel)
    session.commit()
    session.refresh(channel)
    return ChannelRead.model_validate(channel)


@router.patch("/{slug}/channels/{channel_id}", response_model=ChannelRead)
def update_channel(
    slug: str, channel_id: int, payload: ChannelUpdate, session: SessionDep
) -> ChannelRead:
    strategy = get_strategy_or_404(session, slug)
    channel = _get_channel_or_404(session, strategy.id, channel_id)  # type: ignore[arg-type]
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(channel, field, value)
    session.add(channel)
    session.commit()
    session.refresh(channel)
    return ChannelRead.model_validate(channel)
