"""Liveness endpoint. Reports dependency status only — never configuration."""

import logging

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.core.redis import get_redis
from app.db.session import get_engine

router = APIRouter()
logger = logging.getLogger(__name__)


async def check_db() -> bool:
    try:
        async with get_engine().connect() as conn:
            await conn.execute(text("SELECT 1"))
        return True
    except Exception:
        logger.warning("health: database unreachable", exc_info=True)
        return False


async def check_redis() -> bool:
    try:
        return bool(await get_redis().ping())
    except Exception:
        logger.warning("health: redis unreachable", exc_info=True)
        return False


@router.get("/health")
async def health() -> JSONResponse:
    checks = {"db": await check_db(), "redis": await check_redis()}
    ok = all(checks.values())
    body = {
        "status": "ok" if ok else "degraded",
        "checks": {name: "ok" if passed else "fail" for name, passed in checks.items()},
    }
    return JSONResponse(body, status_code=200 if ok else 503)
