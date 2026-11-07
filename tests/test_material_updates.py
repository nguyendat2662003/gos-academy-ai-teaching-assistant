"""Updating the material: a renamed file still replaces its old version (D-88), and approved FAQ entries are
flagged for review when their class's material changes, then confirmed / edited / deactivated (D-89)."""

import io

import pytest
from docx import Document as DocxWriter
from sqlalchemy import func, select

from app.core.classes import get_registry
from app.db.models import Chunk, Document, FaqEntry
from app.ingestion import indexer
from app.ingestion.faq import _faq_chunk, faq_chunk_text
from app.providers.fake import FakeEmbeddingProvider
from app.retrieval.search import hybrid_search

pytestmark = pytest.mark.db

EMBEDDER = FakeEmbeddingProvider("fake-embedding", 768)  # same as EMBEDDING_* in tests
ADMIN = {"X-Admin-Key": "test-admin-key"}
GS_INSTRUCTOR = {"X-Admin-Key": "test-gs-instructor-key"}


def coded_docx(code: str | None, sections: list[tuple[str, str]]) -> bytes:
    doc = DocxWriter()
    doc.add_paragraph("Tài liệu kiểm thử", style="Title")
    if code:
        doc.add_paragraph(f"Mã tài liệu: {code}")
    for heading, body in sections:
        doc.add_heading(heading, level=1)
        doc.add_paragraph(body)
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


async def ingest(session, data: bytes, filename: str, scope: str, embedder=EMBEDDER, **kw):  # type: ignore[no-untyped-def]
    return await indexer.index_file(
        session, data=data, filename=filename, origin_scope=scope, embedder=embedder,
        registry=get_registry(), **kw,
    )  # fmt: skip


async def active_texts(session, class_id: str) -> str:
    rows = await session.execute(
        select(Chunk.content)
        .join(Document, Document.id == Chunk.document_id)
        .where(Document.status == "active", Chunk.class_id == class_id)
    )
    return " ".join(rows.scalars())


async def add_faq(session, class_id: str, question: str, answer: str) -> int:  # type: ignore[no-untyped-def]
    entry = FaqEntry(class_id=class_id, question=question, answer=answer, source="instructor", active=True)
    session.add(entry)
    await session.flush()
    content = faq_chunk_text(class_id, question, answer)
    vector = (await EMBEDDER.embed([content], "document")).vectors[0]
    session.add(_faq_chunk(entry, content, vector)[0])
    entry_id = entry.id
    await session.commit()
    return entry_id


async def faq_state(session, entry_id: int) -> FaqEntry:  # type: ignore[no-untyped-def]
    session.expire_all()
    return await session.get(FaqEntry, entry_id)


async def retrievable_faq_texts(session, class_id: str, question: str) -> list[str]:
    result = await hybrid_search(
        session, class_id=class_id, question=question, embedder=EMBEDDER, registry=get_registry(), top_k=50
    )
    return [c.content for c in result.chunks if c.filename is None]  # instructor FAQ chunks have no file


# ------------------------------------------------------------- D-88: one active version per document code


async def test_renamed_file_with_the_same_code_replaces_the_old_version(clean_state, db_session) -> None:
    v1 = coded_docx("DOC-AUTO-95", [("AUTO-95  Lịch họp", "Nhóm dự án họp vào thứ Hai hằng tuần.")])
    v2 = coded_docx("DOC-AUTO-95", [("AUTO-95  Lịch họp", "Nhóm dự án họp vào thứ Sáu hằng tuần.")])
    r1 = await ingest(db_session, v1, "lich.docx", "AUTO-N8N-01")
    r2 = await ingest(db_session, v2, "lich_ban_moi.docx", "AUTO-N8N-01")

    [res] = r2.results
    assert (res.status, res.version, res.replaced) == ("indexed", 2, ["lich.docx"])
    text = await active_texts(db_session, "AUTO-N8N-01")
    assert "thứ Sáu" in text and "thứ Hai" not in text
    old = await db_session.get(Document, r1.results[0].document_id)
    await db_session.refresh(old)
    assert old.status == "superseded"
    assert await db_session.scalar(select(func.count()).where(Chunk.document_id == old.id)) == 0
    active = await db_session.scalar(
        select(func.count())
        .select_from(Document)
        .where(Document.doc_code == "DOC-AUTO-95", Document.status == "active")
    )
    assert active == 1


async def test_files_without_a_code_are_still_matched_by_name(clean_state, db_session) -> None:
    await ingest(db_session, coded_docx(None, [("GS-91  A", "Nội dung A.")]), "a.docx", "GS-KPI-01")
    await ingest(db_session, coded_docx(None, [("GS-92  B", "Nội dung B.")]), "b.docx", "GS-KPI-01")
    text = await active_texts(db_session, "GS-KPI-01")
    assert "Nội dung A" in text and "Nội dung B" in text  # two different documents, both kept


async def test_code_used_by_another_source_in_the_class_is_refused(clean_state, db_session) -> None:
    shared = coded_docx("DOC-X-01", [("GS-91  Quy định", "Nộp bài trước 22:00.")])
    await ingest(db_session, shared, "chung.docx", "COMMON")  # COMMON-origin file feeding GS-KPI-01
    before = await db_session.scalar(select(func.count()).select_from(Document))

    clash = coded_docx("DOC-X-01", [("GS-93  Khác", "Một tài liệu khác của lớp.")])
    with pytest.raises(indexer.IngestError, match="DOC-X-01"):
        await ingest(db_session, clash, "rieng.docx", "GS-KPI-01")
    assert await db_session.scalar(select(func.count()).select_from(Document)) == before


async def test_upload_api_reports_the_replaced_file(clean_state, client) -> None:
    def upload(name: str, body: str):  # type: ignore[no-untyped-def]
        data = coded_docx("DOC-GS-95", [("GS-95  Hạn nộp", body)])
        return client.post(
            "/admin/documents", data={"class_id": "GS-KPI-01"},
            files={"file": (name, data, "application/octet-stream")}, headers=GS_INSTRUCTOR,
        )  # fmt: skip

    assert (await upload("han_nop.docx", "Hạn nộp: Chủ nhật.")).status_code == 200
    resp = await upload("han_nop_2026.docx", "Hạn nộp: thứ Bảy.")
    assert resp.status_code == 200, resp.text
    assert resp.json()["results"][0]["replaced"] == ["han_nop.docx"]


# ------------------------------------------------------------- D-89: FAQ review when the material changes


async def test_material_change_flags_faqs_of_that_class_only(clean_state, db_session) -> None:
    gs = await add_faq(db_session, "GS-KPI-01", "Hạn nộp bài?", "22:00 Chủ nhật.")
    auto = await add_faq(db_session, "AUTO-N8N-01", "Hạn nộp bài?", "22:00 thứ Bảy.")

    report = await ingest(
        db_session,
        coded_docx("DOC-GS-95", [("GS-95  Hạn nộp", "Hạn nộp mới: thứ Hai.")]),
        "h.docx",
        "GS-KPI-01",
    )
    assert report.results[0].faqs_flagged == 1
    gs_state = await faq_state(db_session, gs)
    assert gs_state.needs_review and "DOC-GS-95" in gs_state.review_reason and "v1" in gs_state.review_reason
    assert gs_state.active  # still served until an instructor decides
    assert not (await faq_state(db_session, auto)).needs_review


async def test_shared_material_change_flags_every_class(clean_state, db_session) -> None:
    gs = await add_faq(db_session, "GS-KPI-01", "Q1", "A1")
    auto = await add_faq(db_session, "AUTO-N8N-01", "Q2", "A2")
    await ingest(db_session, coded_docx(None, [("COMMON-95  Quy định", "Nội quy mới.")]), "q.docx", "COMMON")
    assert (await faq_state(db_session, gs)).needs_review and (await faq_state(db_session, auto)).needs_review


async def test_same_content_reembedded_or_unchanged_does_not_flag(clean_state, db_session) -> None:
    data = coded_docx("DOC-GS-95", [("GS-95  A", "Nội dung A.")])
    await ingest(db_session, data, "a.docx", "GS-KPI-01")
    entry = await add_faq(db_session, "GS-KPI-01", "Q", "A")  # created after the first version

    unchanged = await ingest(db_session, data, "a.docx", "GS-KPI-01")
    assert unchanged.results[0].status == "unchanged"
    other_model = FakeEmbeddingProvider("another-embedding-model", 768)
    reembedded = await ingest(db_session, data, "a.docx", "GS-KPI-01", embedder=other_model)
    assert reembedded.results[0].status == "indexed"  # new version, same text
    assert not (await faq_state(db_session, entry)).needs_review


async def test_deleting_a_document_flags_its_class_faqs(clean_state, db_session) -> None:
    report = await ingest(db_session, coded_docx(None, [("GS-95  A", "Nội dung A.")]), "a.docx", "GS-KPI-01")
    entry = await add_faq(db_session, "GS-KPI-01", "Q", "A")
    assert await indexer.delete_document(db_session, report.results[0].document_id)
    state = await faq_state(db_session, entry)
    assert state.needs_review and "đã bị xóa" in state.review_reason


async def test_instructor_reviews_edits_and_deactivates_faq(clean_state, client, db_session) -> None:
    entry = await add_faq(db_session, "GS-KPI-01", "Hạn nộp bài tập?", "Hạn nộp là 22:00 Chủ nhật.")
    await ingest(db_session, coded_docx(None, [("GS-95  Hạn nộp", "Đổi lịch.")]), "h.docx", "GS-KPI-01")

    listed = (await client.get("/admin/faqs", params={"status": "review"}, headers=GS_INSTRUCTOR)).json()
    assert [f["id"] for f in listed] == [entry] and listed[0]["needs_review"]

    # "still correct": flag cleared, nothing else changes
    ok = await client.patch(f"/admin/faqs/{entry}", json={"reviewed": True}, headers=GS_INSTRUCTOR)
    assert ok.status_code == 200 and not ok.json()["needs_review"] and ok.json()["review_reason"] is None
    assert (await client.get("/admin/faqs", params={"status": "review"}, headers=GS_INSTRUCTOR)).json() == []

    # edit: the old answer is no longer retrievable, the new one is, approved by the instructor
    edited = await client.patch(
        f"/admin/faqs/{entry}", json={"answer": "Hạn nộp là 22:00 thứ Hai."}, headers=GS_INSTRUCTOR
    )
    assert edited.status_code == 200
    assert edited.json()["approved_by"] == "Giảng viên lớp Google Sheets (placeholder)"
    texts = " ".join(await retrievable_faq_texts(db_session, "GS-KPI-01", "Hạn nộp bài tập?"))
    assert "thứ Hai" in texts and "Chủ nhật" not in texts
    assert await db_session.scalar(select(func.count()).where(Chunk.faq_entry_id == entry)) == 1

    # deactivate: not retrievable any more; reactivate: back
    off = await client.patch(f"/admin/faqs/{entry}", json={"active": False}, headers=GS_INSTRUCTOR)
    assert off.status_code == 200 and not off.json()["active"]
    assert await retrievable_faq_texts(db_session, "GS-KPI-01", "Hạn nộp bài tập?") == []
    on = await client.patch(f"/admin/faqs/{entry}", json={"active": True}, headers=GS_INSTRUCTOR)
    assert on.json()["active"]
    assert await retrievable_faq_texts(db_session, "GS-KPI-01", "Hạn nộp bài tập?")


async def test_faq_api_is_scoped_and_validated(clean_state, client, db_session) -> None:
    auto = await add_faq(db_session, "AUTO-N8N-01", "Q", "A")
    gs = await add_faq(db_session, "GS-KPI-01", "Q", "A")

    assert (await client.get("/admin/faqs")).status_code == 401
    mine = (await client.get("/admin/faqs", headers=GS_INSTRUCTOR)).json()
    assert [f["id"] for f in mine] == [gs]
    other = await client.get("/admin/faqs", params={"class_id": "AUTO-N8N-01"}, headers=GS_INSTRUCTOR)
    assert other.status_code == 403
    hidden = await client.patch(f"/admin/faqs/{auto}", json={"active": False}, headers=GS_INSTRUCTOR)
    assert hidden.status_code == 404
    assert (await faq_state(db_session, auto)).active

    assert (await client.patch(f"/admin/faqs/{gs}", json={}, headers=ADMIN)).status_code == 422
    assert (await client.patch(f"/admin/faqs/{gs}", json={"answer": ""}, headers=ADMIN)).status_code == 422
    assert len((await client.get("/admin/faqs", headers=ADMIN)).json()) == 2
