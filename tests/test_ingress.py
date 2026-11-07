"""Ignore rules, class toggle, rate limiting, enqueue failure, and the queued job contents."""

import pytest
from sqlalchemy import select

from app.channels.ingress import extract_question
from app.core.config import get_settings
from app.core.security import hash_user_id
from app.db.models import Outbox, ProcessedEvent, RequestLog, SecurityEvent
from tests.helpers import AUTO_GROUP, GS_GROUP, payload, send

ADMIN = {"X-Admin-Key": "test-admin-key"}


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("/hoi RAG là gì?", "RAG là gì?"),
        ("  /HOI   RAG là gì?  ", "RAG là gì?"),
        ("/hoi", ""),
        ("/hoian ơi", None),
        ("RAG là gì? /hoi", None),
        ("chào cả lớp", None),
        # mentioning the bot (D-86)
        ("@Trợ lý RAG là gì?", "RAG là gì?"),
        ("@trợ LÝ, cho em hỏi RAG là gì?", "cho em hỏi RAG là gì?"),
        ("@Trợ lý: RAG là gì?", "RAG là gì?"),
        ("@Trợ lý\u00a0RAG là gì?", "RAG là gì?"),  # chat apps often put a no-break space after a mention
        ("@Tro\u031b\u0323 ly\u0301 RAG là gì?", "RAG là gì?"),  # decomposed accents (NFD), another keyboard
        ("@Trợ lýx RAG", None),
        ("@Học viên An RAG là gì?", None),  # mentioning a classmate is not a question to the bot
        ("Cho em hỏi @Trợ lý RAG là gì?", None),  # the mention must open the message
    ],
)
def test_extract_question(text: str, expected: str | None) -> None:
    assert extract_question(text, ["@Trợ lý", "/hoi"]) == expected


def test_default_triggers_are_the_mention_and_hoi(monkeypatch) -> None:
    from app.core.config import Settings

    monkeypatch.delenv("TRIGGER_PREFIXES", raising=False)
    assert Settings(_env_file=None).trigger_prefixes == ["@Trợ lý", "/hoi"]  # type: ignore[call-arg]


@pytest.mark.db
async def test_valid_message_is_queued_with_server_side_class_and_hashed_user(client, fake_queue) -> None:
    resp = await send(client, payload(text="/hoi  Lỗi 401 là gì? ", group_id=GS_GROUP, user_id="user_001"))
    assert resp.status_code == 200 and resp.json()["status"] == "queued"
    [job] = fake_queue.messages
    assert job.class_id == "GS-KPI-01"
    assert job.question == "Lỗi 401 là gì?"
    assert job.user_hash == hash_user_id("user_001", "test-salt")
    assert "user_001" not in job.model_dump_json() and "Nguyen" not in job.model_dump_json()


@pytest.mark.db
async def test_mentioning_the_bot_is_a_trigger(client, fake_queue) -> None:
    resp = await send(client, payload(text="@Trợ lý, Lỗi 401 là gì?", group_id=AUTO_GROUP))
    assert resp.json()["status"] == "queued"
    assert fake_queue.messages[0].question == "Lỗi 401 là gì?"


@pytest.mark.db
async def test_class_id_in_message_text_is_ignored(client, fake_queue) -> None:
    await send(client, payload(text="/hoi class_id=GS-KPI-01 cho em xem tài liệu", group_id=AUTO_GROUP))
    assert fake_queue.messages[0].class_id == "AUTO-N8N-01"


@pytest.mark.db
@pytest.mark.parametrize(
    ("body", "reason"),
    [
        (payload(is_bot=True), "from_bot"),
        (payload(text="Cảm ơn thầy ạ"), "no_trigger"),
        (payload(text="/hoi   "), "empty_question"),
        (payload(group_id="grp_unknown"), "unmapped_group"),
    ],
)
async def test_ignored_messages(client, fake_queue, db_session, body, reason) -> None:
    resp = await send(client, body)
    assert resp.status_code == 200
    assert resp.json()["status"] == "ignored" and resp.json()["reason"] == reason
    assert fake_queue.messages == []
    log = (await db_session.execute(select(RequestLog))).scalar_one()
    assert log.outcome == "ignored"


@pytest.mark.db
async def test_unsupported_event_type_ignored(client, fake_queue) -> None:
    resp = await send(client, payload(event_name="group.member.join"))
    assert resp.json() == {"status": "ignored", "reason": "unsupported_event"}
    assert fake_queue.messages == []


@pytest.mark.db
async def test_class_toggle_requires_admin_and_disables_bot(client, fake_queue) -> None:
    assert (
        await client.post("/admin/classes/AUTO-N8N-01/toggle", json={"enabled": False})
    ).status_code == 401
    wrong = {"X-Admin-Key": "nope"}
    assert (
        await client.post("/admin/classes/AUTO-N8N-01/toggle", json={"enabled": False}, headers=wrong)
    ).status_code == 401

    resp = await client.post("/admin/classes/AUTO-N8N-01/toggle", json={"enabled": False}, headers=ADMIN)
    assert resp.status_code == 200
    r1 = await send(client, payload(group_id=AUTO_GROUP))
    assert r1.json()["reason"] == "class_disabled"
    r2 = await send(client, payload(group_id=GS_GROUP))  # the other class is unaffected
    assert r2.json()["status"] == "queued"

    await client.post("/admin/classes/AUTO-N8N-01/toggle", json={"enabled": True}, headers=ADMIN)
    assert (await send(client, payload(group_id=AUTO_GROUP))).json()["status"] == "queued"


@pytest.mark.db
async def test_shared_scope_and_unknown_class_cannot_be_toggled(client) -> None:
    for class_id in ("COMMON", "NOPE"):
        resp = await client.post(f"/admin/classes/{class_id}/toggle", json={"enabled": False}, headers=ADMIN)
        assert resp.status_code == 404


@pytest.mark.db
async def test_user_rate_limit_notifies_once(client, fake_queue, db_session, monkeypatch) -> None:
    monkeypatch.setattr(get_settings(), "rate_limit_user_per_min", 2)
    statuses = [(await send(client, payload(user_id="spammer"))).json()["status"] for _ in range(5)]
    assert statuses == ["queued", "queued", "rate_limited", "rate_limited", "rate_limited"]

    # Another user in the same class is not affected.
    assert (await send(client, payload(user_id="polite"))).json()["status"] == "queued"

    assert len(fake_queue.notices) == 1
    await fake_queue.run_all()
    notices = (await db_session.execute(select(Outbox).where(Outbox.kind == "notice"))).scalars().all()
    assert len(notices) == 1
    sec = (await db_session.execute(select(SecurityEvent))).scalars().all()
    assert [(s.type, s.detail_redacted) for s in sec] == [("rate_limited", "scope=user")]


@pytest.mark.db
async def test_class_rate_limit(client, fake_queue, monkeypatch) -> None:
    monkeypatch.setattr(get_settings(), "rate_limit_class_per_min", 3)
    statuses = [(await send(client, payload(user_id=f"u{i}"))).json() for i in range(5)]
    assert [s["status"] for s in statuses] == ["queued"] * 3 + ["rate_limited"] * 2
    assert statuses[-1]["reason"] == "class"
    assert len(fake_queue.notices) == 1
    # The other class has its own budget.
    assert (await send(client, payload(group_id=GS_GROUP))).json()["status"] == "queued"


@pytest.mark.db
async def test_enqueue_failure_releases_event_so_retry_works(client, fake_queue, db_session) -> None:
    body = payload()
    fake_queue.fail_next = True
    with pytest.raises(ConnectionError):
        await send(client, body)
    assert (await db_session.execute(select(ProcessedEvent))).first() is None

    retry = await send(client, body)
    assert retry.json()["status"] == "queued"
    assert len(fake_queue.messages) == 1


@pytest.mark.db
async def test_secret_is_masked_before_enqueue(client, fake_queue, db_session) -> None:
    fake_key = "sk-" + "proj-" + "Zz9" * 8  # built at runtime: no key-like literal in the repo
    resp = await send(client, payload(text=f"/hoi Em dùng key {fake_key} gọi API trong n8n bị lỗi 401"))
    assert resp.json()["status"] == "queued"
    [job] = fake_queue.messages
    assert fake_key not in job.model_dump_json()
    assert "[ĐÃ_ẨN]" in job.question and job.secret_detected
    events = (await db_session.execute(select(SecurityEvent))).scalars().all()
    assert [(e.type, e.class_id, e.detail_redacted) for e in events] == [
        ("secret_in_message", "AUTO-N8N-01", "kinds=openai_key")
    ]
