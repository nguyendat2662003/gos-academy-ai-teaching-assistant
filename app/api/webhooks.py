"""Inbound webhooks. Mock channel is fully functional; Zalo is a documented stub (501)."""

import json
import logging

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.channels.base import WebhookAuthError
from app.channels.ingress import handle_incoming
from app.channels.registry import get_mock_adapter
from app.core.config import get_settings
from app.core.logging import request_id_var
from app.core.redis import get_redis
from app.db import repositories as repo
from app.db.models import Outcome, SecurityEventType
from app.db.session import get_session
from app.workers.queue import JobQueue, get_job_queue

router = APIRouter(prefix="/webhooks", tags=["webhooks"])
logger = logging.getLogger(__name__)


def _redis() -> Redis:
    return get_redis()


@router.post("/mock")
async def mock_webhook(
    request: Request,
    session: AsyncSession = Depends(get_session),
    redis: Redis = Depends(_redis),
    queue: JobQueue = Depends(get_job_queue),
) -> JSONResponse:
    adapter = get_mock_adapter()
    request_id = request_id_var.get() or ""
    raw_body = await request.body()

    try:
        await adapter.verify(request, raw_body)
    except WebhookAuthError as exc:
        # Only the reason code is stored — never the payload or the headers.
        repo.add_security_event(
            session,
            SecurityEventType.INVALID_SIGNATURE,
            request_id=request_id,
            detail=f"channel=mock;{exc.reason}",
        )
        await session.commit()
        logger.warning("webhook rejected", extra={"fields": {"reason": exc.reason}})
        return JSONResponse({"status": "unauthorized"}, status_code=401)

    try:
        payload = json.loads(raw_body)
    except ValueError:
        return JSONResponse({"status": "bad_request"}, status_code=400)
    msg = adapter.parse(payload) if isinstance(payload, dict) else None
    if msg is None:
        return JSONResponse({"status": Outcome.IGNORED, "reason": "unsupported_event"})

    result = await handle_incoming(
        msg, session=session, redis=redis, queue=queue, settings=get_settings(), request_id=request_id
    )
    body: dict[str, str] = {"status": result.status, "request_id": request_id}
    if result.reason:
        body["reason"] = result.reason
    return JSONResponse(body)


@router.post("/zalo")
async def zalo_webhook() -> JSONResponse:
    """Not available until GOS Academy's OA is granted GMF access (see app/channels/zalo.py)."""
    return JSONResponse(
        {"status": "not_implemented", "detail": "Zalo OA/GMF integration is not enabled in this MVP"},
        status_code=501,
    )
