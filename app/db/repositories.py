"""Small data-access helpers shared by the API and the worker."""

from dataclasses import dataclass

from sqlalchemy import delete, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import ChannelGroup, ClassRoom, ProcessedEvent, RequestLog, SecurityEvent


@dataclass(frozen=True)
class ResolvedClass:
    id: str
    name: str
    enabled: bool


async def resolve_class(session: AsyncSession, channel: str, group_id: str) -> ResolvedClass | None:
    """Server-side class resolution: (channel, group_id) -> class. The ONLY way a class_id is derived."""
    row = (
        await session.execute(
            select(ClassRoom.id, ClassRoom.name, ClassRoom.enabled)
            .join(ChannelGroup, ChannelGroup.class_id == ClassRoom.id)
            .where(ChannelGroup.channel == channel, ChannelGroup.external_group_id == group_id)
        )
    ).one_or_none()
    return ResolvedClass(*row) if row else None


async def claim_event(session: AsyncSession, channel: str, event_id: str) -> bool:
    """Atomically record an event. False if it was already seen (also under concurrent delivery:
    the second INSERT blocks on the first one's row lock, then hits the PK and does nothing)."""
    stmt = (
        insert(ProcessedEvent)
        .values(channel=channel, event_id=event_id, status="received")
        .on_conflict_do_nothing()
        .returning(ProcessedEvent.event_id)
    )
    claimed = (await session.execute(stmt)).scalar_one_or_none() is not None
    await session.commit()
    return claimed


async def set_event_status(session: AsyncSession, channel: str, event_id: str, status: str) -> None:
    await session.execute(
        update(ProcessedEvent)
        .where(ProcessedEvent.channel == channel, ProcessedEvent.event_id == event_id)
        .values(status=status)
    )


async def release_event(session: AsyncSession, channel: str, event_id: str) -> None:
    """Forget an event so the platform's retry is processed (used when enqueueing failed)."""
    await session.execute(
        delete(ProcessedEvent).where(ProcessedEvent.channel == channel, ProcessedEvent.event_id == event_id)
    )
    await session.commit()


def add_security_event(
    session: AsyncSession,
    type_: str,
    *,
    request_id: str | None,
    class_id: str | None = None,
    user_hash: str | None = None,
    detail: str | None = None,
) -> None:
    """Queue a security event on the session. `detail` must already be redacted / payload-free."""
    session.add(
        SecurityEvent(
            type=type_, request_id=request_id, class_id=class_id, user_hash=user_hash, detail_redacted=detail
        )
    )


def add_request_log(session: AsyncSession, **fields: object) -> None:
    session.add(RequestLog(**fields))


async def set_class_enabled(session: AsyncSession, class_id: str, enabled: bool) -> bool:
    result = await session.execute(
        update(ClassRoom)
        .where(ClassRoom.id == class_id, ClassRoom.is_shared.is_(False))
        .values(enabled=enabled)
    )
    await session.commit()
    return result.rowcount > 0
