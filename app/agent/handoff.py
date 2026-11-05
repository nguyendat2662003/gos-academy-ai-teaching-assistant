"""Instructor handoff tickets (CLAUDE.md §10). Creation is idempotent per request_id (job retries)."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.classes import ClassRegistry
from app.db.models import HandoffTicket, TicketStatus


async def open_ticket(
    session: AsyncSession,
    *,
    registry: ClassRegistry,
    request_id: str,
    class_id: str,
    user_hash: str,
    question_redacted: str,
    reason: str,
    confidence: float | None,
    check_detail: dict,
    channel: str | None,
    group_id: str | None,
    reply_to: str | None,
) -> int:
    """Create (or return the existing) ticket for this request and commit. Returns the ticket id."""
    existing = await session.scalar(select(HandoffTicket.id).where(HandoffTicket.request_id == request_id))
    if existing is not None:
        return existing
    instructor = next((c.instructor_name for c in registry.classes if c.id == class_id), None)
    ticket = HandoffTicket(
        class_id=class_id,
        request_id=request_id,
        channel=channel,
        external_group_id=group_id,
        reply_to=reply_to,
        question_redacted=question_redacted,
        user_hash=user_hash,
        reason=reason,
        confidence=confidence,
        check_detail=check_detail,
        status=TicketStatus.OPEN,
        assignee=instructor,
    )
    session.add(ticket)
    await session.commit()
    return ticket.id
