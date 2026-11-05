"""Webhook authentication: bad signature / stale timestamp / missing headers -> 401 + security_event."""

import time

import pytest
from sqlalchemy import func, select

from app.db.models import ProcessedEvent, SecurityEvent
from tests.helpers import payload, send, signed

pytestmark = pytest.mark.db


async def _security_events(db_session) -> list[SecurityEvent]:
    return list((await db_session.execute(select(SecurityEvent))).scalars())


async def test_wrong_secret_rejected(client, db_session, fake_queue) -> None:
    resp = await send(client, payload(), secret="attacker-guess")
    assert resp.status_code == 401
    events = await _security_events(db_session)
    assert [(e.type, e.detail_redacted) for e in events] == [
        ("invalid_signature", "channel=mock;bad_signature")
    ]
    assert fake_queue.messages == []
    assert (await db_session.execute(select(func.count()).select_from(ProcessedEvent))).scalar() == 0


async def test_timestamp_older_than_300s_rejected(client, db_session) -> None:
    resp = await send(client, payload(), timestamp=int(time.time()) - 301)
    assert resp.status_code == 401
    assert (await _security_events(db_session))[0].detail_redacted.endswith("stale_timestamp")


async def test_tampered_body_rejected(client, db_session) -> None:
    raw, headers = signed(payload(text="/hoi câu hỏi gốc"))
    tampered = raw.replace("câu hỏi gốc".encode(), "câu hỏi khác".encode())
    resp = await client.post("/webhooks/mock", content=tampered, headers=headers)
    assert resp.status_code == 401


async def test_missing_headers_rejected(client, db_session) -> None:
    resp = await client.post("/webhooks/mock", json=payload())
    assert resp.status_code == 401
    assert (await _security_events(db_session))[0].detail_redacted.endswith("missing_headers")


async def test_security_event_never_stores_payload(client, db_session) -> None:
    await send(client, payload(text="/hoi sk-SECRETSECRETSECRET user_001"), secret="wrong")
    stored = " ".join(str(e.detail_redacted) for e in await _security_events(db_session))
    assert "SECRET" not in stored and "user_001" not in stored and "Nguyen" not in stored


async def test_zalo_webhook_is_a_stub(client) -> None:
    resp = await client.post("/webhooks/zalo", json={})
    assert resp.status_code == 501
