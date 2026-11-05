"""arq tasks (asynchronous part of CLAUDE.md §5). Every task is idempotent per (channel, event_id)."""

import logging
import time
from typing import Any

from app.agent.pipeline import AgentRequest, answer_question
from app.agent.record import record_reply
from app.channels.registry import get_adapter
from app.core.classes import get_registry
from app.core.config import get_settings
from app.core.logging import request_id_var
from app.db import repositories as repo
from app.db.session import get_sessionmaker
from app.providers.registry import get_embedding_provider, get_llm_provider
from app.workers.queue import MessageJob, NoticeJob

logger = logging.getLogger(__name__)


async def process_message(_ctx: dict[str, Any], payload: dict[str, Any]) -> str:
    """Answer one queued question with the RAG agent and deliver it through the channel adapter."""
    job = MessageJob.model_validate(payload)
    token = request_id_var.set(job.request_id)
    try:
        async with get_sessionmaker()() as session:
            # A retry after the reply went out must not call the LLM (cost) nor reply twice.
            if await repo.outbox_has_event(session, job.channel, job.event_id):
                logger.info("already replied", extra={"fields": {"event_id": job.event_id}})
                return "already_sent"
            request = AgentRequest(
                request_id=job.request_id,
                class_id=job.class_id,
                user_hash=job.user_hash,
                question=job.question,
                channel=job.channel,
                group_id=job.group_id,
                reply_to=job.msg_id,
                secret_detected=job.secret_detected,
            )
            reply = await answer_question(
                session,
                request,
                llm=get_llm_provider(),
                embedder=get_embedding_provider(),
                registry=get_registry(),
                settings=get_settings(),
            )

        sent = await get_adapter(job.channel).send_reply(
            job.group_id, reply.text, job.msg_id, event_id=job.event_id, kind=reply.kind
        )
        if not sent:
            return "already_sent"
        async with get_sessionmaker()() as session:
            latency = int(time.time() * 1000) - job.received_at_ms
            await record_reply(session, request, reply, latency_ms=latency, event_id=job.event_id)
        logger.info(
            "replied",
            extra={
                "fields": {
                    "event_id": job.event_id,
                    "class_id": job.class_id,
                    "outcome": reply.outcome,
                    "handoff_reason": reply.handoff_reason,
                    "top_score": reply.top_score,
                }
            },
        )
        return reply.outcome
    finally:
        request_id_var.reset(token)


async def send_notice(_ctx: dict[str, Any], payload: dict[str, Any]) -> bool:
    """Deliver a fixed notice (e.g. rate limit). At most one per event thanks to the outbox key."""
    job = NoticeJob.model_validate(payload)
    return await get_adapter(job.channel).send_reply(
        job.group_id, job.text, job.reply_to, event_id=job.event_id, kind=job.kind
    )
