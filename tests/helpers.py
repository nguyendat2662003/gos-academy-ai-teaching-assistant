"""Helpers to build and send signed mock-webhook requests in tests."""

import json
import time
import uuid

import httpx

from app.core.security import sign_webhook

SECRET = "test-webhook-secret"
GS_GROUP = "grp_gs_kpi_01"
AUTO_GROUP = "grp_auto_n8n_01"


def payload(
    text: str = "/hoi Lỗi 401 là gì?",
    group_id: str = AUTO_GROUP,
    user_id: str = "user_001",
    event_id: str | None = None,
    is_bot: bool = False,
    event_name: str = "group.message.text",
) -> dict:
    return {
        "event_id": event_id or f"evt_{uuid.uuid4().hex[:10]}",
        "event_name": event_name,
        "timestamp": int(time.time()),
        "group_id": group_id,
        "sender": {"id": user_id, "display_name": "Nguyen Van A", "is_bot": is_bot},
        "message": {"msg_id": f"msg_{uuid.uuid4().hex[:8]}", "text": text},
    }


def signed(body: dict, secret: str = SECRET, timestamp: int | None = None) -> tuple[bytes, dict[str, str]]:
    raw = json.dumps(body, ensure_ascii=False).encode()
    ts = str(timestamp if timestamp is not None else int(time.time()))
    return raw, {
        "X-Timestamp": ts,
        "X-Signature": sign_webhook(secret, ts, raw),
        "Content-Type": "application/json",
    }


async def send(client: httpx.AsyncClient, body: dict, **kwargs: object) -> httpx.Response:
    raw, headers = signed(body, **kwargs)
    return await client.post("/webhooks/mock", content=raw, headers=headers)
