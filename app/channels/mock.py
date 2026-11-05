"""Mock webhook adapter: HMAC-signed JSON in, messages "sent" by writing to the outbox table."""

import time
from datetime import UTC, datetime

from fastapi import Request
from pydantic import BaseModel, ValidationError
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.channels.base import IncomingMessage, WebhookAuthError
from app.core.security import constant_time_equals, sign_webhook
from app.db.models import Outbox

MAX_CLOCK_SKEW_SECONDS = 300
TEXT_EVENT = "group.message.text"


class _Sender(BaseModel):
    id: str
    display_name: str | None = None  # accepted but never stored
    is_bot: bool = False


class _Message(BaseModel):
    msg_id: str | None = None
    text: str


class MockPayload(BaseModel):
    event_id: str
    event_name: str
    timestamp: int
    group_id: str
    sender: _Sender
    message: _Message | None = None


class MockWebhookAdapter:
    name = "mock"

    def __init__(self, secret: str, sessionmaker: async_sessionmaker[AsyncSession]) -> None:
        self._secret = secret
        self._sessionmaker = sessionmaker

    async def verify(self, request: Request, raw_body: bytes) -> None:
        timestamp = request.headers.get("X-Timestamp")
        signature = request.headers.get("X-Signature")
        if not timestamp or not signature:
            raise WebhookAuthError("missing_headers")
        try:
            ts = int(timestamp)
        except ValueError as exc:
            raise WebhookAuthError("bad_timestamp") from exc
        if abs(time.time() - ts) > MAX_CLOCK_SKEW_SECONDS:
            raise WebhookAuthError("stale_timestamp")
        if not constant_time_equals(signature, sign_webhook(self._secret, timestamp, raw_body)):
            raise WebhookAuthError("bad_signature")

    def parse(self, payload: dict) -> IncomingMessage | None:
        try:
            data = MockPayload.model_validate(payload)
        except ValidationError:
            return None
        if data.event_name != TEXT_EVENT or data.message is None:
            return None
        return IncomingMessage(
            channel=self.name,
            event_id=data.event_id,
            group_id=data.group_id,
            user_id=data.sender.id,
            is_from_bot=data.sender.is_bot,
            text=data.message.text,
            sent_at=datetime.fromtimestamp(data.timestamp, UTC),
            msg_id=data.message.msg_id,
        )

    async def send_reply(
        self,
        group_id: str,
        text: str,
        reply_to: str | None,
        *,
        event_id: str | None = None,
        kind: str = "answer",
    ) -> bool:
        stmt = (
            insert(Outbox)
            .values(
                channel=self.name,
                external_group_id=group_id,
                event_id=event_id,
                reply_to=reply_to,
                kind=kind,
                text=text,
            )
            .on_conflict_do_nothing()
            .returning(Outbox.id)
        )
        async with self._sessionmaker() as session:
            inserted = (await session.execute(stmt)).scalar_one_or_none()
            await session.commit()
        return inserted is not None
