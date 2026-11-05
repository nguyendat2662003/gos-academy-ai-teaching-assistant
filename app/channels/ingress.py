"""Synchronous part of message handling (CLAUDE.md §5 steps 3–6): dedupe, filter, rate limit, enqueue.

Kept free of HTTP concerns so it can be reused by every channel adapter.
"""

import logging
import time
from dataclasses import dataclass

from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent import messages
from app.channels.base import IncomingMessage
from app.core.config import Settings
from app.core.ratelimit import check_rate
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


def extract_question(text: str, prefixes: list[str]) -> str | None:
    """Return the question after a trigger prefix ("/hoi ..."), or None if the message has no trigger.

    The prefix must be followed by whitespace or end the message, so "/hoian" is not a trigger.
    """
    stripped = text.strip()
    lowered = stripped.lower()
    for prefix in prefixes:
        p = prefix.lower()
        if lowered.startswith(p) and (len(stripped) == len(p) or stripped[len(p)].isspace()):
            return stripped[len(p) :].strip()
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
