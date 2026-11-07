"""Synchronous part of message handling (webhook, ARCHITECTURE §2): dedupe, filter, rate limit, enqueue.

Kept free of HTTP concerns so it can be reused by every channel adapter.
"""

import logging
import time
import unicodedata
from dataclasses import dataclass

from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent import messages
from app.channels.base import IncomingMessage
from app.core.config import Settings
from app.core.ratelimit import check_rate
from app.core.redact import redact
from app.core.security import hash_user_id
from app.db import repositories as repo
from app.db.models import Outcome, SecurityEventType
from app.workers.queue import JobQueue, MessageJob, NoticeJob

logger = logging.getLogger(__name__)

QUEUED = "queued"


@dataclass(frozen=True)
class IngressResult:
    status: str  # queued | duplicate | ignored | rate_limited
    reason: str | None = None
    class_id: str | None = None


# Allowed right after the trigger, as in "@Trợ lý, cho em hỏi ..." or "@Trợ lý: ...".
TRIGGER_SEPARATORS = ",:;"


def extract_question(text: str, prefixes: list[str]) -> str | None:
    """Return the question after a trigger at the start of the message ("@Trợ lý ...", "/hoi ..."), else None.

    Case-insensitive and Unicode-normalised (NFC): a decomposed "lý" from another keyboard still matches.
    The trigger must not run into a letter or digit: "/hoian" and "@Trợ lýx" are not triggers.
    """
    stripped = unicodedata.normalize("NFC", text).strip()
    for prefix in prefixes:
        p = unicodedata.normalize("NFC", prefix.strip())
        if not p or stripped[: len(p)].casefold() != p.casefold():
            continue
        rest = stripped[len(p) :]
        if rest and (rest[0].isalnum() or rest[0] == "_"):
            continue
        rest = rest.strip()
        if rest[:1] in tuple(TRIGGER_SEPARATORS):
            rest = rest[1:].strip()
        return rest
    return None


async def handle_incoming(
    msg: IncomingMessage,
    *,
    session: AsyncSession,
    redis: Redis,
    queue: JobQueue,
    settings: Settings,
    request_id: str,
) -> IngressResult:
    """Run steps 3–6. Every non-queued outcome is written to request_logs here;
    queued messages are logged by the worker once processed."""
    started = time.perf_counter()

    # 3. Idempotency: committed immediately so a concurrent duplicate sees it.
    if await repo.claim_event(session, msg.channel, msg.event_id):
        result = await _decide(msg, session, redis, queue, settings, request_id)
        await repo.set_event_status(session, msg.channel, msg.event_id, result.status)
    else:
        result = IngressResult(Outcome.DUPLICATE)

    if result.status != QUEUED:
        repo.add_request_log(
            session,
            request_id=request_id,
            class_id=result.class_id,
            channel=msg.channel,
            event_id=msg.event_id,
            outcome=result.status,
            cost_usd=0,  # no provider call before the queue
            latency_ms=round((time.perf_counter() - started) * 1000),
        )
    await session.commit()
    logger.info(
        "ingress",
        extra={
            "fields": {
                "event_id": msg.event_id,
                "status": result.status,
                "reason": result.reason,
                "class_id": result.class_id,
            }
        },
    )
    return result


async def _decide(
    msg: IncomingMessage,
    session: AsyncSession,
    redis: Redis,
    queue: JobQueue,
    settings: Settings,
    request_id: str,
) -> IngressResult:
    # 4. Ignore rules (bot loop prevention, trigger, class mapping, class switch).
    if msg.is_from_bot:
        return IngressResult(Outcome.IGNORED, "from_bot")
    question = extract_question(msg.text, settings.trigger_prefixes)
    if question is None:
        return IngressResult(Outcome.IGNORED, "no_trigger")
    if not question:
        return IngressResult(Outcome.IGNORED, "empty_question")
    klass = await repo.resolve_class(session, msg.channel, msg.group_id)
    if klass is None:
        return IngressResult(Outcome.IGNORED, "unmapped_group")
    if not klass.enabled:
        return IngressResult(Outcome.IGNORED, "class_disabled", klass.id)

    user_hash = hash_user_id(msg.user_id, settings.user_hash_salt.get_secret_value())

    # Secrets never leave this function unmasked: not into Redis, the DB, logs or the LLM (D-27b).
    redaction = redact(question)
    question = redaction.text
    if redaction.found:
        repo.add_security_event(
            session,
            SecurityEventType.SECRET_IN_MESSAGE,
            request_id=request_id,
            class_id=klass.id,
            user_hash=user_hash,
            detail="kinds=" + ",".join(sorted(set(redaction.kinds))),
        )

    # 5. Rate limit; at most one notice per scope per window.
    decision = await check_rate(
        redis, klass.id, user_hash, settings.rate_limit_user_per_min, settings.rate_limit_class_per_min
    )
    if not decision.allowed:
        if decision.notify:
            repo.add_security_event(
                session,
                SecurityEventType.RATE_LIMITED,
                request_id=request_id,
                class_id=klass.id,
                user_hash=user_hash,
                detail=f"scope={decision.scope}",
            )
            text = messages.RATE_LIMITED_USER if decision.scope == "user" else messages.RATE_LIMITED_CLASS
            notice = NoticeJob(
                channel=msg.channel,
                event_id=msg.event_id,
                group_id=msg.group_id,
                text=text,
                reply_to=msg.msg_id,
            )
            try:
                await queue.enqueue_notice(notice)
            except Exception:
                # A lost courtesy notice is acceptable; the message stays rate limited.
                logger.warning("rate-limit notice not enqueued", exc_info=True)
        return IngressResult(Outcome.RATE_LIMITED, decision.scope, klass.id)

    # 6. Hand over to the worker.
    job = MessageJob(
        request_id=request_id,
        channel=msg.channel,
        event_id=msg.event_id,
        group_id=msg.group_id,
        class_id=klass.id,
        user_hash=user_hash,
        question=question,
        secret_detected=redaction.found,
        msg_id=msg.msg_id,
        received_at_ms=int(time.time() * 1000),
    )
    try:
        await queue.enqueue_message(job)
    except Exception:
        # Let the platform retry: forget the event, surface the failure to the caller.
        await session.rollback()
        await repo.release_event(session, msg.channel, msg.event_id)
        raise
    return IngressResult(QUEUED, class_id=klass.id)
