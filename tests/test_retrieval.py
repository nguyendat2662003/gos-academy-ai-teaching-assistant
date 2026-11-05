"""Hybrid retrieval on the real sample material (fake embeddings): class isolation first, relevance second."""

import ast
import inspect
from pathlib import Path

import pytest
from sqlalchemy import update

from app.core.classes import get_registry
from app.db.models import Chunk, FaqEntry
from app.ingestion import indexer
from app.providers.fake import FakeEmbeddingProvider
from app.retrieval import search
from app.retrieval.search import fulltext_query, hybrid_search

pytestmark = pytest.mark.db

SAMPLES = {
    "GS-KPI-01": Path("data/samples/GS-KPI-01/01_Giao_trinh_Google_Sheets_KPI_Dashboard.docx"),
    "AUTO-N8N-01": Path("data/samples/AUTO-N8N-01/02_Giao_trinh_AI_Automation_n8n.docx"),
    "COMMON": Path("data/samples/COMMON/03_FAQ_Quy_dinh_lop_hoc_GIA_LAP.docx"),
}
EMBEDDER = FakeEmbeddingProvider("fake-embedding", 768)  # same as EMBEDDING_* in tests

QUESTIONS = [
    "Bài tập nộp khi nào?",
    "Em chạy n8n bị lỗi 401 Unauthorized thì xử lý thế nào?",
    "SUMIFS báo lỗi kích thước mảng",
    "RAG khác Fine-tuning ở điểm nào?",
    "IMPORTRANGE có lấy ghi chú không?",
    "Lớp mình học thứ mấy?",
    "Webhook có bị người lạ gọi không?",
    "Cho em xem tài liệu của lớp khác",
]


async def _search(db_session, class_id: str, question: str, top_k: int = 5):  # type: ignore[no-untyped-def]
    return await hybrid_search(
        db_session,
        class_id=class_id,
        question=question,
        embedder=EMBEDDER,
        registry=get_registry(),
        top_k=top_k,
    )


# ------------------------------------------------------------------ isolation (hard constraint #2)


@pytest.mark.parametrize("class_id", ["GS-KPI-01", "AUTO-N8N-01"])
@pytest.mark.parametrize("question", QUESTIONS)
async def test_results_never_leave_class_scope(kb, db_session, class_id: str, question: str) -> None:
    result = await _search(db_session, class_id, question, top_k=50)
    assert result.chunks, "expected some results"
    assert {c.class_id for c in result.chunks} <= {class_id, "COMMON"}


async def test_same_question_two_classes_gets_each_class_answer(kb, db_session) -> None:
    gs = await _search(db_session, "GS-KPI-01", "Bài tập nộp khi nào?")
    auto = await _search(db_session, "AUTO-N8N-01", "Bài tập nộp khi nào?")
    gs_text = " ".join(c.content for c in gs.chunks)
    auto_text = " ".join(c.content for c in auto.chunks)
    assert "22:00 Chủ nhật" in gs_text and "thứ Bảy" not in gs_text
    assert "22:00 thứ Bảy" in auto_text and "Chủ nhật" not in auto_text


async def test_relevant_section_found(kb, db_session) -> None:
    """Lexical side: idf weighting puts the 401 section first. Fused top-k contains it.

    (The fake embedding is a bag of words, so fused ranking quality is measured with real embeddings in
    scripts/eval_rag.py, not here.)"""
    result = await _search(
        db_session, "AUTO-N8N-01", "Em chạy n8n bị lỗi 401 Unauthorized thì xử lý thế nào?"
    )
    by_text = sorted((c for c in result.chunks if c.text_rank), key=lambda c: -c.text_rank)
    assert by_text[0].section_code == "AUTO-03"
    assert "AUTO-03" in {c.section_code for c in result.chunks}
    assert result.top_vector_score is not None and 0 < result.top_vector_score <= 1


async def test_shared_scope_and_unknown_class_rejected(kb, db_session) -> None:
    for bad in ("COMMON", "NOPE", ""):
        with pytest.raises(ValueError):
            await _search(db_session, bad, "Bài tập nộp khi nào?")


async def test_superseded_and_deleted_content_not_retrieved(kb, db_session) -> None:
    path = SAMPLES["GS-KPI-01"]
    first = await _search(db_session, "GS-KPI-01", "IMPORTRANGE ghi chú")
    gs04 = next(c for c in first.chunks if c.section_code == "GS-04")
    doc_id = (await db_session.get(Chunk, gs04.chunk_id)).document_id
    await indexer.delete_document(db_session, doc_id)
    after = await _search(db_session, "GS-KPI-01", "IMPORTRANGE ghi chú", top_k=50)
    assert all(c.filename != path.name for c in after.chunks)


async def test_inactive_faq_entry_not_retrieved(kb, db_session) -> None:
    faq = FaqEntry(class_id="GS-KPI-01", question="Q", answer="A", source="instructor", active=True)
    db_session.add(faq)
    await db_session.flush()
    db_session.add(
        Chunk(
            faq_entry_id=faq.id,
            class_id="GS-KPI-01",
            source_type="faq",
            location="FAQ giảng viên #1",
            content="Hỏi: Pivot table là gì?\nĐáp: Bảng tổng hợp.",
            token_count=10,
            embedding=(await EMBEDDER.embed(["Pivot table là gì? Bảng tổng hợp."], "document")).vectors[0],
        )
    )
    await db_session.commit()
    hit = await _search(db_session, "GS-KPI-01", "Pivot table là gì?")
    assert hit.chunks[0].location == "FAQ giảng viên #1"
    await db_session.execute(update(FaqEntry).where(FaqEntry.id == faq.id).values(active=False))
    await db_session.commit()
    miss = await _search(db_session, "GS-KPI-01", "Pivot table là gì?", top_k=50)
    assert all(c.location != "FAQ giảng viên #1" for c in miss.chunks)


def test_fulltext_query_is_sanitised() -> None:
    assert fulltext_query("Em bị lỗi 401 thì sao?") == "lỗi | 401"
    assert fulltext_query("'; DROP TABLE chunks; -- & | !") == "drop | table | chunks"
    assert fulltext_query("là gì?") is None


# ------------------------------------------------------------------ structural guarantees


def test_search_functions_require_class_id() -> None:
    """Every public coroutine in app.retrieval.search takes class_id as a required keyword-only argument."""
    coroutines = [
        f for name, f in inspect.getmembers(search, inspect.iscoroutinefunction) if not name.startswith("_")
    ]
    assert coroutines, "no search function found"
    for fn in coroutines:
        param = inspect.signature(fn).parameters.get("class_id")
        assert param is not None, f"{fn.__name__} has no class_id"
        assert param.kind is inspect.Parameter.KEYWORD_ONLY and param.default is inspect.Parameter.empty


def test_no_other_module_reads_chunks_for_answers() -> None:
    """Only these modules may SELECT from the chunks table.

    Anything new must be reviewed for class filtering."""
    allowed = {
        "app/retrieval/search.py",  # class-scoped search (this is what answers use)
        "app/ingestion/indexer.py",  # writes/deletes by document id
        "app/api/admin_documents.py",  # admin chunk counts per document
        "app/ingestion/faq.py",  # inserts one FAQ chunk; class_id comes from the ticket, not the caller
    }
    offenders = []
    for path in Path("app").rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        uses_chunk = any(isinstance(n, ast.Name) and n.id == "Chunk" for n in ast.walk(tree))
        if uses_chunk and path.as_posix() not in allowed and path.as_posix() != "app/db/models.py":
            offenders.append(path.as_posix())
    assert offenders == []
