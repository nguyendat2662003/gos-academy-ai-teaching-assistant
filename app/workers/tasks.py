"""arq tasks (asynchronous part of CLAUDE.md §5). Every task is idempotent per (channel, event_id)."""

import logging
import time
from typing import Any

from app.agent import messages
from app.channels.registry import get_adapter
from app.core.logging import request_id_var
from app.db import repositories as repo
from app.db.models import Outcome
from app.db.session import get_sessionmaker
from app.workers.queue import MessageJob, NoticeJob

logger = logging.getLogger(__name__)


async def process_message(_ctx: dict[str, Any], payload: dict[str, Any]) -> str:
    """Answer one queued question. Phase 2: echo placeholder; replaced by the RAG agent in Phase 4."""
    job = MessageJob.model_validate(payload)
    token = request_id_var.set(job.request_id)
    try:
        adapter = get_adapter(job.channel)
        text = messages.ECHO_RECEIVED.format(question=job.question)
        sent = await adapter.send_reply(job.group_id, text, job.msg_id, event_id=job.event_id, kind="answer")
        if not sent:
            # A previous attempt already replied (retry after a crash): nothing more to do.
            logger.info("already replied", extra={"fields": {"event_id": job.event_id}})
            return "already_sent"

        async with get_sessionmaker()() as session:
            repo.add_request_log(
                session,
                request_id=job.request_id,
                class_id=job.class_id,
                channel=job.channel,
                event_id=job.event_id,
                outcome=Outcome.ANSWERED,
                model="echo",
                latency_ms=int(time.time() * 1000) - job.received_at_ms,
            )
            await repo.set_event_status(session, job.channel, job.event_id, Outcome.ANSWERED)
            await session.commit()
        logger.info("replied", extra={"fields": {"event_id": job.event_id, "class_id": job.class_id}})
        return Outcome.ANSWERED
    finally:
        request_id_var.reset(token)


async def send_notice(_ctx: dict[str, Any], payload: dict[str, Any]) -> bool:
    """Deliver a fixed notice (e.g. rate limit). At most one per event thanks to the outbox key."""
    job = NoticeJob.model_validate(payload)
    return await get_adapter(job.channel).send_reply(
        job.group_id, job.text, job.reply_to, event_id=job.event_id, kind=job.kind
    )
