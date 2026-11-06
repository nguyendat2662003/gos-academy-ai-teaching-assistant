"""Evaluate retrieval and answering on data/eval/golden.yaml (CLAUDE.md §13). Prints a Markdown report.

  python scripts/eval_rag.py                 # retrieval only: hit@k, MRR, cross-class leak, threshold sweep
  python scripts/eval_rag.py --full          # + full pipeline with the configured LLM (costs tokens)
  python scripts/eval_rag.py --full --min-score 0.3 --out docs/eval_latest.md

Run it where the database is reachable with the providers you want to measure, normally inside the stack:
  docker compose exec api python scripts/eval_rag.py --full

--full runs the real pipeline (guard, policy, threshold, LLM, verification) inside ONE database transaction
that is rolled back at the end: tickets and security events it creates leave no trace (no stats pollution).
No message is sent to any group. Keys come from the environment and are never printed.
"""

import argparse
import asyncio
import math
import sys
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path

import yaml
from pydantic import BaseModel, Field

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession  # noqa: E402

from app.agent.pipeline import AgentRequest, answer_question  # noqa: E402
from app.core.classes import get_registry  # noqa: E402
from app.core.config import get_settings  # noqa: E402
from app.db.models import Chunk  # noqa: E402
from app.db.session import get_engine, get_sessionmaker  # noqa: E402
from app.providers.registry import get_embedding_provider, get_llm_provider  # noqa: E402
from app.retrieval.search import hybrid_search  # noqa: E402

GOLDEN = Path("data/eval/golden.yaml")
ANSWERABLE = ("answer", "partial")
GATE_NEGATIVE = ("not_in_material", "other_class")  # should ideally stay below the threshold


class GoldenItem(BaseModel):
    id: str
    class_id: str
    question: str
    expect: str = Field(pattern="^(answer|partial|handoff|refused)$")
    kind: str
    sections: list[str] = Field(default_factory=list)
    reason: str | None = None


@dataclass
class ItemResult:
    item: GoldenItem
    top_score: float | None = None
    retrieved_sections: list[str] = field(default_factory=list)
    first_hit_rank: int | None = None  # 1-based rank of the first expected section
    leaked: int = 0  # retrieved chunks of another class
    outcome: str | None = None
    reason: str | None = None
    cited_sections: list[str] = field(default_factory=list)
    cited_leak: int = 0
    tokens: int = 0
    latency_ms: int = 0


def load_golden(path: Path) -> list[GoldenItem]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    items = [GoldenItem.model_validate(raw) for raw in data["items"]]
    ids = [i.id for i in items]
    if len(ids) != len(set(ids)):
        raise SystemExit("duplicate ids in golden set")
    known = {c.id for c in get_registry().classes}
    if bad := [i.id for i in items if i.class_id not in known]:
        raise SystemExit(f"unknown class_id in {bad}")
    return items


async def run_retrieval(session: AsyncSession, items: list[GoldenItem], top_k: int) -> list[ItemResult]:
    embedder, registry = get_embedding_provider(), get_registry()
    results = []
    for item in items:
        res = ItemResult(item)
        if item.kind != "injection":  # the guard blocks these before retrieval
            r = await hybrid_search(
                session, class_id=item.class_id, question=item.question, embedder=embedder,
                registry=registry, top_k=top_k,
            )  # fmt: skip
            res.top_score = r.top_vector_score
            res.retrieved_sections = [c.section_code or c.location for c in r.chunks]
            allowed = {item.class_id, registry.shared_scope.id}
            res.leaked = sum(c.class_id not in allowed for c in r.chunks)
            hits = [i for i, s in enumerate(res.retrieved_sections, 1) if s in item.sections]
            res.first_hit_rank = hits[0] if hits else None
        results.append(res)
    return results


async def run_full(results: list[ItemResult], min_score: float | None) -> None:
    """Real pipeline per item inside one transaction that is rolled back (savepoint per commit)."""
    settings = get_settings()
    if min_score is not None:
        settings = settings.model_copy(update={"retrieval_min_score": min_score})
    llm, embedder, registry = get_llm_provider(), get_embedding_provider(), get_registry()
    async with get_engine().connect() as conn:
        outer = await conn.begin()
        session = AsyncSession(bind=conn, join_transaction_mode="create_savepoint", expire_on_commit=False)
        try:
            for res in results:
                request = AgentRequest(
                    request_id=f"eval{uuid.uuid4().hex[:12]}",
                    class_id=res.item.class_id,
                    user_hash=f"eval-{uuid.uuid4().hex}",  # fresh user: no conversation history
                    question=res.item.question,
                    channel="eval",
                )
                started = time.perf_counter()
                reply = await answer_question(
                    session, request, llm=llm, embedder=embedder, registry=registry, settings=settings
                )
                res.latency_ms = round((time.perf_counter() - started) * 1000)
                res.outcome, res.reason = reply.outcome, reply.handoff_reason
                res.tokens = reply.input_tokens + reply.output_tokens
                ids = [int(ref.removeprefix("c_")) for ref in reply.cited_refs]
                if ids:
                    rows = (await session.execute(select(Chunk.class_id, Chunk.section_code, Chunk.location)
                                                  .where(Chunk.id.in_(ids)))).all()  # fmt: skip
                    allowed = {res.item.class_id, registry.shared_scope.id}
                    res.cited_sections = [s or loc for _, s, loc in rows]
                    res.cited_leak = sum(c not in allowed for c, _, _ in rows)
                print(f"  {res.item.id}: {res.outcome}", file=sys.stderr)
        finally:
            await session.close()
            await outer.rollback()


# ---------------------------------------------------------------- report


def _pct(n: int, d: int) -> str:
    return "–" if d == 0 else f"{n}/{d} ({100 * n / d:.0f}%)"


def retrieval_report(results: list[ItemResult], top_k: int) -> list[str]:
    labelled = [r for r in results if r.item.sections]
    hits = [r for r in labelled if r.first_hit_rank]
    mrr = sum(1 / r.first_hit_rank for r in hits) / len(labelled) if labelled else 0.0
    leaks = sum(r.leaked for r in results)
    lines = [
        "## Truy xuất",
        "",
        "| Chỉ số | Giá trị |",
        "|---|---|",
        f"| hit@1 | {_pct(sum(r.first_hit_rank == 1 for r in labelled), len(labelled))} |",
        f"| hit@{top_k} | {_pct(len(hits), len(labelled))} |",
        f"| MRR@{top_k} | {mrr:.3f} |",
        f"| Chunk lớp khác bị truy xuất (phải = 0) | **{leaks}** |",
        "",
    ]
    if misses := [r for r in labelled if not r.first_hit_rank]:
        lines += ["Không lấy được mục kỳ vọng trong top-k:", ""]
        lines += [f"- {r.item.id} `{r.item.question}` → kỳ vọng {r.item.sections}, lấy {r.retrieved_sections}"
                  for r in misses]  # fmt: skip
        lines.append("")
    return lines


def threshold_report(results: list[ItemResult]) -> list[str]:
    pos = [r.top_score for r in results if r.item.expect in ANSWERABLE and r.top_score is not None]
    neg = [r.top_score for r in results if r.item.kind in GATE_NEGATIVE and r.top_score is not None]
    if not pos:
        return []
    median = sorted(pos)[len(pos) // 2]
    lines = [
        "## Ngưỡng `RETRIEVAL_MIN_SCORE` (cosine top-1)",
        "",
        f"- Câu có căn cứ: min **{min(pos):.3f}**, trung vị {median:.3f}, max {max(pos):.3f}",
        f"- Câu ngoài giáo trình / lớp khác: min {min(neg):.3f}, max **{max(neg):.3f}**" if neg else "",
        "",
        "| Ngưỡng | Câu có căn cứ qua cổng | Câu không căn cứ bị chặn ngay (không gọi LLM) |",
        "|---|---|---|",
    ]
    for t in [x / 100 for x in range(20, 61, 5)]:
        passed, blocked = sum(s >= t for s in pos), sum(s < t for s in neg)
        lines.append(f"| {t:.2f} | {_pct(passed, len(pos))} | {_pct(blocked, len(neg))} |")
    safe = math.floor((min(pos) - 0.03) * 100) / 100  # keep a margin below the weakest grounded question
    lines += [
        "",
        f"Đề xuất: ngưỡng cao nhất vẫn cho **mọi** câu có căn cứ qua cổng, trừ biên 0.03 → **{safe:.2f}**. "
        "Câu không căn cứ lọt qua cổng vẫn bị chặn ở bước kiểm tra JSON/trích dẫn (D-60).",
        "",
    ]
    return lines


def full_report(results: list[ItemResult]) -> list[str]:
    def ok(r: ItemResult) -> bool:
        expected = {"answer": "answered"}.get(r.item.expect, r.item.expect)
        return r.outcome == expected and (r.item.reason is None or r.reason == r.item.reason)

    def answered(o: str | None) -> bool:
        return o in ("answered", "partial")

    grounded = [r for r in results if answered(r.outcome) and r.item.sections]
    cited_ok = [r for r in grounded if set(r.cited_sections) & set(r.item.sections)]
    avg_ms = sum(r.latency_ms for r in results) // max(len(results), 1)
    wrongly_answered = [r for r in results if answered(r.outcome) and r.item.expect not in ANSWERABLE]
    lines = [
        "## Pipeline đầy đủ (LLM thật)",
        "",
        "| Chỉ số | Giá trị |",
        "|---|---|",
        f"| Quyết định đúng (khớp chính xác `expect`) | {_pct(sum(ok(r) for r in results), len(results))} |",
        "| Quyết định trả lời/không trả lời đúng | "
        f"{_pct(sum(answered(r.outcome) == (r.item.expect in ANSWERABLE) for r in results), len(results))} |",
        f"| Trả lời câu lẽ ra phải chuyển/từ chối (bịa) | **{len(wrongly_answered)}** |",
        f"| Trích dẫn đúng mục kỳ vọng (trong số câu đã trả lời) | {_pct(len(cited_ok), len(grounded))} |",
        f"| Trích dẫn chunk lớp khác (phải = 0) | **{sum(r.cited_leak for r in results)}** |",
        f"| Token LLM (vào + ra) | {sum(r.tokens for r in results)} |",
        f"| Thời gian xử lý TB / câu (không gồm hàng đợi) | {avg_ms} ms |",
        "",
        "| Theo loại | Đúng |",
        "|---|---|",
    ]
    for kind in sorted({r.item.kind for r in results}):
        group = [r for r in results if r.item.kind == kind]
        lines.append(f"| {kind} | {_pct(sum(ok(r) for r in group), len(group))} |")
    lines += [
        "",
        "| id | lớp | kỳ vọng | kết quả | lý do | top | mục trích dẫn |",
        "|---|---|---|---|---|---|---|",
    ]
    for r in results:
        mark = "" if ok(r) else " ⚠️"
        top = "–" if r.top_score is None else f"{r.top_score:.3f}"
        expect = r.item.expect + (f" ({r.item.reason})" if r.item.reason else "")
        cited = ", ".join(dict.fromkeys(r.cited_sections))
        cells = [r.item.id, r.item.class_id, expect, f"{r.outcome}{mark}", r.reason or "", top, cited]
        lines.append("| " + " | ".join(cells) + " |")
    lines.append("")
    return lines


async def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--golden", type=Path, default=GOLDEN)
    parser.add_argument("--full", action="store_true", help="also run the full pipeline with the real LLM")
    parser.add_argument("--min-score", type=float, help="override RETRIEVAL_MIN_SCORE for --full")
    parser.add_argument("--out", type=Path, help="also write the Markdown report to this file")
    args = parser.parse_args()

    settings = get_settings()
    items = load_golden(args.golden)
    async with get_sessionmaker()() as session:
        results = await run_retrieval(session, items, settings.retrieval_top_k)
    if args.full:
        await run_full(results, args.min_score)

    emb = get_embedding_provider()
    min_score = args.min_score if args.min_score is not None else settings.retrieval_min_score
    lines = [
        "# Kết quả đánh giá RAG",
        "",
        f"- Bộ câu hỏi: `{args.golden.as_posix()}` ({len(items)} câu)",
        f"- Embedding: `{emb.name}:{emb.model}` (dim {emb.dim}); top_k = {settings.retrieval_top_k}",
    ]
    if args.full:
        llm = get_llm_provider()
        lines.append(f"- LLM: `{llm.name}:{llm.model}`; RETRIEVAL_MIN_SCORE = {min_score}")
    lines += ["", *retrieval_report(results, settings.retrieval_top_k), *threshold_report(results)]
    if args.full:
        lines += full_report(results)
    report = "\n".join(lines)
    print(report)
    if args.out:
        args.out.write_text(report + "\n", encoding="utf-8")
    if sum(r.leaked + r.cited_leak for r in results):
        raise SystemExit("CROSS-CLASS LEAK DETECTED")


if __name__ == "__main__":
    asyncio.run(main())
