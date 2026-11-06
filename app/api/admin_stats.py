"""Monitoring API (X-Admin-Key): usage/cost statistics and security events.

Roles (D-83): an instructor key gets the stats of its own class only; security events are admin only (they
include events with no class, e.g. invalid webhook signatures).
"""

from datetime import date, datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import Principal, require_admin, require_staff
from app.core.config import get_settings
from app.core.pricing import get_pricing
from app.db.models import SecurityEvent, SecurityEventType
from app.db.session import get_session
from app.db.stats import StatsFilter, compute_stats

router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[Depends(require_staff)])


def stats_filter(
    class_id: str | None = None,
    date_from: date | None = Query(
        default=None, alias="from", description="YYYY-MM-DD, Vietnam time, inclusive"
    ),
    date_to: date | None = Query(default=None, alias="to", description="YYYY-MM-DD, inclusive"),
    principal: Principal = Depends(require_staff),
) -> StatsFilter:
    if date_from and date_to and date_from > date_to:
        raise HTTPException(422, "'from' must not be after 'to'")
    return StatsFilter(class_id=principal.class_filter(class_id), date_from=date_from, date_to=date_to)


@router.get("/stats")
async def stats(
    f: StatsFilter = Depends(stats_filter), session: AsyncSession = Depends(get_session)
) -> dict[str, object]:
    """Questions, outcomes, tickets by reason, latency avg/p95, tokens and estimated cost: total, per class,
    per day; plus ingest embedding cost and security events."""
    return await compute_stats(
        session, f, pricing=get_pricing(), fallback_embedding_model=get_settings().embedding_model
    )


class SecurityEventOut(BaseModel):
    id: int
    created_at: datetime
    class_id: str | None
    type: str
    detail: str | None  # already redacted when written
    user_ref: str | None  # first 12 hex chars of the HMAC user hash: enough to correlate, nothing more
    request_id: str | None


@router.get("/security-events", dependencies=[Depends(require_admin)])
async def security_events(
    f: StatsFilter = Depends(stats_filter),
    type: SecurityEventType | None = None,  # noqa: A002 - public query parameter name
    limit: int = Query(default=100, ge=1, le=1000),
    session: AsyncSession = Depends(get_session),
) -> list[SecurityEventOut]:
    stmt = (
        select(SecurityEvent)
        .where(*f.where(SecurityEvent.created_at, SecurityEvent.class_id))
        .order_by(SecurityEvent.id.desc())
        .limit(limit)
    )
    if type:
        stmt = stmt.where(SecurityEvent.type == type)
    return [
        SecurityEventOut(
            id=e.id,
            created_at=e.created_at,
            class_id=e.class_id,
            type=e.type,
            detail=e.detail_redacted,
            user_ref=e.user_hash[:12] if e.user_hash else None,
            request_id=e.request_id,
        )
        for e in (await session.execute(stmt)).scalars()
    ]
