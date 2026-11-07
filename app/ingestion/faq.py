"""Instructor-approved FAQ entries: promote a ticket's answer, keep entries in step with the material.

The entry always belongs to the ticket's class (decided server-side when the ticket was created from the
group_id), never to a class chosen by the caller. Embedding happens before any write, so a provider error
leaves nothing half-done; entry + chunk (+ ticket flag) are committed in one transaction.

When a class's material changes, its active entries are flagged `needs_review` (D-89): an approved answer may
now contradict the new version. An instructor then confirms, edits or deactivates each one.
A deactivated entry is no longer retrievable (search filters on `active`).
"""

import logging
from collections.abc import Callable
from datetime import UTC, datetime

from sqlalchemy import delete, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.redact import redact
from app.db.models import Chunk, FaqEntry, HandoffTicket, SourceType
from app.ingestion.injection import find_injection
from app.ingestion.text import estimate_tokens
from app.providers.base import EmbeddingProvider, check_dimensions

logger = logging.getLogger("app")


class PromoteError(ValueError):
    """The ticket cannot be promoted (no answer yet, already promoted)."""


class FaqUpdateError(ValueError):
    """The requested FAQ change is invalid (empty question or answer)."""


def faq_location(entry_id: int) -> str:
    """Location shown in the sources line ('FAQ đã duyệt (FAQ giảng viên #7)')."""
    return f"FAQ giảng viên #{entry_id}"


def faq_chunk_text(class_name: str, question: str, answer: str) -> str:
    """Same shape as document chunks: a context line, then the content."""
    return f"[FAQ đã duyệt của lớp {class_name}]\nCâu hỏi: {question}\nTrả lời: {answer}"


def _faq_chunk(entry: FaqEntry, content: str, vector: list[float]) -> tuple[Chunk, bool]:
    flagged = find_injection(content) is not None
    chunk = Chunk(
        faq_entry_id=entry.id,
        class_id=entry.class_id,
        source_type=SourceType.FAQ,
        section_code=None,
        location=faq_location(entry.id),
        content=content,
        token_count=estimate_tokens(content),
        embedding=vector,
        flagged_injection=flagged,
    )
    return chunk, flagged


async def _embed_one(embedder: EmbeddingProvider, content: str) -> tuple[list[float], int]:
    result = await embedder.embed([content], "document")
    check_dimensions(result.vectors, embedder.dim)
    return result.vectors[0], result.tokens


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
    vector, tokens = await _embed_one(embedder, content)

    entry = FaqEntry(
        class_id=ticket.class_id,
        question=question,
        answer=answer,
        source="instructor",
        source_ticket_id=ticket.id,
        approved_by=approved_by or ticket.assignee,
        approved_at=datetime.now(UTC),
        active=True,
        embedding_tokens=tokens,
        embedding_model=embedder.model,
    )
    session.add(entry)
    await session.flush()  # entry.id for the location
    chunk, flagged = _faq_chunk(entry, content, vector)
    session.add(chunk)
    ticket.promoted_to_faq = True
    await session.commit()
    logger.info(
        "faq promoted",
        extra={
            "fields": {
                "faq_entry_id": entry.id,
                "ticket_id": ticket.id,
                "class_id": ticket.class_id,
                "flagged": flagged,
                "embedding_tokens": tokens,
            }
        },
    )
    return entry, tokens


async def flag_faqs_for_review(session: AsyncSession, scope: str, shared_scope: str, reason: str) -> int:
    """Mark the active FAQ entries fed by `scope` as needing review; returns how many. Does not commit.

    A class's entries depend on that class's material; every class also reads the shared scope, so a change
    there flags the entries of all classes."""
    conditions = [FaqEntry.active.is_(True)]
    if scope != shared_scope:
        conditions.append(FaqEntry.class_id == scope)
    result = await session.execute(
        update(FaqEntry)
        .where(*conditions)
        .values(needs_review=True, review_reason=reason[:255])
        .execution_options(synchronize_session=False)
    )
    flagged = int(result.rowcount or 0)  # type: ignore[attr-defined]
    if flagged:
        logger.info("faq flagged for review", extra={"fields": {"scope": scope, "faq_entries": flagged}})
    return flagged


async def update_faq(
    session: AsyncSession,
    entry: FaqEntry,
    *,
    class_name: str,
    editor: str,
    embedder_factory: Callable[[], EmbeddingProvider],
    question: str | None = None,
    answer: str | None = None,
    active: bool | None = None,
) -> int:
    """Apply an instructor's decision on one entry; returns embedding tokens spent (0 unless text changed).

    - new question/answer: redacted, re-embedded first (`embedder_factory` is only called then), and the chunk
      is replaced in the same transaction; counts as a fresh approval by `editor`.
    - active=False: no longer retrievable. active=True: served again.
    - Every decision, including "still correct" (no field changed), clears the needs-review flag."""
    new_q = redact(question.strip()).text if question is not None else entry.question
    new_a = redact(answer.strip()).text if answer is not None else entry.answer
    if not new_q or not new_a:
        raise FaqUpdateError("question and answer must not be empty")

    tokens = 0
    if (new_q, new_a) != (entry.question, entry.answer):
        embedder = embedder_factory()
        content = faq_chunk_text(class_name, new_q, new_a)
        vector, tokens = await _embed_one(embedder, content)  # before any write
        await session.execute(delete(Chunk).where(Chunk.faq_entry_id == entry.id))
        chunk, _ = _faq_chunk(entry, content, vector)
        session.add(chunk)
        entry.question, entry.answer = new_q, new_a
        entry.approved_by, entry.approved_at = editor, datetime.now(UTC)
        entry.embedding_tokens += tokens
        entry.embedding_model = embedder.model
    if active is not None:
        entry.active = active
    entry.needs_review, entry.review_reason = False, None
    entry.updated_at = datetime.now(UTC)
    await session.commit()
    logger.info(
        "faq updated",
        extra={"fields": {"faq_entry_id": entry.id, "class_id": entry.class_id, "active": entry.active,
                          "embedding_tokens": tokens}},
    )  # fmt: skip
    return tokens
