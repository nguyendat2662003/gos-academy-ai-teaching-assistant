"""POST /api/ask — direct question/answer for trusted server-to-server callers (X-API-Key, CLAUDE.md §9).

The caller is trusted to have authenticated the student and to pass the right class_id. Same pipeline,
same redaction and guard as the chat channel; nothing is posted to a group.
"""

import time

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.pipeline import AgentRequest, answer_question
from app.agent.record import record_reply
from app.core.classes import get_registry
from app.core.config import get_settings
from app.core.logging import request_id_var
from app.core.redact import redact
from app.core.security import constant_time_equals, hash_user_id
from app.db import repositories as repo
from app.db.models import ClassRoom, SecurityEventType
from app.db.session import get_session
from app.providers.registry import ProviderConfigError, get_embedding_provider, get_llm_provider

router = APIRouter(prefix="/api", tags=["ask"])


class AskRequest(BaseModel):
    class_id: str
    user_id: str = Field(min_length=1, max_length=255)
    question: str = Field(min_length=1, max_length=2000)


class AskResponse(BaseModel):
    request_id: str
    outcome: str
    answer: str
    handoff_reason: str | None
    ticket_id: int | None
    cited_chunk_ids: list[str]


async def require_ask_key(x_api_key: str | None = Header(default=None)) -> None:
    if not constant_time_equals(x_api_key, get_settings().ask_api_key.get_secret_value()):
        raise HTTPException(401, "invalid api key")


@router.post("/ask", dependencies=[Depends(require_ask_key)])
async def ask(body: AskRequest, session: AsyncSession = Depends(get_session)) -> AskResponse:
    started = time.perf_counter()
    settings, registry = get_settings(), get_registry()
    klass = await session.get(ClassRoom, body.class_id)
    if klass is None or klass.is_shared:
        raise HTTPException(404, "class not found")
    if not klass.enabled:
        raise HTTPException(409, "bot is disabled for this class")
    try:
        llm, embedder = get_llm_provider(), get_embedding_provider()
    except ProviderConfigError as exc:
        raise HTTPException(503, str(exc)) from exc

    request_id = request_id_var.get() or ""
    user_hash = hash_user_id(body.user_id, settings.user_hash_salt.get_secret_value())
    redaction = redact(body.question)
    if redaction.found:
        repo.add_security_event(
            session, SecurityEventType.SECRET_IN_MESSAGE, request_id=request_id, class_id=body.class_id,
            user_hash=user_hash, detail="kinds=" + ",".join(sorted(set(redaction.kinds))),
        )  # fmt: skip
        await session.commit()
    request = AgentRequest(
        request_id=request_id,
        class_id=body.class_id,
        user_hash=user_hash,
        question=redaction.text,
        channel="api",
        secret_detected=redaction.found,
    )
    reply = await answer_question(
        session, request, llm=llm, embedder=embedder, registry=registry, settings=settings
    )
    latency = round((time.perf_counter() - started) * 1000)
    await record_reply(session, request, reply, latency_ms=latency, event_id=None)
    return AskResponse(
        request_id=request_id,
        outcome=reply.outcome,
        answer=reply.text,
        handoff_reason=reply.handoff_reason,
        ticket_id=reply.ticket_id,
        cited_chunk_ids=reply.cited_refs,
    )
