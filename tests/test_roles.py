"""Roles in the admin area (D-83): admin = every class; an instructor key = its own class only."""

import pytest
from pydantic import ValidationError
from sqlalchemy import select

from app.api.deps import staff_keys
from app.core.classes import get_registry
from app.core.config import Settings, get_settings
from app.db.models import Document, FaqEntry
from tests.helpers import AUTO_GROUP, GS_GROUP
from tests.test_indexer import make_docx
from tests.test_scenarios import ask, ticket_for

ADMIN = {"X-Admin-Key": "test-admin-key"}
GS = {"X-Admin-Key": "test-gs-instructor-key"}
AUTO = {"X-Admin-Key": "test-auto-instructor-key"}
FEE = "/hoi Khóa học tiếp theo có giảm học phí không?"  # policy handoff -> one ticket per class


# ------------------------------------------------------------------ configuration


@pytest.mark.parametrize(
    "raw",
    [
        "GS-KPI-01=short-key",  # < 16 characters
        "GS-KPI-01",  # no "="
        "GS-KPI-01=first-long-key-123,GS-KPI-01=second-long-key-45",  # class twice
        "GS-KPI-01=same-long-key-12345,AUTO-N8N-01=same-long-key-12345",  # shared key
    ],
)
def test_malformed_instructor_keys_are_rejected_without_echoing_them(raw: str) -> None:
    with pytest.raises(ValidationError) as exc:
        Settings(instructor_api_keys=raw)
    message = str(exc.value)
    assert "INSTRUCTOR_API_KEYS" in message
    for part in raw.replace(",", "=").split("="):
        if "key" in part:
            assert part not in message  # hide_input_in_errors: no key in the startup error / log


def test_instructor_keys_parse() -> None:
    s = Settings(instructor_api_keys=" GS-KPI-01 = gs-key-0123456789 , ")
    assert {k: v.get_secret_value() for k, v in s.instructor_api_keys.items()} == {
        "GS-KPI-01": "gs-key-0123456789"
    }
    assert Settings(instructor_api_keys="").instructor_api_keys == {}


@pytest.mark.parametrize(
    ("keys", "error"),
    [
        ({"COMMON": "common-key-0123456789"}, "unknown class COMMON"),  # shared scope has no instructor
        ({"GS-KPI-99": "typo-key-0123456789"}, "unknown class GS-KPI-99"),
        ({"GS-KPI-01": "test-admin-key"}, "equals ADMIN_API_KEY"),
    ],
)
def test_staff_keys_are_checked_against_classes_yaml(monkeypatch, keys, error) -> None:  # type: ignore[no-untyped-def]
    from pydantic import SecretStr

    monkeypatch.setattr(get_settings(), "instructor_api_keys", {k: SecretStr(v) for k, v in keys.items()})
    staff_keys.cache_clear()
    try:
        with pytest.raises(ValueError, match=error):
            staff_keys()
    finally:
        monkeypatch.undo()
        staff_keys.cache_clear()


# ------------------------------------------------------------------ tickets


async def _tickets(client, fake_queue, db_session) -> tuple[int, int]:  # type: ignore[no-untyped-def]
    _, gs_log = await ask(client, fake_queue, db_session, FEE, GS_GROUP, "u_gs")
    _, auto_log = await ask(client, fake_queue, db_session, FEE, AUTO_GROUP, "u_auto")
    return (await ticket_for(db_session, gs_log)).id, (await ticket_for(db_session, auto_log)).id


@pytest.mark.db
async def test_instructor_sees_and_handles_only_own_class(kb, llm, client, fake_queue, db_session) -> None:
    gs_ticket, auto_ticket = await _tickets(client, fake_queue, db_session)

    me = (await client.get("/admin/me", headers=GS)).json()
    gs_name = next(c.instructor_name for c in get_registry().classes if c.id == "GS-KPI-01")
    assert me == {"role": "instructor", "name": gs_name, "class_id": "GS-KPI-01"}
    assert (await client.get("/admin/me", headers=ADMIN)).json()["role"] == "admin"
    assert (await client.get("/admin/me", headers={"X-Admin-Key": "nope"})).status_code == 401

    # list / filter / export: own class only
    assert [t["id"] for t in (await client.get("/admin/handoffs", headers=GS)).json()] == [gs_ticket]
    assert [t["id"] for t in (await client.get("/admin/handoffs", headers=AUTO)).json()] == [auto_ticket]
    assert len((await client.get("/admin/handoffs", headers=ADMIN)).json()) == 2
    other = await client.get("/admin/handoffs", params={"class_id": "AUTO-N8N-01"}, headers=GS)
    assert other.status_code == 403
    csv = (await client.get("/admin/handoffs/export.csv", headers=GS)).text
    assert "GS-KPI-01" in csv and "AUTO-N8N-01" not in csv

    # another class's ticket does not exist for this key (read, answer, promote)
    assert (await client.get(f"/admin/handoffs/{auto_ticket}", headers=GS)).status_code == 404
    patch = await client.patch(f"/admin/handoffs/{auto_ticket}", json={"instructor_answer": "x"}, headers=GS)
    assert patch.status_code == 404
    assert (await client.post(f"/admin/handoffs/{auto_ticket}/promote", headers=GS)).status_code == 404
    assert (await client.get(f"/admin/handoffs/{gs_ticket}", headers=GS)).status_code == 200

    # classes, bot switch, stats, security events, demo
    assert [c["id"] for c in (await client.get("/admin/classes", headers=GS)).json()] == ["GS-KPI-01"]
    toggle = await client.post("/admin/classes/GS-KPI-01/toggle", json={"enabled": False}, headers=GS)
    assert toggle.status_code == 403  # bot on/off is an admin decision
    stats = (await client.get("/admin/stats", headers=GS)).json()
    assert [r["class_id"] for r in stats["by_class"]] == ["GS-KPI-01"] and stats["total"]["questions"] == 1
    assert (
        await client.get("/admin/stats", params={"class_id": "AUTO-N8N-01"}, headers=GS)
    ).status_code == 403
    assert (await client.get("/admin/security-events", headers=GS)).status_code == 403
    assert (await client.get("/admin/security-events", headers=ADMIN)).status_code == 200


@pytest.mark.db
async def test_demo_is_admin_only(client, monkeypatch) -> None:
    monkeypatch.setattr(get_settings(), "app_env", "dev")
    body = {"group_id": GS_GROUP, "user_id": "u", "text": "/hoi x"}
    assert (await client.post("/demo/api/send", json=body, headers=GS)).status_code == 403
    assert (await client.get("/demo/api/messages", headers=GS)).status_code == 403


@pytest.mark.db
async def test_faq_approver_is_the_logged_in_instructor(kb, llm, client, fake_queue, db_session) -> None:
    gs_ticket, _ = await _tickets(client, fake_queue, db_session)
    await client.patch(
        f"/admin/handoffs/{gs_ticket}", json={"instructor_answer": "Liên hệ phòng tư vấn."}, headers=GS
    )
    resp = await client.post(
        f"/admin/handoffs/{gs_ticket}/promote", json={"approved_by": "Người khác"}, headers=GS
    )
    assert resp.status_code == 200, resp.text
    entry = await db_session.get(FaqEntry, resp.json()["faq_entry_id"])
    assert entry.class_id == "GS-KPI-01"
    assert entry.approved_by == next(c.instructor_name for c in get_registry().classes if c.id == "GS-KPI-01")


# ------------------------------------------------------------------ documents


async def _doc(db_session, class_id: str, origin: str) -> int:  # type: ignore[no-untyped-def]
    return (
        await db_session.execute(
            select(Document.id).where(
                Document.class_id == class_id, Document.origin_scope == origin, Document.status == "active"
            )
        )
    ).scalar_one()


@pytest.mark.db
async def test_instructor_documents_own_class_only(kb, client, db_session) -> None:
    listed = (await client.get("/admin/documents", headers=GS)).json()
    assert {d["class_id"] for d in listed} == {"GS-KPI-01", "COMMON"}  # own + shared material (read)
    assert (
        await client.get("/admin/documents", params={"class_id": "AUTO-N8N-01"}, headers=GS)
    ).status_code == 403

    auto_doc = await _doc(db_session, "AUTO-N8N-01", "AUTO-N8N-01")
    gs_part_of_common_file = await _doc(db_session, "GS-KPI-01", "COMMON")
    gs_doc = await _doc(db_session, "GS-KPI-01", "GS-KPI-01")

    data = make_docx([("GS-99 Mục thử nghiệm", "Nội dung thử nghiệm của lớp Google Sheets.")])
    files = {"file": ("gs_extra.docx", data)}
    for scope in ("AUTO-N8N-01", "COMMON"):
        up = await client.post("/admin/documents", data={"class_id": scope}, files=files, headers=GS)
        assert up.status_code == 403, scope
    ok = await client.post("/admin/documents", data={"class_id": "GS-KPI-01"}, files=files, headers=GS)
    assert ok.status_code == 200, ok.text

    assert (await client.delete(f"/admin/documents/{auto_doc}", headers=GS)).status_code == 404
    assert (await client.post(f"/admin/documents/{auto_doc}/reindex", headers=GS)).status_code == 404
    shared = await client.delete(f"/admin/documents/{gs_part_of_common_file}", headers=GS)
    assert shared.status_code == 403  # the mixed FAQ file also feeds other classes: admin only
    assert (await client.post(f"/admin/documents/{gs_doc}/reindex", headers=GS)).status_code == 200
    assert (await client.delete(f"/admin/documents/{auto_doc}", headers=ADMIN)).status_code == 200
