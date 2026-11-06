"""Phase 5: handoff tickets admin API, 'Duyệt vào FAQ' end to end, CSV export, admin page, /demo."""

import csv
import io

import pytest
from sqlalchemy import select

from app.core.config import get_settings
from app.db.models import Chunk, FaqEntry, HandoffTicket, Outbox
from tests.helpers import AUTO_GROUP, GS_GROUP
from tests.test_scenarios import ask

pytestmark = pytest.mark.db

ADMIN = {"X-Admin-Key": "test-admin-key"}
QUESTION = "/hoi Có cần dùng Kubernetes để deploy Docker Swarm không?"
ANSWER = "Không cần. Docker Swarm và Kubernetes là hai công cụ điều phối khác nhau."
FAKE_KEY = "sk-" + "proj-" + "Zx9" * 8


async def _tickets(client, **params):  # type: ignore[no-untyped-def]
    resp = await client.get("/admin/handoffs", params=params, headers=ADMIN)
    assert resp.status_code == 200, resp.text
    return resp.json()


# ------------------------------------------------------------------ the FAQ approval loop, end to end


async def test_faq_approval_end_to_end(kb, llm, client, fake_queue, db_session) -> None:
    # 1. not in the material -> handoff ticket for the AUTO instructor
    row, log = await ask(client, fake_queue, db_session, QUESTION, AUTO_GROUP, "hv_a")
    assert log.outcome == "handoff"
    [ticket] = await _tickets(client, class_id="AUTO-N8N-01", status="open")
    assert ticket["question"] == QUESTION.removeprefix("/hoi ") and ticket["code"] in row.text
    assert ticket["assignee"] == "Giảng viên lớp AI Automation (placeholder)" and ticket["can_post_to_group"]
    assert await _tickets(client, class_id="GS-KPI-01") == []  # the GS inbox does not see it

    # 2. instructor answers and posts it into the student's group
    resp = await client.patch(
        f"/admin/handoffs/{ticket['id']}",
        json={"instructor_answer": ANSWER, "post_to_group": True},
        headers=ADMIN,
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert (
        data["posted_to_group"] and data["ticket"]["status"] == "answered" and data["ticket"]["answered_at"]
    )
    posted = (await db_session.execute(select(Outbox).where(Outbox.kind == "instructor"))).scalar_one()
    assert posted.external_group_id == AUTO_GROUP and ticket["code"] in posted.text and ANSWER in posted.text

    # 3. "Duyệt vào FAQ" -> active entry of the ticket's class, indexed immediately
    resp = await client.post(f"/admin/handoffs/{ticket['id']}/promote", json={}, headers=ADMIN)
    assert resp.status_code == 200, resp.text
    promoted = resp.json()
    assert promoted["class_id"] == "AUTO-N8N-01" and promoted["approved_by"] == ticket["assignee"]
    entry = await db_session.get(FaqEntry, promoted["faq_entry_id"])
    assert entry is not None and entry.source == "instructor" and entry.source_ticket_id == ticket["id"]
    assert entry.embedding_tokens > 0 and entry.embedding_model == "fake-embedding"  # counted in /admin/stats
    faq_chunk = (await db_session.execute(select(Chunk).where(Chunk.faq_entry_id == entry.id))).scalar_one()
    assert faq_chunk.class_id == "AUTO-N8N-01" and faq_chunk.embedding is not None
    again = await client.post(f"/admin/handoffs/{ticket['id']}/promote", json={}, headers=ADMIN)
    assert again.status_code == 409 and "already_promoted" in again.text

    # 4. the same question in the same class is now answered from the approved FAQ, with its source
    llm.calls.clear()
    row, log = await ask(client, fake_queue, db_session, QUESTION, AUTO_GROUP, "hv_b")
    assert log.outcome == "answered", row.text
    assert f"c_{faq_chunk.id}" in log.cited_chunk_ids
    assert f"FAQ đã duyệt (FAQ giảng viên #{entry.id})" in row.text.split("📚")[1]

    # 5. ... but never in the other class: the AUTO entry is not even shown to the model there
    llm.calls.clear()
    gs_row, gs_log = await ask(client, fake_queue, db_session, QUESTION, GS_GROUP, "hv_c")
    assert all(f'id="c_{faq_chunk.id}"' not in call[-1]["content"] for call in llm.calls)
    assert f"c_{faq_chunk.id}" not in (gs_log.cited_chunk_ids or [])
    assert gs_log.outcome != "answered" and "FAQ đã duyệt" not in gs_row.text


# ------------------------------------------------------------------ ticket API rules


async def test_ticket_api_requires_admin_key(client) -> None:
    for method, path in [
        ("GET", "/admin/handoffs"),
        ("GET", "/admin/handoffs/export.csv"),
        ("PATCH", "/admin/handoffs/1"),
        ("POST", "/admin/handoffs/1/promote"),
        ("GET", "/admin/classes"),
    ]:
        resp = await client.request(method, path, json={}, headers={"X-Admin-Key": "wrong"})
        assert resp.status_code == 401, (method, path)


async def test_answer_is_redacted_and_promote_needs_an_answer(
    kb, llm, client, fake_queue, db_session
) -> None:
    await ask(client, fake_queue, db_session, QUESTION)
    [ticket] = await _tickets(client)
    url = f"/admin/handoffs/{ticket['id']}"

    resp = await client.post(url + "/promote", json={}, headers=ADMIN)
    assert resp.status_code == 409 and "missing_answer" in resp.text
    assert (await client.patch(url, json={"status": "bogus"}, headers=ADMIN)).status_code == 422
    resp = await client.patch(url, json={"status": "in_progress", "assignee": "Cô Lan"}, headers=ADMIN)
    assert resp.json()["ticket"]["status"] == "in_progress" and resp.json()["ticket"]["assignee"] == "Cô Lan"

    resp = await client.patch(url, json={"instructor_answer": f"Dùng key {FAKE_KEY} nhé"}, headers=ADMIN)
    stored = resp.json()["ticket"]["instructor_answer"]
    assert FAKE_KEY not in stored and "[ĐÃ_ẨN]" in stored and resp.json()["ticket"]["status"] == "answered"
    assert resp.json()["posted_to_group"] is False
    assert (await db_session.execute(select(Outbox).where(Outbox.kind == "instructor"))).first() is None

    resp = await client.post(url + "/promote", json={"question": "Kubernetes có cần không?"}, headers=ADMIN)
    entry = await db_session.get(FaqEntry, resp.json()["faq_entry_id"])
    assert entry.question == "Kubernetes có cần không?" and FAKE_KEY not in entry.answer


async def test_api_ticket_cannot_be_posted_to_a_group(kb, llm, client, db_session) -> None:
    body = {"class_id": "GS-KPI-01", "user_id": "u1", "question": "Khóa học tiếp theo có giảm học phí không?"}
    assert (
        await client.post("/api/ask", json=body, headers={"X-API-Key": "test-ask-key"})
    ).status_code == 200
    [ticket] = await _tickets(client)
    assert ticket["reason"] == "policy" and not ticket["can_post_to_group"]
    update = {"instructor_answer": "Liên hệ tư vấn.", "post_to_group": True}
    resp = await client.patch(f"/admin/handoffs/{ticket['id']}", json=update, headers=ADMIN)
    assert resp.status_code == 409


async def test_csv_export(client, db_session) -> None:
    for class_id, question in [
        ("AUTO-N8N-01", '=HYPERLINK("http://evil","bấm")'),
        ("GS-KPI-01", "Hỏi về GS"),
    ]:
        db_session.add(
            HandoffTicket(class_id=class_id, question_redacted=question, user_hash="u", reason="no_context")
        )
    await db_session.commit()
    resp = await client.get("/admin/handoffs/export.csv", params={"class_id": "AUTO-N8N-01"}, headers=ADMIN)
    assert resp.status_code == 200 and resp.headers["content-type"].startswith("text/csv")
    assert resp.content.startswith("﻿".encode())  # Excel/Sheets open it as UTF-8
    rows = list(csv.DictReader(io.StringIO(resp.content.decode("utf-8-sig"))))
    assert len(rows) == 1 and rows[0]["class_id"] == "AUTO-N8N-01" and rows[0]["code"].startswith("#H-")
    assert rows[0]["question"] == "'" + '=HYPERLINK("http://evil","bấm")'  # formula neutralised
    assert "user_hash" not in rows[0]


# ------------------------------------------------------------------ pages


async def test_admin_page_is_a_static_shell_with_csp(client) -> None:
    resp = await client.get("/admin/ui")
    assert resp.status_code == 200 and "Yêu cầu chuyển giảng viên" in resp.text
    policy = resp.headers["content-security-policy"]
    assert "script-src 'nonce-" in policy and "unsafe-inline" not in policy
    nonce = policy.split("'nonce-", 1)[1].split("'", 1)[0]
    assert f'<script nonce="{nonce}">' in resp.text
    for secret in ("test-admin-key", "test-webhook-secret", "test-ask-key"):
        assert secret not in resp.text


async def test_demo_is_dev_only(client) -> None:
    assert get_settings().app_env == "test"
    assert (await client.get("/demo")).status_code == 404
    resp = await client.post(
        "/demo/api/send", json={"group_id": GS_GROUP, "user_id": "u", "text": "x"}, headers=ADMIN
    )
    assert resp.status_code == 404


async def test_demo_signs_server_side_and_reads_the_outbox(client, fake_queue, monkeypatch) -> None:
    monkeypatch.setattr(get_settings(), "app_env", "dev")
    page = await client.get("/demo")
    assert page.status_code == 200 and GS_GROUP in page.text and AUTO_GROUP in page.text
    assert "test-webhook-secret" not in page.text and "test-admin-key" not in page.text

    body = {"group_id": AUTO_GROUP, "user_id": "hv_demo", "text": "/hoi Lỗi 401 là gì?"}
    assert (await client.post("/demo/api/send", json=body)).status_code == 401
    assert (
        await client.post("/demo/api/send", json={**body, "group_id": "grp_unknown"}, headers=ADMIN)
    ).status_code == 422
    resp = await client.post("/demo/api/send", json=body, headers=ADMIN)
    assert resp.status_code == 200 and resp.json()["result"]["status"] == "queued"  # passed the HMAC check
    assert len(fake_queue.messages) == 1 and fake_queue.messages[0].group_id == AUTO_GROUP
    no_trigger = await client.post("/demo/api/send", json={**body, "text": "chào cả nhà"}, headers=ADMIN)
    assert no_trigger.json()["result"] == {
        "status": "ignored",
        "reason": "no_trigger",
        "request_id": no_trigger.json()["result"]["request_id"],
    }

    await fake_queue.run_all()  # empty knowledge base -> handoff reply in the AUTO group
    messages = (await client.get("/demo/api/messages", headers=ADMIN)).json()
    assert [(m["group_id"], m["kind"]) for m in messages] == [(AUTO_GROUP, "handoff")]
    assert messages[0]["reply_to"] == resp.json()["msg_id"]
    assert (await client.get(f"/demo/api/messages?after={messages[0]['id']}", headers=ADMIN)).json() == []


async def test_demo_shows_events_replays_them_and_simulates_a_bot(client, fake_queue, monkeypatch) -> None:
    """D-84: the page shows the event it sent (never the signature), can re-deliver it unchanged (scenario 6,
    including two copies at the same time) and can post as a bot account (loop protection)."""
    monkeypatch.setattr(get_settings(), "app_env", "dev")
    body = {"group_id": GS_GROUP, "user_id": "hv_an", "text": "/hoi Bài tập nộp khi nào?"}
    sent = (await client.post("/demo/api/send", json=body, headers=ADMIN)).json()
    event = sent["event"]
    assert event["event_id"] == sent["event_id"] and event["sender"] == {"id": "hv_an", "is_bot": False}
    assert "signature" not in str(sent).lower() and "test-webhook-secret" not in str(sent)
    assert sent["result"]["status"] == "queued" and len(fake_queue.messages) == 1

    again = (await client.post("/demo/api/replay", json={"event": event}, headers=ADMIN)).json()
    assert [d["result"]["status"] for d in again] == ["duplicate"]
    fresh = {**event, "event_id": "demo_concurrent_1"}
    both = (await client.post("/demo/api/replay", json={"event": fresh, "times": 2}, headers=ADMIN)).json()
    assert sorted(d["result"]["status"] for d in both) == ["duplicate", "queued"]  # concurrent: one wins
    assert len(fake_queue.messages) == 2
    bad = await client.post("/demo/api/replay", json={"event": {**event, "group_id": "grp_x"}}, headers=ADMIN)
    assert bad.status_code == 422

    as_bot = {**body, "user_id": "bot_khac", "is_bot": True}
    ignored = (await client.post("/demo/api/send", json=as_bot, headers=ADMIN)).json()
    assert ignored["result"]["status"] == "ignored" and ignored["result"]["reason"] == "from_bot"

    page = (await client.get("/demo")).text
    assert "MÔ PHỎNG" in page and "/webhooks/mock" in page and '"/hoi"' in page
    await fake_queue.run_all()
    rows = (await client.get("/demo/api/messages", headers=ADMIN)).json()
    assert rows and all(r["created_at"] for r in rows)
