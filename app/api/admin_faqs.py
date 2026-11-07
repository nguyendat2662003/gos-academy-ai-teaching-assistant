"""Admin API for approved FAQ entries: list, confirm, edit, deactivate / reactivate (X-Admin-Key, D-89).

When a class's material changes, its FAQ entries are flagged "needs review" by the indexer; this is where an
instructor clears the flag. Roles (D-83): an instructor key sees and changes only its own class's entries
(another class's entry answers 404); an edit is recorded as approved by that instructor.
"""

from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.admin_documents import embedding_provider
from app.api.deps import Principal, require_staff
from app.core.classes import get_registry
from app.db.models import FaqEntry
from app.db.session import get_session
from app.ingestion.faq import FaqUpdateError, update_faq

router = APIRouter(prefix="/admin/faqs", tags=["admin"], dependencies=[Depends(require_staff)])

FaqStatus = Literal["active", "inactive", "review"]


class FaqOut(BaseModel):
    id: int
    class_id: str
    question: str
    answer: str
    source: str
    source_ticket_id: int | None
    approved_by: str | None
    approved_at: datetime | None
    active: bool
    needs_review: bool
    review_reason: str | None
    created_at: datetime
    updated_at: datetime | None

    @classmethod
    def of(cls, e: FaqEntry) -> "FaqOut":
        return cls(
            id=e.id,
            class_id=e.class_id,
            question=e.question,
            answer=e.answer,
            source=e.source,
            source_ticket_id=e.source_ticket_id,
            approved_by=e.approved_by,
            approved_at=e.approved_at,
            active=e.active,
            needs_review=e.needs_review,
            review_reason=e.review_reason,
            created_at=e.created_at,
            updated_at=e.updated_at,
        )


class FaqUpdate(BaseModel):
    """At least one field. `reviewed: true` alone = "still correct with the new material"."""

    question: str | None = Field(default=None, min_length=1, max_length=2000)
    answer: str | None = Field(default=None, min_length=1, max_length=4000)
    active: bool | None = None
    reviewed: bool | None = None


@router.get("")
async def list_faqs(
    class_id: str | None = None,
    status: FaqStatus | None = None,
    limit: int = 200,
    session: AsyncSession = Depends(get_session),
    principal: Principal = Depends(require_staff),
) -> list[FaqOut]:
    """Entries needing review first, then newest first."""
    stmt = select(FaqEntry).order_by(FaqEntry.needs_review.desc(), FaqEntry.id.desc()).limit(min(limit, 500))
    if scope := principal.class_filter(class_id):
        stmt = stmt.where(FaqEntry.class_id == scope)
    if status == "active":
        stmt = stmt.where(FaqEntry.active.is_(True))
    elif status == "inactive":
        stmt = stmt.where(FaqEntry.active.is_(False))
    elif status == "review":
        stmt = stmt.where(FaqEntry.active.is_(True), FaqEntry.needs_review.is_(True))
    return [FaqOut.of(e) for e in (await session.execute(stmt)).scalars()]


@router.patch("/{faq_id}")
async def patch_faq(
    faq_id: int,
    body: FaqUpdate,
    session: AsyncSession = Depends(get_session),
    principal: Principal = Depends(require_staff),
) -> FaqOut:
    entry = await session.get(FaqEntry, faq_id)
    if entry is None or not principal.owns(entry.class_id):
        raise HTTPException(404, "faq entry not found")
    if body.question is None and body.answer is None and body.active is None and not body.reviewed:
        raise HTTPException(422, "nothing to change")
    class_name = next(c.name for c in get_registry().classes if c.id == entry.class_id)
    try:
        await update_faq(
            session,
            entry,
            class_name=class_name,
            editor=principal.name,
            question=body.question,
            answer=body.answer,
            active=body.active,
            embedder_factory=embedding_provider,
        )
    except FaqUpdateError as exc:
        raise HTTPException(422, str(exc)) from exc
    await session.refresh(entry)
    return FaqOut.of(entry)
