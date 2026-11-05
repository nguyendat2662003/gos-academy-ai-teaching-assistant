"""Aggregates behind GET /admin/stats (CLAUDE.md §11).

Source of truth = token counts in request_logs / documents / faq_entries. Cost is derived at query time:
tokens × the current config/pricing.yaml, so prices filled in later also price earlier traffic, and an unknown
price makes the cost explicitly incomplete instead of a silent 0 (DECISIONS D-70). request_logs.cost_usd is a
per-request snapshot taken at write time; with unchanged prices both agree (tested).

Days are calendar days in Vietnam time. Asia/Ho_Chi_Minh has no DST, so the Python side uses a fixed +07:00
offset (no tz database needed on Windows) and SQL uses the IANA name for grouping.
"""

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone

from sqlalchemy import case, func, literal_column, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.pricing import Pricing
from app.db.models import Document, FaqEntry, Outcome, RequestLog, SecurityEvent

REPORT_TZ = "Asia/Ho_Chi_Minh"
VN = timezone(timedelta(hours=7), "ICT")
BOT_OUTCOMES = (Outcome.ANSWERED, Outcome.PARTIAL, Outcome.HANDOFF, Outcome.REFUSED, Outcome.ERROR)
COUNTED = (*BOT_OUTCOMES, Outcome.IGNORED, Outcome.DUPLICATE, Outcome.RATE_LIMITED)
UNKNOWN_CLASS = (
    "(chưa xác định)"  # duplicates are rejected before the group is resolved (CLAUDE.md §5 step 3)
)


@dataclass(frozen=True)
class StatsFilter:
    class_id: str | None = None
    date_from: date | None = None  # inclusive, Vietnam calendar day
    date_to: date | None = None  # inclusive

    def where(self, created_col, class_col):  # type: ignore[no-untyped-def]
        conds = []
        if self.class_id:
            conds.append(class_col == self.class_id)
        if self.date_from:
            conds.append(created_col >= datetime.combine(self.date_from, time.min, VN))
        if self.date_to:
            conds.append(created_col < datetime.combine(self.date_to + timedelta(days=1), time.min, VN))
        return conds


# Constants rendered inline (not bound): the same expression must appear identically in SELECT and GROUP BY.
_TZ_SQL = literal_column(f"'{REPORT_TZ}'")
_DAY_FMT = literal_column("'YYYY-MM-DD'")
_UNKNOWN_SQL = literal_column(f"'{UNKNOWN_CLASS}'")


def _day(col):  # type: ignore[no-untyped-def]
    return func.to_char(func.timezone(_TZ_SQL, col), _DAY_FMT)


class _Cost:
    """Accumulates a cost; becomes None (and remembers the model) as soon as one price is unknown."""

    def __init__(self, missing: set[str]) -> None:
        self.value: float | None = 0.0
        self.missing = missing

    def add(self, amount: float | None, model: str | None) -> None:
        if amount is None:
            self.missing.add(model or "(không rõ model)")
            self.value = None
        elif self.value is not None:
            self.value += amount

    def result(self) -> float | None:
        return None if self.value is None else round(self.value, 8)


def _empty_metrics() -> dict[str, object]:
    return {
        "questions": 0,
        **{o.value: 0 for o in COUNTED},
        "tickets_by_reason": {},
        "latency_ms_avg": None,
        "latency_ms_p95": None,
        "input_tokens": 0,
        "output_tokens": 0,
        "embedding_tokens": 0,
        "cost_usd": 0.0,
    }


async def _request_level(  # type: ignore[no-untyped-def]
    session: AsyncSession, keys: list, where: list, pricing: Pricing, fallback_emb: str, missing: set[str]
) -> dict[tuple, dict[str, object]]:
    """Metrics of request_logs grouped by `keys` ([] = one total row)."""
    o = RequestLog.outcome
    bot = o.in_(BOT_OUTCOMES)
    bot_latency = case((bot, RequestLog.latency_ms))
    counts = (
        select(
            *keys,
            func.count().filter(bot).label("questions"),
            *[func.count().filter(o == x).label(x.value) for x in COUNTED],
            func.avg(bot_latency).label("lat_avg"),
            func.percentile_cont(0.95).within_group(bot_latency).label("lat_p95"),
            func.coalesce(func.sum(RequestLog.input_tokens), 0).label("input_tokens"),
            func.coalesce(func.sum(RequestLog.output_tokens), 0).label("output_tokens"),
            func.coalesce(func.sum(RequestLog.embedding_tokens), 0).label("embedding_tokens"),
        )
        .where(*where)
        .group_by(*keys)
    )
    out: dict[tuple, dict[str, object]] = {}
    for row in await session.execute(counts):
        key = tuple(row[: len(keys)])
        m = _empty_metrics()
        m["questions"] = row.questions
        for x in COUNTED:
            m[x.value] = getattr(row, x.value)
        m["latency_ms_avg"] = None if row.lat_avg is None else round(float(row.lat_avg))
        m["latency_ms_p95"] = None if row.lat_p95 is None else round(float(row.lat_p95))
        m["input_tokens"], m["output_tokens"] = int(row.input_tokens), int(row.output_tokens)
        m["embedding_tokens"] = int(row.embedding_tokens)
        out[key] = m

    reasons = (
        select(*keys, RequestLog.handoff_reason, func.count())
        .where(*where, RequestLog.handoff_reason.is_not(None))
        .group_by(*keys, RequestLog.handoff_reason)
    )
    for row in await session.execute(reasons):
        out[tuple(row[: len(keys)])]["tickets_by_reason"][row[len(keys)]] = row[len(keys) + 1]  # type: ignore[index]

    # cost: tokens per (keys, model, embedding model) x current prices
    tokens = (
        select(
            *keys,
            RequestLog.model,
            RequestLog.embedding_model,
            func.sum(RequestLog.input_tokens),
            func.sum(RequestLog.output_tokens),
            func.sum(RequestLog.embedding_tokens),
        )
        .where(*where)
        .group_by(*keys, RequestLog.model, RequestLog.embedding_model)
    )
    costs: dict[tuple, _Cost] = defaultdict(lambda: _Cost(missing))
    for row in await session.execute(tokens):
        key, (model, emb_model, tin, tout, temb) = tuple(row[: len(keys)]), row[len(keys) :]
        emb_model = emb_model or fallback_emb  # rows written before migration 0003
        costs[key].add(pricing.llm_cost(model, int(tin or 0), int(tout or 0)), model)
        costs[key].add(pricing.embedding_cost(emb_model, int(temb or 0)), emb_model)
    for key, m in out.items():
        m["cost_usd"] = costs[key].result() if key in costs else 0.0
    return out


async def _ingest(  # type: ignore[no-untyped-def]
    session: AsyncSession, f: StatsFilter, pricing: Pricing, fallback_emb: str, missing: set[str]
) -> dict[str, object]:
    """Embedding spent on indexing: every document version (superseded ones were paid too) + FAQ entries."""
    by_class: dict[str, dict[str, object]] = {}
    total_cost = _Cost(missing)
    sources = (
        (Document, "documents"),
        (FaqEntry, "faq_entries"),
    )
    for model_cls, label in sources:
        stmt = (
            select(
                model_cls.class_id,
                model_cls.embedding_model,
                func.count(),
                func.coalesce(func.sum(model_cls.embedding_tokens), 0),
            )
            .where(*f.where(model_cls.created_at, model_cls.class_id))
            .group_by(model_cls.class_id, model_cls.embedding_model)
        )
        for class_id, emb_model, n, tokens in await session.execute(stmt):
            emb_model = emb_model or fallback_emb
            entry = by_class.setdefault(
                class_id,
                {
                    "class_id": class_id,
                    "documents": 0,
                    "faq_entries": 0,
                    "embedding_tokens": 0,
                    "_cost": _Cost(missing),
                },
            )
            entry[label] += n  # type: ignore[operator]
            entry["embedding_tokens"] += int(tokens)  # type: ignore[operator]
            cost = pricing.embedding_cost(emb_model, int(tokens))
            entry["_cost"].add(cost, emb_model)  # type: ignore[attr-defined]
            total_cost.add(cost, emb_model)
    rows = []
    for entry in sorted(by_class.values(), key=lambda e: str(e["class_id"])):
        entry["cost_usd"] = entry.pop("_cost").result()  # type: ignore[attr-defined]
        rows.append(entry)
    return {
        "embedding_tokens": sum(int(e["embedding_tokens"]) for e in rows),  # type: ignore[call-overload]
        "cost_usd": total_cost.result(),
        "by_class": rows,
    }


async def _security(session: AsyncSession, f: StatsFilter) -> dict[str, object]:
    stmt = (
        select(SecurityEvent.type, func.count())
        .where(*f.where(SecurityEvent.created_at, SecurityEvent.class_id))
        .group_by(SecurityEvent.type)
    )
    by_type = {t: n for t, n in await session.execute(stmt)}
    return {"total": sum(by_type.values()), "by_type": by_type}


async def compute_stats(
    session: AsyncSession, f: StatsFilter, *, pricing: Pricing, fallback_embedding_model: str
) -> dict[str, object]:
    missing: set[str] = set()
    where = f.where(RequestLog.created_at, RequestLog.class_id)

    async def level(keys: list) -> dict[tuple, dict[str, object]]:  # type: ignore[type-arg]
        return await _request_level(session, keys, where, pricing, fallback_embedding_model, missing)

    total = (await level([])).get((), _empty_metrics())
    by_class = await level([func.coalesce(RequestLog.class_id, _UNKNOWN_SQL)])
    by_day = await level([_day(RequestLog.created_at)])
    ingest = await _ingest(session, f, pricing, fallback_embedding_model, missing)
    return {
        "filters": {
            "class_id": f.class_id,
            "from": f.date_from.isoformat() if f.date_from else None,
            "to": f.date_to.isoformat() if f.date_to else None,
            "timezone": REPORT_TZ,
        },
        "total": total,
        "by_class": [{"class_id": k[0], **v} for k, v in sorted(by_class.items())],
        "by_day": [{"day": k[0], **v} for k, v in sorted(by_day.items())],
        "ingest": ingest,
        "security_events": await _security(session, f),
        "pricing": {
            "checked_at": pricing.checked_at,
            "currency": pricing.currency,
            "cost_complete": not missing,
            "models_missing_price": sorted(missing),
        },
    }
