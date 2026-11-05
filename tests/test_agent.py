"""Agent internals: verification against misbehaving LLMs, timeout/retry, conversation context,
sources line, /api/ask."""

import asyncio
import json
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select, update

from app.agent.conversation import load_history
from app.agent.sources import format_sources
from app.core.config import get_settings
from app.db.models import ConversationTurn, HandoffTicket
from app.providers.base import LLMResult, PermanentLLMError, TransientLLMError
from app.providers.retry import complete_with_retry
from app.retrieval.search import RetrievedChunk
from tests.helpers import AUTO_GROUP, GS_GROUP
from tests.test_scenarios import ask

FAKE_KEY = "sk-" + "live-" + "Mn4" * 8


def _first_block_id(messages) -> str:  # type: ignore[no-untyped-def]
    return messages[-1]["content"].split('<tai_lieu id="', 1)[1].split('"', 1)[0]


# ------------------------------------------------------------------ verification (step 14)


@pytest.mark.db
@pytest.mark.parametrize(
    ("script", "problem"),
    [
        (lambda m: "not json at all", "invalid_json"),
        (
            lambda m: {"answerable": True, "answer": "Bịa đặt.", "cited_chunk_ids": ["c_999999"]},
            "unknown_citation",
        ),
        (lambda m: {"answerable": True, "answer": "Không nguồn.", "cited_chunk_ids": []}, "no_citation"),
        (lambda m: {"answerable": False, "answer": "", "cited_chunk_ids": []}, "not_answerable"),
    ],
)
async def test_bad_llm_output_becomes_low_confidence_handoff(
    kb, llm, client, fake_queue, db_session, script, problem
) -> None:
    llm.script = script
    row, log = await ask(client, fake_queue, db_session, "/hoi Lỗi 401 Unauthorized là gì?")
    assert (log.outcome, log.handoff_reason, row.kind) == ("handoff", "low_confidence", "handoff")
    assert "Bịa đặt" not in row.text and "c_999999" not in row.text
    ticket = (await db_session.execute(select(HandoffTicket))).scalar_one()
    assert problem in ticket.check_detail["problems"]


@pytest.mark.db
async def test_secret_written_by_llm_is_masked(kb, llm, client, fake_queue, db_session) -> None:
    llm.script = lambda m: {
        "answerable": True,
        "answer": f"Dùng key {FAKE_KEY} là được.",
        "cited_chunk_ids": [_first_block_id(m)],
    }
    row, log = await ask(client, fake_queue, db_session, "/hoi Lỗi 401 Unauthorized là gì?")
    assert log.outcome == "answered" and FAKE_KEY not in row.text and "[ĐÃ_ẨN]" in row.text


# ------------------------------------------------------------------ timeout / retry (step 16)


class _SlowLLM:
    name, model = "slow", "slow-model"

    def __init__(self) -> None:
        self.attempts = 0

    async def complete_json(self, messages, *, max_output_tokens):  # type: ignore[no-untyped-def]
        self.attempts += 1
        await asyncio.sleep(1)
        raise AssertionError("should have timed out")


@pytest.mark.db
async def test_llm_timeout_creates_error_ticket(kb, llm, client, fake_queue, db_session, monkeypatch) -> None:
    from app.workers import tasks

    slow = _SlowLLM()
    monkeypatch.setattr(tasks, "get_llm_provider", lambda: slow)
    monkeypatch.setattr(get_settings(), "llm_timeout_seconds", 0.05)
    monkeypatch.setattr(get_settings(), "llm_max_retries", 2)
    row, log = await ask(client, fake_queue, db_session, "/hoi Lỗi 401 Unauthorized là gì?")
    assert slow.attempts == 3  # 1 try + 2 retries
    assert (log.outcome, log.handoff_reason, log.error_code, row.kind) == (
        "error",
        "error",
        "TransientLLMError",
        "error",
    )
    assert "sự cố tạm thời" in row.text and "#H-" in row.text
    assert (await db_session.execute(select(HandoffTicket.reason))).scalar_one() == "error"


class _Flaky:
    name, model = "flaky", "m"

    def __init__(self, failures: int, error: type[Exception]) -> None:
        self.failures, self.error, self.calls = failures, error, 0

    async def complete_json(self, messages, *, max_output_tokens):  # type: ignore[no-untyped-def]
        self.calls += 1
        if self.calls <= self.failures:
            raise self.error("boom")
        return LLMResult("{}", 1, 1, "m")


async def test_retry_only_transient_errors() -> None:
    kwargs = {"max_output_tokens": 10, "timeout_s": 1, "max_retries": 3, "base_delay": 0}
    flaky = _Flaky(2, TransientLLMError)
    assert (await complete_with_retry(flaky, [], **kwargs)).text == "{}" and flaky.calls == 3
    permanent = _Flaky(1, PermanentLLMError)
    with pytest.raises(PermanentLLMError):
        await complete_with_retry(permanent, [], **kwargs)
    assert permanent.calls == 1
    always = _Flaky(99, TransientLLMError)
    with pytest.raises(TransientLLMError):
        await complete_with_retry(always, [], **kwargs)
    assert always.calls == 4


# ------------------------------------------------------------------ conversation context


@pytest.mark.db
async def test_follow_up_question_is_rewritten_with_same_class_history(
    kb, llm, client, fake_queue, db_session
) -> None:
    await ask(client, fake_queue, db_session, "/hoi Lỗi 401 Unauthorized là gì?", AUTO_GROUP, "hv_x")
    llm.calls.clear()
    await ask(client, fake_queue, db_session, "/hoi còn 403 thì sao?", AUTO_GROUP, "hv_x")
    rewrite_call = llm.calls[0]
    assert "standalone_question" in rewrite_call[0]["content"]
    assert "Lỗi 401 Unauthorized là gì?" in rewrite_call[1]["content"]
    answer_prompt = llm.calls[1][-1]["content"]
    assert "<cau_hoi>\nLỗi 401 Unauthorized là gì? còn 403 thì sao?\n</cau_hoi>" in answer_prompt

    # the same student in the OTHER class has no history: no rewrite call at all
    llm.calls.clear()
    await ask(client, fake_queue, db_session, "/hoi còn 403 thì sao?", GS_GROUP, "hv_x")
    assert all("standalone_question" not in call[0]["content"] for call in llm.calls)


@pytest.mark.db
async def test_history_ttl_and_limit(clean_state, db_session) -> None:
    for i in range(10):
        db_session.add(ConversationTurn(class_id="GS-KPI-01", user_hash="u", role="user", content=f"q{i}"))
    db_session.add(
        ConversationTurn(class_id="AUTO-N8N-01", user_hash="u", role="user", content="other class")
    )
    await db_session.commit()
    recent = await load_history(db_session, class_id="GS-KPI-01", user_hash="u", max_turns=2, ttl_minutes=30)
    assert [c for _, c in recent] == ["q6", "q7", "q8", "q9"]
    await db_session.execute(
        update(ConversationTurn).values(created_at=datetime.now(UTC) - timedelta(minutes=31))
    )
    await db_session.commit()
    assert (
        await load_history(db_session, class_id="GS-KPI-01", user_hash="u", max_turns=6, ttl_minutes=30) == []
    )


# ------------------------------------------------------------------ sources line


def _c(
    source_type: str, location: str, code: str | None, doc: str | None, file: str | None
) -> RetrievedChunk:
    return RetrievedChunk(1, "AUTO-N8N-01", source_type, code, location, "x", doc, file, False)


def test_sources_are_built_from_metadata() -> None:
    line = format_sources(
        [
            _c("docx", "AUTO-03 HTTP API", "AUTO-03", "DOC-AUTO-01", "02.docx"),
            _c("docx", "AUTO-05 RAG", "AUTO-05", "DOC-AUTO-01", "02.docx"),
            _c("faq", "AUTO-CLASS-02, dòng 2", "AUTO-CLASS-02", "DOC-FAQ-01", "03.docx"),
            _c("pdf", "trang 1", "AUTO-03", "DOC-AUTO-01", "02.pdf"),
            _c("faq", "Sheet FAQ, dòng 3", None, None, "faq.xlsx"),
            _c("faq", "FAQ giảng viên #7", None, None, None),
            _c("docx", "AUTO-03 HTTP API", "AUTO-03", "DOC-AUTO-01", "02.docx"),  # duplicate
        ]
    )
    assert line == (
        "📚 Nguồn: DOC-AUTO-01 – AUTO-03; AUTO-05; AUTO-03, trang 1 (02.docx); "
        "DOC-FAQ-01 – AUTO-CLASS-02, dòng 2 (03.docx); faq.xlsx (Sheet FAQ, dòng 3); "
        "FAQ đã duyệt (FAQ giảng viên #7)"
    )


# ------------------------------------------------------------------ /api/ask


@pytest.mark.db
async def test_api_ask(kb, llm, client, db_session) -> None:
    body = {"class_id": "GS-KPI-01", "user_id": "u1", "question": "Bài tập nộp khi nào?"}
    assert (await client.post("/api/ask", json=body)).status_code == 401
    assert (await client.post("/api/ask", json=body, headers={"X-API-Key": "nope"})).status_code == 401
    headers = {"X-API-Key": "test-ask-key"}
    resp = await client.post("/api/ask", json=body, headers=headers)
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["outcome"] == "answered" and "22:00 Chủ nhật" in data["answer"] and data["cited_chunk_ids"]
    assert (
        await client.post("/api/ask", json={**body, "class_id": "COMMON"}, headers=headers)
    ).status_code == 404
    await client.post(
        "/admin/classes/GS-KPI-01/toggle", json={"enabled": False}, headers={"X-Admin-Key": "test-admin-key"}
    )
    assert (await client.post("/api/ask", json=body, headers=headers)).status_code == 409


def test_fake_llm_payloads_are_json() -> None:
    """Guard against the fake drifting from the schema the pipeline validates."""
    from app.agent.prompts import LLMAnswer
    from app.providers.fake_llm import FakeLLM

    payload = FakeLLM._answer('<tai_lieu id="c_1" nguon="X" muc="Y">\nn8n webhook xác thực\n</tai_lieu>\n\n'
                              "<cau_hoi>\nwebhook n8n xác thực thế nào\n</cau_hoi>")  # fmt: skip
    LLMAnswer.model_validate_json(json.dumps(payload))
    assert payload["answerable"] and payload["cited_chunk_ids"] == ["c_1"]
