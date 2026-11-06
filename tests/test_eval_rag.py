"""scripts/eval_rag.py: the golden set is consistent with the material, and --full leaves no trace."""

import sys
from pathlib import Path

import pytest
from sqlalchemy import func, select

from app.db.models import HandoffTicket, SecurityEvent
from app.ingestion.chunker import chunk_document
from app.ingestion.parsers import parse_file
from tests.conftest import SAMPLE_FILES

sys.path.insert(0, str(Path("scripts").resolve()))
import eval_rag  # noqa: E402


def test_golden_set_is_valid_and_points_at_real_sections() -> None:
    items = eval_rag.load_golden(eval_rag.GOLDEN)
    assert len(items) >= 30
    codes = {c.section_code for f in SAMPLE_FILES.values() for c in chunk_document(parse_file(Path(f)))}
    for item in items:
        assert set(item.sections) <= codes, item.id  # no typo in expected sections
        if item.expect in ("answer", "partial"):
            assert item.sections, item.id
        else:
            assert not item.sections, item.id
    # both classes, every kind, and the same question asked in two classes
    assert {i.class_id for i in items} == {"GS-KPI-01", "AUTO-N8N-01"}
    assert {i.kind for i in items} == {"material", "not_in_material", "other_class", "policy", "injection"}
    by_q: dict[str, set[str]] = {}
    for i in items:
        by_q.setdefault(i.question, set()).add(i.class_id)
    assert any(len(v) == 2 for v in by_q.values())


@pytest.mark.db
async def test_eval_runs_offline_without_leaks_or_side_effects(kb, db_session) -> None:
    items = eval_rag.load_golden(eval_rag.GOLDEN)
    results = await eval_rag.run_retrieval(db_session, items, top_k=5)
    assert sum(r.leaked for r in results) == 0
    assert any(r.first_hit_rank for r in results)

    await eval_rag.run_full(results, min_score=0.0)
    assert {r.outcome for r in results} >= {"answered", "refused", "handoff"}
    assert sum(r.cited_leak for r in results) == 0
    # everything the pipeline wrote (tickets, security events) was rolled back
    assert await db_session.scalar(select(func.count()).select_from(HandoffTicket)) == 0
    assert await db_session.scalar(select(func.count()).select_from(SecurityEvent)) == 0

    report = "\n".join(
        eval_rag.retrieval_report(results, 5)
        + eval_rag.threshold_report(results)
        + eval_rag.full_report(results)
    )
    assert "Chunk lớp khác bị truy xuất (phải = 0) | **0**" in report and "| GS-01 |" in report
