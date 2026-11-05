"""Scenario 6: the same event delivered twice (sequentially and concurrently) is processed exactly once."""

import asyncio

import pytest
from arq.connections import RedisSettings
from arq.worker import Worker
from sqlalchemy import func, select

from app.core.config import get_settings
from app.db.models import Outbox, RequestLog
from app.main import app
from app.workers.queue import get_job_queue
from app.workers.tasks import process_message, send_notice
from tests.helpers import payload, send, signed

pytestmark = pytest.mark.db


async def _outbox(db_session) -> list[Outbox]:
    return list((await db_session.execute(select(Outbox))).scalars())


async def test_concurrent_duplicate_gives_one_job_and_one_outbox_row(client, fake_queue, db_session) -> None:
    raw, headers = signed(payload(event_id="evt_dup_concurrent"))
    responses = await asyncio.gather(
        *(client.post("/webhooks/mock", content=raw, headers=headers) for _ in range(2))
    )
    assert sorted(r.json()["status"] for r in responses) == ["duplicate", "queued"]
    assert len(fake_queue.messages) == 1

    await fake_queue.run_all()
    await fake_queue.run_all()  # a worker retry must not send a second reply
    rows = await _outbox(db_session)
    assert len(rows) == 1 and rows[0].event_id == "evt_dup_concurrent"

    outcomes = (await db_session.execute(select(RequestLog.outcome).order_by(RequestLog.id))).scalars().all()
    # empty knowledge base in this test -> the single processed copy is handed off to an instructor
    assert sorted(outcomes) == ["duplicate", "handoff"]


async def test_many_concurrent_copies(client, fake_queue) -> None:
    raw, headers = signed(payload(event_id="evt_dup_storm"))
    responses = await asyncio.gather(
        *(client.post("/webhooks/mock", content=raw, headers=headers) for _ in range(8))
    )
    statuses = [r.json()["status"] for r in responses]
    assert statuses.count("queued") == 1 and statuses.count("duplicate") == 7
    assert len(fake_queue.messages) == 1


async def test_sequential_redelivery_is_duplicate(client, fake_queue) -> None:
    body = payload(event_id="evt_dup_later")
    assert (await send(client, body)).json()["status"] == "queued"
    assert (await send(client, body)).json()["status"] == "duplicate"
    assert len(fake_queue.messages) == 1


async def test_end_to_end_with_real_arq_worker(clean_state, db_session) -> None:
    """Webhook -> real arq queue (Redis) -> real worker -> outbox. Duplicate copies included."""
    import httpx

    app.dependency_overrides.pop(get_job_queue, None)
    raw, headers = signed(payload(text="/hoi Webhook có bị người lạ gọi không?", event_id="evt_e2e"))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        responses = await asyncio.gather(
            *(c.post("/webhooks/mock", content=raw, headers=headers) for _ in range(2))
        )
    assert sorted(r.json()["status"] for r in responses) == ["duplicate", "queued"]

    worker = Worker(
        functions=[process_message, send_notice],
        redis_settings=RedisSettings.from_dsn(get_settings().redis_url.get_secret_value()),
        burst=True,
        poll_delay=0.05,
        handle_signals=False,
    )
    await worker.main()
    # Not worker.close(): it sends SIGUSR1, which does not exist on Windows.
    await worker.pool.aclose()

    rows = await _outbox(db_session)
    assert len(rows) == 1
    assert rows[0].kind == "handoff" and "Mã yêu cầu: #H-" in rows[0].text  # no documents indexed here
    count = (await db_session.execute(select(func.count()).select_from(RequestLog))).scalar()
    assert count == 2  # one duplicate + one handoff
