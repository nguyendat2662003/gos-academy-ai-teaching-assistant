"""Greetings / thanks to the bot get a friendly fixed reply: no LLM, no retrieval, no ticket (D-87)."""

import pytest
from sqlalchemy import func, select

from app.agent.smalltalk import classify_smalltalk
from app.db.models import ConversationTurn, HandoffTicket
from tests.helpers import AUTO_GROUP, GS_GROUP
from tests.test_scenarios import ask


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("chào bạn", "greeting"),
        ("Xin chào trợ lý ạ!", "greeting"),
        ("hello", "greeting"),
        ("Chào buổi sáng cả nhà 👋", "greeting"),
        ("cảm ơn bạn nhiều nhé", "thanks"),
        ("Cám ơn ạ", "thanks"),
        ("thanks", "thanks"),
        ("ok ạ", "thanks"),
        # real questions, even polite ones, go through the normal pipeline
        ("chào bạn, cho mình hỏi SUMIFS dùng thế nào?", None),
        ("cảm ơn, vậy còn lỗi 401 thì sao?", None),
        ("Bài tập nộp khi nào?", None),
        ("ạ", None),
        ("", None),
        ("chào chào chào chào chào chào chào chào chào", None),  # too long to be a plain greeting
    ],
)
def test_classify_smalltalk(text: str, expected: str | None) -> None:
    assert classify_smalltalk(text) == expected


@pytest.mark.db
async def test_greeting_gets_a_friendly_reply_without_llm_or_ticket(
    kb, llm, client, fake_queue, db_session
) -> None:
    row, log = await ask(client, fake_queue, db_session, "@Trợ lý chào bạn", AUTO_GROUP, "hv_a")
    assert log.outcome == "smalltalk" and row.kind == "smalltalk"
    assert "AI Automation" in row.text and "@Trợ lý" in row.text  # tells the student how to ask
    assert llm.calls == [] and log.input_tokens == 0 and log.embedding_tokens == 0
    assert (await db_session.execute(select(func.count()).select_from(HandoffTicket))).scalar_one() == 0
    assert (await db_session.execute(select(func.count()).select_from(ConversationTurn))).scalar_one() == 0

    row, log = await ask(client, fake_queue, db_session, "@Trợ lý cảm ơn ạ", GS_GROUP, "hv_b")
    assert log.outcome == "smalltalk" and row.text.startswith("Không có gì")
    assert llm.calls == []


@pytest.mark.db
async def test_greeting_is_counted_apart_from_questions(kb, llm, client, fake_queue, db_session) -> None:
    await ask(client, fake_queue, db_session, "@Trợ lý xin chào", AUTO_GROUP, "hv_a")
    stats = (await client.get("/admin/stats", headers={"X-Admin-Key": "test-admin-key"})).json()
    assert stats["total"]["smalltalk"] == 1 and stats["total"]["questions"] == 0
