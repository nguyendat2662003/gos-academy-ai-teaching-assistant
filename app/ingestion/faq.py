"""Instructor-approved FAQ entries (CLAUDE.md §10): promote a ticket's answer and index it at once.

The entry always belongs to the ticket's class (decided server-side when the ticket was created from the
group_id), never to a class chosen by the caller. Embedding happens before any write, so a provider error
leaves nothing half-done; entry + chunk + ticket flag are committed in one transaction.
"""

import logging
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.redact import redact
from app.db.models import Chunk, FaqEntry, HandoffTicket, SourceType
from app.ingestion.injection import find_injection
from app.ingestion.text import estimate_tokens
from app.providers.base import EmbeddingProvider, check_dimensions

logger = logging.getLogger("app")


class PromoteError(ValueError):
    """The ticket cannot be promoted (no answer yet, already promoted)."""


def faq_location(entry_id: int) -> str:
    """Location shown in the sources line ('FAQ đã duyệt (FAQ giảng viên #7)')."""
    return f"FAQ giảng viên #{entry_id}"


def faq_chunk_text(class_name: str, question: str, answer: str) -> str:
    """Same shape as document chunks: a context line, then the content."""
    return f"[FAQ đã duyệt của lớp {class_name}]\nCâu hỏi: {question}\nTrả lời: {answer}"


async def promote_ticket(
    session: AsyncSession,
    ticket: HandoffTicket,
    *,
    class_name: str,
    question: str | None,
    answer: str | None,
    approved_by: str | None,
    embedder: EmbeddingProvider,
) -> tuple[FaqEntry, int]:
    """Create an active FAQ entry from the ticket and index it for the ticket's class.

    Returns (entry, embedding_tokens). Question/answer default to the ticket's; both are redacted."""
    if ticket.promoted_to_faq:
        raise PromoteError("already_promoted")
    question = redact((question or ticket.question_redacted).strip()).text
    answer = redact((answer or ticket.instructor_answer or "").strip()).text
    if not question or not answer:
        raise PromoteError("missing_answer")

    content = faq_chunk_text(class_name, question, answer)
    result = await embedder.embed([content], "document")
    check_dimensions(result.vectors, embedder.dim)

    entry = FaqEntry(
        class_id=ticket.class_id,
        question=question,
        answer=answer,
        source="instructor",
        source_ticket_id=ticket.id,
        approved_by=approved_by or ticket.assignee,
        approved_at=datetime.now(UTC),
        active=True,
        embedding_tokens=result.tokens,
        embedding_model=embedder.model,
    )
    session.add(entry)
    await session.flush()  # entry.id for the location
    rule = find_injection(content)
    session.add(
        Chunk(
            faq_entry_id=entry.id,
            class_id=ticket.class_id,
            source_type=SourceType.FAQ,
            section_code=None,
            location=faq_location(entry.id),
            content=content,
            token_count=estimate_tokens(content),
            embedding=result.vectors[0],
            flagged_injection=rule is not None,
        )
    )
    ticket.promoted_to_faq = True
    await session.commit()
    logger.info(
        "faq promoted",
        extra={
            "fields": {
                "faq_entry_id": entry.id,
                "ticket_id": ticket.id,
                "class_id": ticket.class_id,
                "flagged": rule is not None,
                "embedding_tokens": result.tokens,
            }
        },
    )
    return entry, result.tokens
