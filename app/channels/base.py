"""Channel abstraction: every chat platform is normalised into IncomingMessage."""

from datetime import datetime
from typing import Protocol

from fastapi import Request
from pydantic import BaseModel


class IncomingMessage(BaseModel):
    """Platform-independent view of one group message."""

    channel: str
    event_id: str
    group_id: str
    user_id: str  # raw platform id: hashed before storage, never logged
    is_from_bot: bool
    text: str
    sent_at: datetime
    msg_id: str | None = None


class WebhookAuthError(Exception):
    """Raised by ChannelAdapter.verify; `reason` is a short safe code (no secrets, no payload)."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class ChannelAdapter(Protocol):
    name: str

    async def verify(self, request: Request, raw_body: bytes) -> None:
        """Raise WebhookAuthError if the request is not authentic."""
        ...

    def parse(self, payload: dict) -> IncomingMessage | None:
        """Return None for events the bot does not handle (non-text, joins, ...)."""
        ...

    async def send_reply(
        self,
        group_id: str,
        text: str,
        reply_to: str | None,
        *,
        event_id: str | None = None,
        kind: str = "answer",
    ) -> bool:
        """Send a message to the group. With event_id set, at most one message is ever sent per event;
        returns False when it was already sent."""
        ...
