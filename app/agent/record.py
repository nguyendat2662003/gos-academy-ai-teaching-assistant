"""Persist what happened after a reply was delivered: conversation turns + request log (+ event status)."""

from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.conversation import add_exchange
from app.agent.pipeline import AgentReply, AgentRequest
from app.core.pricing import get_pricing
from app.db import repositories as repo


async def record_reply(
    session: AsyncSession,
    request: AgentRequest,
    reply: AgentReply,
    *,
    latency_ms: int,
    event_id: str | None,
) -> None:
    """Only called once the reply is actually sent (or returned), so a retried job does not double-log."""
    if reply.outcome != "refused":  # refusals are not useful context for follow-up questions
        add_exchange(
            session,
            class_id=request.class_id,
            user_hash=request.user_hash,
            question=reply.standalone_question or request.question,
            reply=reply.answer_body,
        )
    repo.add_request_log(
        session,
        request_id=request.request_id,
        class_id=request.class_id,
        channel=request.channel,
        event_id=event_id,
        outcome=reply.outcome,
        handoff_reason=reply.handoff_reason,
        retrieval_top_score=reply.top_score,
        cited_chunk_ids=reply.cited_refs or None,
        model=reply.model,
        input_tokens=reply.input_tokens,
        output_tokens=reply.output_tokens,
        embedding_tokens=reply.embedding_tokens,
        embedding_model=reply.embedding_model,
        # snapshot at write time (None if a price is not filled in yet); stats re-price from tokens
        cost_usd=get_pricing().request_cost(
            model=reply.model,
            input_tokens=reply.input_tokens,
            output_tokens=reply.output_tokens,
            embedding_model=reply.embedding_model,
            embedding_tokens=reply.embedding_tokens,
        ),
        latency_ms=latency_ms,
        error_code=reply.error_code,
    )
    if event_id and request.channel:
        await repo.set_event_status(session, request.channel, event_id, reply.outcome)
    await session.commit()
