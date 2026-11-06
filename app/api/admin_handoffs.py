"""Admin API for instructor handoff tickets: list, answer (optionally post to the group), promote to FAQ,
export CSV (X-Admin-Key).

Roles (D-83): an instructor key sees and handles only its own class's tickets (another class's ticket answers
404); FAQ entries it approves record the instructor's name from classes.yaml, not a name typed by the client.
"""

import csv
import io
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent import messages
from app.api.admin_documents import embedding_provider
from app.api.deps import Principal, require_staff
from app.channels.registry import get_adapter
from app.core.classes import get_registry
from app.core.redact import redact
from app.db.models import HandoffTicket, TicketStatus
from app.db.session import get_session
from app.ingestion.faq import PromoteError, promote_ticket
from app.providers.base import EmbeddingProvider

router = APIRouter(prefix="/admin/handoffs", tags=["admin"], dependencies=[Depends(require_staff)])

CSV_COLUMNS = [
    "code",
    "id",
    "class_id",
    "created_at",
    "status",
    "reason",
    "confidence",
    "assignee",
    "question",
    "instructor_answer",
    "promoted_to_faq",
    "answered_at",
]


class TicketOut(BaseModel):
    id: int
    code: str
    class_id: str
    created_at: datetime
    updated_at: datetime
    status: str
    reason: str
    confidence: float | None
    check_detail: dict | None
    assignee: str | None
    question: str
    instructor_answer: str | None
    answered_at: datetime | None
    promoted_to_faq: bool
    can_post_to_group: bool  # the question came from a group chat (not /api/ask)

    @classmethod
    def of(cls, t: HandoffTicket) -> "TicketOut":
        return cls(
            id=t.id,
            code=messages.ticket_code(t.id),
            class_id=t.class_id,
            created_at=t.created_at,
            updated_at=t.updated_at,
            status=t.status,
            reason=t.reason,
            confidence=t.confidence,
            check_detail=t.check_detail,
            assignee=t.assignee,
            question=t.question_redacted,
            instructor_answer=t.instructor_answer,
            answered_at=t.answered_at,
            promoted_to_faq=t.promoted_to_faq,
            can_post_to_group=_has_group(t),
        )


class TicketUpdate(BaseModel):
    status: TicketStatus | None = None
    assignee: str | None = Field(default=None, max_length=255)
    instructor_answer: str | None = Field(default=None, max_length=4000)
    post_to_group: bool = False  # send the (saved) answer into the student's group via the adapter


class PromoteRequest(BaseModel):
    """Optional edits before the answer becomes an FAQ entry (defaults: the ticket's question/answer)."""

    question: str | None = Field(default=None, max_length=2000)
    answer: str | None = Field(default=None, max_length=4000)
    approved_by: str | None = Field(default=None, max_length=255)  # admin only; instructor = their own name


def _has_group(t: HandoffTicket) -> bool:
    return bool(t.channel and t.channel != "api" and t.external_group_id)


async def _get_ticket(session: AsyncSession, ticket_id: int, principal: Principal) -> HandoffTicket:
    ticket = await session.get(HandoffTicket, ticket_id)
    if ticket is None or not principal.owns(ticket.class_id):  # never reveal another class's ticket
        raise HTTPException(404, "ticket not found")
    return ticket


def _filtered(class_id: str | None, status: str | None):  # type: ignore[no-untyped-def]
    stmt = select(HandoffTicket).order_by(HandoffTicket.id.desc())
    if class_id:
        stmt = stmt.where(HandoffTicket.class_id == class_id)
    if status:
        stmt = stmt.where(HandoffTicket.status == status)
    return stmt


@router.get("")
async def list_tickets(
    class_id: str | None = None,
    status: TicketStatus | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    session: AsyncSession = Depends(get_session),
    principal: Principal = Depends(require_staff),
) -> list[TicketOut]:
    stmt = _filtered(principal.class_filter(class_id), status)
    rows = (await session.execute(stmt.limit(limit))).scalars()
    return [TicketOut.of(t) for t in rows]


def _csv_cell(value: object) -> str:
    """Neutralise spreadsheet formulas: student text starting with = + - @ would run in Sheets/Excel."""
    text = "" if value is None else str(value)
    return "'" + text if text[:1] in ("=", "+", "-", "@", "\t", "\r") else text


@router.get("/export.csv")
async def export_csv(
    class_id: str | None = None,
    status: TicketStatus | None = None,
    session: AsyncSession = Depends(get_session),
    principal: Principal = Depends(require_staff),
) -> Response:
    class_id = principal.class_filter(class_id)
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(CSV_COLUMNS)
    for t in (await session.execute(_filtered(class_id, status))).scalars():
        row = [
            messages.ticket_code(t.id),
            t.id,
            t.class_id,
            t.created_at.isoformat(),
            t.status,
            t.reason,
            "" if t.confidence is None else round(t.confidence, 4),
            t.assignee,
            t.question_redacted,
            t.instructor_answer,
            t.promoted_to_faq,
            t.answered_at.isoformat() if t.answered_at else "",
        ]
        writer.writerow([_csv_cell(v) for v in row])
    filename = f"handoffs_{class_id or 'all'}.csv"
    return Response(
        content="﻿" + buf.getvalue(),  # BOM: Excel/Sheets read Vietnamese as UTF-8
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/{ticket_id}")
async def get_ticket(
    ticket_id: int,
    session: AsyncSession = Depends(get_session),
    principal: Principal = Depends(require_staff),
) -> TicketOut:
    return TicketOut.of(await _get_ticket(session, ticket_id, principal))


@router.patch("/{ticket_id}")
async def update_ticket(
    ticket_id: int,
    body: TicketUpdate,
    session: AsyncSession = Depends(get_session),
    principal: Principal = Depends(require_staff),
) -> dict[str, object]:
    """Save the instructor's answer / status / assignee; optionally post the answer to the group."""
    ticket = await _get_ticket(session, ticket_id, principal)
    if body.assignee is not None:
        ticket.assignee = body.assignee.strip() or None
    if body.instructor_answer is not None:
        ticket.instructor_answer = redact(body.instructor_answer.strip()).text or None
        if ticket.instructor_answer and body.status is None and ticket.status in ("open", "in_progress"):
            ticket.status = TicketStatus.ANSWERED
    if body.status is not None:
        ticket.status = body.status
    if ticket.status in (TicketStatus.ANSWERED, TicketStatus.CLOSED) and ticket.answered_at is None:
        ticket.answered_at = datetime.now(UTC) if ticket.instructor_answer else None

    if body.post_to_group:
        if not ticket.instructor_answer:
            raise HTTPException(409, "no instructor answer to post")
        if not _has_group(ticket):
            raise HTTPException(409, "ticket did not come from a group chat")
    await session.commit()

    posted = False
    if body.post_to_group:
        text = messages.INSTRUCTOR_REPLY.format(
            ticket=messages.ticket_code(ticket.id),
            question=ticket.question_redacted,
            answer=ticket.instructor_answer,
        )
        try:
            adapter = get_adapter(ticket.channel or "")
        except LookupError as exc:  # e.g. the Zalo stub: cannot send yet
            raise HTTPException(501, "channel cannot send messages yet") from exc
        posted = await adapter.send_reply(
            ticket.external_group_id or "", text, ticket.reply_to, event_id=None, kind="instructor"
        )
    await session.refresh(ticket)
    return {"ticket": TicketOut.of(ticket).model_dump(mode="json"), "posted_to_group": posted}


@router.post("/{ticket_id}/promote")
async def promote(
    ticket_id: int,
    body: PromoteRequest | None = None,
    session: AsyncSession = Depends(get_session),
    embedder: EmbeddingProvider = Depends(embedding_provider),
    principal: Principal = Depends(require_staff),
) -> dict[str, object]:
    """'Duyệt vào FAQ': the answer becomes an active FAQ entry of the ticket's class, indexed immediately."""
    body = body or PromoteRequest()
    ticket = await _get_ticket(session, ticket_id, principal)
    approved_by = body.approved_by if principal.is_admin else principal.name
    class_name = next((c.name for c in get_registry().classes if c.id == ticket.class_id), ticket.class_id)
    try:
        entry, tokens = await promote_ticket(
            session,
            ticket,
            class_name=class_name,
            question=body.question,
            answer=body.answer,
            approved_by=approved_by,
            embedder=embedder,
        )
    except PromoteError as exc:
        raise HTTPException(409, str(exc)) from exc
    return {
        "faq_entry_id": entry.id,
        "class_id": entry.class_id,
        "question": entry.question,
        "answer": entry.answer,
        "approved_by": entry.approved_by,
        "embedding_tokens": tokens,
    }
