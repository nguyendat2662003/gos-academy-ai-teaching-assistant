"""Checks on the LLM answer before anything reaches students (CLAUDE.md §5 step 14)."""

from dataclasses import dataclass, field

from pydantic import ValidationError

from app.agent.prompts import LLMAnswer
from app.core.redact import redact


@dataclass
class Verification:
    ok: bool
    answer: LLMAnswer | None = None
    problems: list[str] = field(default_factory=list)


def verify_answer(raw: str, retrieved_refs: set[str]) -> Verification:
    """Valid JSON + answerable + ≥1 citation + every citation among the chunks we actually retrieved."""
    try:
        answer = LLMAnswer.model_validate_json(raw)
    except ValidationError:
        return Verification(False, problems=["invalid_json"])
    problems = []
    if not answer.answerable:
        problems.append("not_answerable")
    if not answer.cited_chunk_ids:
        problems.append("no_citation")
    unknown = [c for c in answer.cited_chunk_ids if c not in retrieved_refs]
    if unknown:
        problems.append("unknown_citation")
    if answer.answerable and not answer.answer.strip():
        problems.append("empty_answer")
    # Defence in depth: whatever the model wrote, secrets never go out.
    answer.answer = redact(answer.answer).text
    return Verification(not problems, answer, problems)
