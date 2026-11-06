"""Knowledge base: scoping, versioning (update / unchanged / delete / reindex), failure safety, admin API."""

import io
from pathlib import Path

import pytest
from docx import Document as DocxWriter
from sqlalchemy import func, select

from app.core.classes import get_registry
from app.db.models import Chunk, Document, SecurityEvent
from app.ingestion import indexer
from app.ingestion.text import scope_prefix
from app.providers.base import EmbeddingDimensionError, check_dimensions
from app.providers.fake import FakeEmbeddingProvider, fake_vector

pytestmark = pytest.mark.db

SAMPLES = {
    "GS-KPI-01": Path("data/samples/GS-KPI-01/01_Giao_trinh_Google_Sheets_KPI_Dashboard.docx"),
    "AUTO-N8N-01": Path("data/samples/AUTO-N8N-01/02_Giao_trinh_AI_Automation_n8n.docx"),
    "COMMON": Path("data/samples/COMMON/03_FAQ_Quy_dinh_lop_hoc_GIA_LAP.docx"),
}
ADMIN = {"X-Admin-Key": "test-admin-key"}


def make_docx(sections: list[tuple[str, str]]) -> bytes:
    doc = DocxWriter()
    doc.add_paragraph("Tài liệu kiểm thử", style="Title")
    for heading, body in sections:
        doc.add_heading(heading, level=1)
        doc.add_paragraph(body)
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


@pytest.fixture
def embedder() -> FakeEmbeddingProvider:
    return FakeEmbeddingProvider("fake-embedding", 768)


async def ingest(session, embedder, data: bytes, filename: str, scope: str, **kw) -> indexer.IngestReport:
    return await indexer.index_file(
        session,
        data=data,
        filename=filename,
        origin_scope=scope,
        embedder=embedder,
        registry=get_registry(),
        **kw,
    )


async def active_chunks(session, class_id: str | None = None) -> list[Chunk]:
    stmt = select(Chunk).join(Document, Document.id == Chunk.document_id).where(Document.status == "active")
    if class_id:
        stmt = stmt.where(Chunk.class_id == class_id)
    return list((await session.execute(stmt)).scalars())


# ------------------------------------------------------------------ real sample material


async def test_ingest_samples_scopes_every_chunk_correctly(clean_state, db_session, embedder) -> None:
    for scope, path in SAMPLES.items():
        await ingest(db_session, embedder, path.read_bytes(), path.name, scope)

    counts = {
        scope: len(await active_chunks(db_session, scope)) for scope in ("GS-KPI-01", "AUTO-N8N-01", "COMMON")
    }
    # GS: 8 sections of 01 + GS-CLASS-01 + 4 FAQ rows of 03
    # AUTO: 10 sections of 02 + AUTO-CLASS-01 + 4 FAQ rows; COMMON: COMMON-01..04
    assert counts == {"GS-KPI-01": 13, "AUTO-N8N-01": 15, "COMMON": 4}

    registry = get_registry()
    for chunk in await active_chunks(db_session):
        owner = registry.scope_for_prefix(scope_prefix(chunk.section_code))
        assert owner == chunk.class_id, (chunk.location, chunk.class_id)
    auto_text = " ".join(c.content for c in await active_chunks(db_session, "AUTO-N8N-01"))
    gs_text = " ".join(c.content for c in await active_chunks(db_session, "GS-KPI-01"))
    assert "IMPORTRANGE" not in auto_text and "SUMIFS" not in auto_text
    assert "n8n" not in gs_text.lower() and "Webhook" not in gs_text
    # the mixed FAQ file became 3 documents, one per scope
    docs = await db_session.execute(
        select(Document.class_id).where(Document.filename == SAMPLES["COMMON"].name)
    )
    assert sorted(docs.scalars()) == ["AUTO-N8N-01", "COMMON", "GS-KPI-01"]
    assert all(c.embedding is not None for c in await active_chunks(db_session))


async def test_reingest_same_content_is_skipped(clean_state, db_session, embedder) -> None:
    path = SAMPLES["COMMON"]
    await ingest(db_session, embedder, path.read_bytes(), path.name, "COMMON")
    calls = embedder.calls
    report = await ingest(db_session, embedder, path.read_bytes(), path.name, "COMMON")
    assert {r.status for r in report.results} == {"unchanged"}
    assert embedder.calls == calls
    assert await db_session.scalar(select(func.count()).select_from(Document)) == 3


async def test_switching_embedding_model_reembeds(clean_state, db_session, embedder) -> None:
    data = make_docx([("GS-90  A", "Nội dung A.")])
    await ingest(db_session, embedder, data, "a.docx", "GS-KPI-01")
    other_model = FakeEmbeddingProvider("another-embedding-model", 768)
    report = await ingest(db_session, other_model, data, "a.docx", "GS-KPI-01")
    assert (report.results[0].status, report.results[0].version) == ("indexed", 2)


# ------------------------------------------------------------------ versioning


async def test_update_replaces_old_content(clean_state, db_session, embedder) -> None:
    v1 = make_docx([("AUTO-95  Lịch họp", "Nhóm dự án họp vào thứ Hai hằng tuần.")])
    v2 = make_docx([("AUTO-95  Lịch họp", "Nhóm dự án họp vào thứ Sáu hằng tuần.")])
    r1 = await ingest(db_session, embedder, v1, "lich.docx", "AUTO-N8N-01")
    r2 = await ingest(db_session, embedder, v2, "lich.docx", "AUTO-N8N-01")
    assert (r2.results[0].status, r2.results[0].version) == ("indexed", 2)

    texts = [c.content for c in await active_chunks(db_session, "AUTO-N8N-01")]
    assert any("thứ Sáu" in t for t in texts) and not any("thứ Hai" in t for t in texts)
    old = await db_session.get(Document, r1.results[0].document_id)
    await db_session.refresh(old)
    assert old.status == "superseded"
    old_chunks = await db_session.scalar(select(func.count()).where(Chunk.document_id == old.id))
    assert old_chunks == 0


async def test_delete_removes_chunks(clean_state, db_session, embedder) -> None:
    report = await ingest(
        db_session, embedder, make_docx([("GS-90  A", "Nội dung A.")]), "a.docx", "GS-KPI-01"
    )
    doc_id = report.results[0].document_id
    assert await indexer.delete_document(db_session, doc_id)
    assert not await indexer.delete_document(db_session, doc_id)
    assert await active_chunks(db_session, "GS-KPI-01") == []
    assert await db_session.scalar(select(func.count()).where(Chunk.document_id == doc_id)) == 0


async def test_reindex_creates_new_version(clean_state, db_session, embedder) -> None:
    report = await ingest(
        db_session, embedder, make_docx([("GS-90  A", "Nội dung A.")]), "a.docx", "GS-KPI-01"
    )
    again = await indexer.reindex_document(
        db_session, report.results[0].document_id, embedder=embedder, registry=get_registry()
    )
    assert (again.results[0].status, again.results[0].version) == ("indexed", 2)
    assert len(await active_chunks(db_session, "GS-KPI-01")) == 1


async def test_scope_removed_from_mixed_file(clean_state, db_session, embedder) -> None:
    v1 = make_docx([("COMMON-90  Chung", "Quy định chung."), ("GS-90  Riêng GS", "Nội dung GS.")])
    v2 = make_docx([("COMMON-90  Chung", "Quy định chung.")])
    await ingest(db_session, embedder, v1, "mix.docx", "COMMON")
    report = await ingest(db_session, embedder, v2, "mix.docx", "COMMON")
    assert {(r.scope, r.status) for r in report.results} == {
        ("COMMON", "unchanged"),
        ("GS-KPI-01", "removed"),
    }
    assert await active_chunks(db_session, "GS-KPI-01") == []


# ------------------------------------------------------------------ safety


async def test_cross_scope_section_in_class_upload_is_refused(clean_state, db_session, embedder) -> None:
    data = make_docx([("AUTO-90  OK", "n8n."), ("GS-91  Lạc lớp", "SUMIFS.")])
    with pytest.raises(indexer.ScopeConflictError):
        await ingest(db_session, embedder, data, "lac.docx", "AUTO-N8N-01")
    data = make_docx([("COMMON-90  Chung", "Quy định.")])
    with pytest.raises(indexer.ScopeConflictError):  # a class may not publish into the shared scope
        await ingest(db_session, embedder, data, "chung.docx", "GS-KPI-01")
    assert await db_session.scalar(select(func.count()).select_from(Document)) == 0


async def test_embedding_failure_keeps_previous_version(clean_state, db_session, embedder) -> None:
    class Broken(FakeEmbeddingProvider):
        async def embed(self, texts, kind):  # type: ignore[no-untyped-def]
            raise TimeoutError("provider down")

    v1 = make_docx([("GS-90  Lịch", "Thứ Ba.")])
    await ingest(db_session, embedder, v1, "lich.docx", "GS-KPI-01")
    v2 = make_docx([("GS-90  Lịch", "Thứ Tư.")])
    report = await ingest(db_session, Broken("x", 768), v2, "lich.docx", "GS-KPI-01")
    assert (report.results[0].status, report.results[0].error) == ("failed", "TimeoutError")
    texts = [c.content for c in await active_chunks(db_session, "GS-KPI-01")]
    assert len(texts) == 1 and "Thứ Ba" in texts[0]


async def test_injection_in_document_is_flagged_and_logged(clean_state, db_session, embedder) -> None:
    data = Path("tests/fixtures/injection_lesson.docx").read_bytes()
    report = await ingest(db_session, embedder, data, "injection_lesson.docx", "AUTO-N8N-01")
    assert report.results[0].flagged == 1
    flagged = [c.location for c in await active_chunks(db_session) if c.flagged_injection]
    assert flagged == ["AUTO-92 Ghi chú của tác giả"]
    events = (await db_session.execute(select(SecurityEvent))).scalars().all()
    assert [(e.type, e.class_id) for e in events] == [("prompt_injection", "AUTO-N8N-01")]


async def test_document_without_content_is_refused(clean_state, db_session, embedder) -> None:
    doc = DocxWriter()
    doc.add_paragraph("chỉ có một đoạn văn, không có heading")
    buf = io.BytesIO()
    doc.save(buf)
    with pytest.raises(indexer.IngestError):
        await ingest(db_session, embedder, buf.getvalue(), "empty.docx", "GS-KPI-01")


def test_dimension_mismatch_detected() -> None:
    with pytest.raises(EmbeddingDimensionError):
        check_dimensions([[0.1, 0.2]], 768)


def test_fake_embedding_is_deterministic_and_meaningful() -> None:
    import math

    def cos(a, b):  # type: ignore[no-untyped-def]
        return sum(x * y for x, y in zip(a, b, strict=True))

    a = fake_vector("Lỗi 401 Unauthorized khi gọi API trong n8n", 768)
    assert a == fake_vector("Lỗi 401 Unauthorized khi gọi API trong n8n", 768)
    assert math.isclose(sum(x * x for x in a), 1.0, rel_tol=1e-9)
    near = fake_vector("loi 401 khi goi API n8n", 768)
    far = fake_vector("IMPORTRANGE đồng bộ ghi chú", 768)
    assert cos(a, near) > cos(a, far)


# ------------------------------------------------------------------ admin API


async def test_documents_api(client, db_session) -> None:
    xlsx = Path("tests/fixtures/faq_custom_headers.xlsx").read_bytes()
    files = {"file": ("faq.xlsx", xlsx, "application/octet-stream")}

    assert (
        await client.post("/admin/documents", files=files, data={"class_id": "GS-KPI-01"})
    ).status_code == 401

    bad = await client.post(
        "/admin/documents",
        files={"file": ("x.txt", b"hi", "text/plain")},
        data={"class_id": "GS-KPI-01"},
        headers=ADMIN,
    )
    assert bad.status_code == 422
    unknown = await client.post("/admin/documents", files=files, data={"class_id": "NOPE"}, headers=ADMIN)
    assert unknown.status_code == 422

    up = await client.post("/admin/documents", files=files, data={"class_id": "GS-KPI-01"}, headers=ADMIN)
    assert up.status_code == 200, up.text
    result = up.json()["results"][0]
    assert (result["scope"], result["status"], result["chunks"]) == ("GS-KPI-01", "indexed", 2)
    assert up.json()["warnings"] == ["Sheet Hoi dap, dòng 3: thiếu câu hỏi hoặc trả lời — bỏ qua"]

    listed = (await client.get("/admin/documents", params={"class_id": "GS-KPI-01"}, headers=ADMIN)).json()
    assert [(d["filename"], d["chunks"], d["status"]) for d in listed] == [("faq.xlsx", 2, "active")]

    doc_id = result["document_id"]
    re = await client.post(f"/admin/documents/{doc_id}/reindex", headers=ADMIN)
    assert re.status_code == 200 and re.json()["results"][0]["version"] == 2
    new_id = re.json()["results"][0]["document_id"]
    assert (await client.delete(f"/admin/documents/{new_id}", headers=ADMIN)).status_code == 200
    assert (await client.delete(f"/admin/documents/{new_id}", headers=ADMIN)).status_code == 404
    assert (await client.post("/admin/documents/999999/reindex", headers=ADMIN)).status_code == 404
    assert (await client.post(f"/admin/documents/{new_id}/reindex", headers=ADMIN)).status_code == 409


async def test_uploaded_filename_cannot_escape_storage(client) -> None:
    data = make_docx([("GS-90  A", "Nội dung.")])
    resp = await client.post(
        "/admin/documents",
        files={"file": ("../../evil.docx", data, "application/octet-stream")},
        data={"class_id": "GS-KPI-01"},
        headers=ADMIN,
    )
    assert resp.status_code == 200 and resp.json()["filename"] == "evil.docx"


# ------------------------------------------------------------------ scripts/ingest_samples.py


async def test_ingest_samples_script_is_idempotent_and_fails_loudly(
    clean_state, db_session, monkeypatch, capsys
) -> None:
    """`docker compose up` runs the script every time (D-82): the 2nd run embeds nothing, and a broken
    embedding provider gives exit code 1 so `migrate` fails instead of starting a bot with no material."""
    from scripts import ingest_samples

    embedder = FakeEmbeddingProvider("fake-embedding", 768)
    monkeypatch.setattr(ingest_samples, "get_embedding_provider", lambda: embedder)
    assert await ingest_samples.main([]) == 0
    first = embedder.calls
    assert first > 0 and len(await active_chunks(db_session)) == 32
    assert await ingest_samples.main([]) == 0
    assert embedder.calls == first  # unchanged content: skipped by hash, no embedding call
    capsys.readouterr()

    class BrokenEmbedder(FakeEmbeddingProvider):
        async def embed(self, texts, kind):  # type: ignore[no-untyped-def,override]
            raise PermissionError("401 invalid api key")

    monkeypatch.setattr(ingest_samples, "get_embedding_provider", lambda: BrokenEmbedder("other-model", 768))
    assert await ingest_samples.main([]) == 1  # new model -> must re-embed -> fails
    out = capsys.readouterr().out
    assert "INGEST FAILED" in out and "invalid api key" not in out  # only the error type is printed
    assert len(await active_chunks(db_session)) == 32  # previous version stays active
