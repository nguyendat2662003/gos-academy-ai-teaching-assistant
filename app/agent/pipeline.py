"""Answer one student question (worker, ARCHITECTURE §2). Channel-agnostic: returns the reply, sends nothing.

redact → guard → greeting/thanks → history → rewrite → policy → retrieve → threshold → LLM (retry)
→ verify → compose
"""

import logging
from dataclasses import dataclass, field

from sqlalchemy.ext.asyncio import AsyncSession

from app.agent import messages
from app.agent.conversation import load_history
from app.agent.guard import check_question
from app.agent.handoff import open_ticket
from app.agent.policy import is_policy_evidence, sensitive_topic
from app.agent.prompts import RewriteResult, build_answer_messages, build_rewrite_messages
from app.agent.smalltalk import classify_smalltalk
from app.agent.sources import format_sources
from app.agent.verify import verify_answer
from app.core.classes import ClassRegistry
from app.core.config import Settings
from app.core.redact import redact
from app.db import repositories as repo
from app.db.models import HandoffReason, Outcome, SecurityEventType
from app.providers.base import EmbeddingProvider, LLMProvider, LLMResult, Message
from app.providers.retry import complete_with_retry
from app.retrieval.search import hybrid_search

logger = logging.getLogger(__name__)

_REFUSALS = {
    SecurityEventType.PROMPT_INJECTION: messages.REFUSED_INJECTION,
    SecurityEventType.SECRET_EXFILTRATION: messages.REFUSED_SECRET,
    SecurityEventType.CROSS_CLASS_REQUEST: messages.REFUSED_CROSS_CLASS,
}
_HANDOFF_TEXT = {
    HandoffReason.NO_CONTEXT: messages.HANDOFF_NO_CONTEXT,
    HandoffReason.POLICY: messages.HANDOFF_POLICY,
    HandoffReason.LOW_CONFIDENCE: messages.HANDOFF_LOW_CONFIDENCE,
    HandoffReason.ERROR: messages.ERROR_FRIENDLY,
}


@dataclass
class AgentRequest:
    request_id: str
    class_id: str  # resolved server-side from the group (or authenticated caller for /api/ask)
    user_hash: str
    question: str
    channel: str | None = None
    group_id: str | None = None
    reply_to: str | None = None
    secret_detected: bool = False


@dataclass
class AgentReply:
    outcome: str
    text: str  # full message for the group (answer + sources + notes)
    kind: str  # outbox kind: answer | partial | handoff | refusal | error
    answer_body: str  # what is kept in conversation history (no sources line)
    handoff_reason: str | None = None
    ticket_id: int | None = None
    top_score: float | None = None
    cited_refs: list[str] = field(default_factory=list)
    model: str | None = None
    input_tokens: int = 0
    output_tokens: int = 0
    embedding_tokens: int = 0
    embedding_model: str | None = None
    error_code: str | None = None
    standalone_question: str | None = None


@dataclass
class _Usage:
    model: str | None = None
    input_tokens: int = 0
    output_tokens: int = 0
    embedding_tokens: int = 0
    embedding_model: str | None = None

    def add(self, result: LLMResult) -> None:
        self.model = result.model
        self.input_tokens += result.input_tokens
        self.output_tokens += result.output_tokens


async def answer_question(
    session: AsyncSession,
    request: AgentRequest,
    *,
    llm: LLMProvider,
    embedder: EmbeddingProvider,
    registry: ClassRegistry,
    settings: Settings,
) -> AgentReply:
    usage = _Usage()
    redaction = redact(request.question)  # idempotent second pass (first one ran at the webhook)
    question = redaction.text
    secret = request.secret_detected or redaction.found

    async def handoff(
        reason: str, *, top: float | None, detail: dict, error: str | None = None
    ) -> AgentReply:
        ticket = await _ticket(session, request, registry, question, reason, top, detail)
        text = messages.pick(_HANDOFF_TEXT[reason], ticket).format(ticket=messages.ticket_code(ticket))
        outcome = Outcome.ERROR if reason == HandoffReason.ERROR else Outcome.HANDOFF
        return _reply(outcome, text, "error" if error else "handoff", secret, usage, reason=reason,
                      ticket=ticket, top=top, error=error)  # fmt: skip

    # 8. Guard
    verdict = check_question(question, request.class_id, registry)
    if verdict.blocked and verdict.event_type is not None:
        repo.add_security_event(
            session, verdict.event_type, request_id=request.request_id, class_id=request.class_id,
            user_hash=request.user_hash, detail=f"rule={verdict.rule}",
        )  # fmt: skip
        await session.commit()
        return _reply(Outcome.REFUSED, _REFUSALS[verdict.event_type], "refusal", secret, usage)

    # Greeting / thanks only: friendly fixed reply, no retrieval, no LLM, no ticket (D-87)
    talk = classify_smalltalk(question)
    if talk is not None:
        template = messages.SMALLTALK_GREETING if talk == "greeting" else messages.SMALLTALK_THANKS
        class_name = next(c.name for c in registry.classes if c.id == request.class_id)
        trigger = settings.trigger_prefixes[0] if settings.trigger_prefixes else "/hoi"
        text = template.format(class_name=class_name, trigger=trigger)
        return _reply(Outcome.SMALLTALK, text, "smalltalk", secret, usage)

    # 10. Follow-up questions -> standalone question
    history = await load_history(
        session, class_id=request.class_id, user_hash=request.user_hash,
        max_turns=settings.context_max_turns, ttl_minutes=settings.context_ttl_minutes,
    )  # fmt: skip
    standalone = await _rewrite(question, history, llm, settings, usage)

    # 11. Retrieval (class-scoped)
    retrieval = await hybrid_search(
        session, class_id=request.class_id, question=standalone, embedder=embedder,
        registry=registry, top_k=settings.retrieval_top_k,
    )  # fmt: skip
    usage.embedding_tokens += retrieval.embedding_tokens
    usage.embedding_model = embedder.model
    top = retrieval.top_vector_score
    chunks = retrieval.chunks

    # 9. Sensitive topics: only with concrete policy evidence
    topic = sensitive_topic(standalone)
    if topic and not any(is_policy_evidence(c.content, topic) for c in chunks):
        return _with_question(
            await handoff(HandoffReason.POLICY, top=top, detail={"topic": topic}), standalone
        )

    # 12. Relevance threshold: below it the LLM is not called at all
    if top is None or top < settings.retrieval_min_score or not chunks:
        detail = {"top_score": top, "min_score": settings.retrieval_min_score}
        return _with_question(await handoff(HandoffReason.NO_CONTEXT, top=top, detail=detail), standalone)

    # 13. Generate (with timeout + retry)
    class_name = next(c.name for c in registry.classes if c.id == request.class_id)
    prompt = build_answer_messages(class_name, chunks, standalone, history)
    try:
        result = await _complete(llm, prompt, settings)
    except Exception as exc:  # retries exhausted, permanent error, or provider bug
        logger.error(
            "llm failed", extra={"fields": {"error": type(exc).__name__, "class_id": request.class_id}}
        )
        reply = await handoff(HandoffReason.ERROR, top=top, detail={"error": type(exc).__name__},
                              error=type(exc).__name__)  # fmt: skip
        return _with_question(reply, standalone)
    usage.add(result)

    # 14. Verify
    by_ref = {c.ref: c for c in chunks}
    check = verify_answer(result.text, set(by_ref))
    if not check.ok or check.answer is None:
        detail = {"problems": check.problems, "top_score": top}
        return _with_question(await handoff(HandoffReason.LOW_CONFIDENCE, top=top, detail=detail), standalone)

    # 15. Compose: answer + (partial note) + sources from metadata
    answer = check.answer
    cited = [by_ref[ref] for ref in dict.fromkeys(answer.cited_chunk_ids)]
    body = answer.answer.strip()
    parts = [body]
    outcome, kind, reason, ticket = Outcome.ANSWERED, "answer", None, None
    if answer.unanswered_parts:
        reason = HandoffReason.PARTIAL_COVERAGE
        detail = {
            "unanswered_parts": answer.unanswered_parts,
            "notes": answer.notes_for_instructor,
            "top_score": top,
        }
        ticket = await _ticket(session, request, registry, standalone, reason, top, detail)
        missing = ", ".join(f"“{p}”" for p in answer.unanswered_parts)
        parts.append(messages.PARTIAL_NOTE.format(parts=missing, ticket=messages.ticket_code(ticket)))
        outcome, kind = Outcome.PARTIAL, "partial"
    parts.append(format_sources(cited))
    reply = _reply(outcome, "\n\n".join(parts), kind, secret, usage, reason=reason, ticket=ticket, top=top)
    reply.answer_body = body
    reply.cited_refs = [c.ref for c in cited]
    return _with_question(reply, standalone)


# ------------------------------------------------------------------ helpers


async def _complete(llm: LLMProvider, prompt: list[Message], settings: Settings) -> LLMResult:
    return await complete_with_retry(
        llm,
        prompt,
        max_output_tokens=settings.llm_max_output_tokens,
        timeout_s=settings.llm_timeout_seconds,
        max_retries=settings.llm_max_retries,
        base_delay=settings.llm_retry_base_delay,
    )


async def _rewrite(
    question: str, history: list[tuple[str, str]], llm: LLMProvider, settings: Settings, usage: _Usage
) -> str:
    """Rewrite only when there is history; on any failure fall back to the original question."""
    if not history:
        return question
    try:
        result = await _complete(llm, build_rewrite_messages(question, history), settings)
        usage.add(result)
        rewritten = RewriteResult.model_validate_json(result.text).standalone_question.strip()
    except Exception as exc:  # noqa: BLE001 - rewriting is an optimisation, never fatal
        logger.warning(
            "rewrite failed, using original question", extra={"fields": {"error": type(exc).__name__}}
        )
        return question
    return redact(rewritten).text or question


async def _ticket(
    session: AsyncSession,
    request: AgentRequest,
    registry: ClassRegistry,
    question: str,
    reason: str,
    top: float | None,
    detail: dict,
) -> int:
    return await open_ticket(
        session,
        registry=registry,
        request_id=request.request_id,
        class_id=request.class_id,
        user_hash=request.user_hash,
        question_redacted=question,
        reason=reason,
        confidence=top,
        check_detail=detail,
        channel=request.channel,
        group_id=request.group_id,
        reply_to=request.reply_to,
    )


def _reply(
    outcome: str,
    text: str,
    kind: str,
    secret: bool,
    usage: _Usage,
    *,
    reason: str | None = None,
    ticket: int | None = None,
    top: float | None = None,
    error: str | None = None,
) -> AgentReply:
    full = f"{messages.SECRET_WARNING}\n\n{text}" if secret else text
    return AgentReply(
        outcome=outcome,
        text=full,
        kind=kind,
        answer_body=text,
        handoff_reason=reason,
        ticket_id=ticket,
        top_score=top,
        model=usage.model,
        input_tokens=usage.input_tokens,
        output_tokens=usage.output_tokens,
        embedding_tokens=usage.embedding_tokens,
        embedding_model=usage.embedding_model,
        error_code=error,
    )


def _with_question(reply: AgentReply, standalone: str) -> AgentReply:
    reply.standalone_question = standalone
    return reply
