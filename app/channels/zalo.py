"""Skeleton adapter for the official Zalo integration (Official Account + Group Message Framework).

NOT IMPLEMENTED ON PURPOSE. Everything below must be re-verified against the official documentation at
https://developers.zalo.me before implementation — no API detail is assumed here.

Prerequisites (business side):
- A verified Zalo Official Account (OA) owned by GOS Academy.
- GMF (Group Message Framework) access granted to that OA by Zalo, and the OA added to each class group.
- An access token for the OA with the permissions/scopes to read group message events and to send
  messages to groups; a secure process to refresh and store it (secret manager / env, never in code).

Technical side (to confirm on developers.zalo.me):
- How Zalo authenticates webhook calls (signature header / algorithm / timestamp) → implement `verify`.
- The webhook event schema for group text messages (event name, group id, sender id, message id,
  whether the sender is the OA itself) → map it in `parse` to IncomingMessage.
- The endpoint, payload, rate limits and error codes for sending a message to a group → `send_reply`.
- Platform policies on bots in groups (allowed triggers, message frequency, content rules).

Personal accounts and unofficial/reverse-engineered libraries must never be used (CLAUDE.md §1.4).
"""

from fastapi import Request

from app.channels.base import IncomingMessage

_TODO = "Zalo OA/GMF integration requires granted permissions; verify details on developers.zalo.me"


class ZaloGMFAdapter:
    name = "zalo"

    async def verify(self, request: Request, raw_body: bytes) -> None:
        """Validate Zalo's webhook signature using the mechanism documented by Zalo (to be verified)."""
        raise NotImplementedError(_TODO)

    def parse(self, payload: dict) -> IncomingMessage | None:
        """Map a Zalo group-message event to IncomingMessage; return None for other event types."""
        raise NotImplementedError(_TODO)

    async def send_reply(
        self,
        group_id: str,
        text: str,
        reply_to: str | None,
        *,
        event_id: str | None = None,
        kind: str = "answer",
    ) -> bool:
        """Send a text message to the group via the OA's GMF send endpoint (to be verified)."""
        raise NotImplementedError(_TODO)
