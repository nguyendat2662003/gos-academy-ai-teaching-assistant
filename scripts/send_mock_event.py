"""Send HMAC-signed events to the mock webhook (manual testing / demo).

WEBHOOK_SECRET is read from the environment (or .env) and never printed.

Examples:
  python scripts/send_mock_event.py --group grp_auto_n8n_01 --user hv01 --text "/hoi Lỗi 401 là gì?"
  python scripts/send_mock_event.py --group grp_gs_kpi_01 --user hv02 --text "/hoi ..." --duplicate
  python scripts/send_mock_event.py --replay data/samples/_meta/Tin_nhan_mo_phong_TTS.json

--replay: the sample file carries a client-side class_id. It is translated to that class's mock group_id
using config/classes.yaml, because the server only ever trusts group_id (DECISIONS D-06). Each message is
re-signed with the current timestamp and prefixed with the trigger if it lacks one.
"""

import argparse
import asyncio
import json
import sys
import time
import uuid
from pathlib import Path

import httpx
from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.classes import ClassRegistry, load_registry  # noqa: E402
from app.core.security import sign_webhook  # noqa: E402

DEFAULT_TRIGGER = "/hoi"


class _ScriptEnv(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")
    webhook_secret: SecretStr


def build_payload(
    group_id: str, user_id: str, text: str, event_id: str | None = None, is_bot: bool = False
) -> dict:
    now = int(time.time())
    return {
        "event_id": event_id or f"evt_{uuid.uuid4().hex[:12]}",
        "event_name": "group.message.text",
        "timestamp": now,
        "group_id": group_id,
        "sender": {"id": user_id, "is_bot": is_bot},
        "message": {"msg_id": f"msg_{uuid.uuid4().hex[:12]}", "text": text},
    }


def signed_request(secret: str, payload: dict) -> tuple[bytes, dict[str, str]]:
    body = json.dumps(payload, ensure_ascii=False).encode()
    timestamp = str(int(time.time()))
    headers = {
        "Content-Type": "application/json",
        "X-Timestamp": timestamp,
        "X-Signature": sign_webhook(secret, timestamp, body),
    }
    return body, headers


def replay_payloads(path: Path, registry: ClassRegistry, prefix: str = "") -> list[dict]:
    """Convert the sample message file into mock payloads (class_id -> group_id, add trigger)."""
    group_of = {
        c.id: next(g.external_group_id for g in c.groups if g.channel == "mock")
        for c in registry.classes
        if any(g.channel == "mock" for g in c.groups)
    }
    data = json.loads(path.read_text(encoding="utf-8"))
    payloads = []
    for ev in data["events"]:
        text = ev["text"]
        if not text.lower().startswith(DEFAULT_TRIGGER):
            text = f"{DEFAULT_TRIGGER} {text}"
        payloads.append(
            build_payload(
                group_of[ev["class_id"]], ev["sender_id"], text, event_id=f"{prefix}{ev['event_id']}"
            )
        )
    return payloads


async def _post(client: httpx.AsyncClient, url: str, body: bytes, headers: dict[str, str]) -> str:
    resp = await client.post(url, content=body, headers=headers)
    return f"{resp.status_code} {resp.text}"


async def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--url", default="http://127.0.0.1:8000/webhooks/mock")
    parser.add_argument("--group")
    parser.add_argument("--user", default="user_demo")
    parser.add_argument("--text")
    parser.add_argument("--event-id")
    parser.add_argument("--bot", action="store_true", help="mark the sender as a bot")
    parser.add_argument("--duplicate", action="store_true", help="send the same event twice concurrently")
    parser.add_argument("--replay", type=Path, help="sample JSON file to replay")
    parser.add_argument("--event-prefix", default="", help="prefix for replayed event ids (to re-run)")
    args = parser.parse_args()

    secret = _ScriptEnv().webhook_secret.get_secret_value()  # type: ignore[call-arg]

    if args.replay:
        payloads = replay_payloads(args.replay, load_registry("config/classes.yaml"), args.event_prefix)
    elif args.group and args.text:
        payloads = [build_payload(args.group, args.user, args.text, args.event_id, args.bot)]
    else:
        parser.error("use --group and --text, or --replay FILE")

    async with httpx.AsyncClient(timeout=10) as client:
        for payload in payloads:
            body, headers = signed_request(secret, payload)
            copies = 2 if args.duplicate else 1
            results = await asyncio.gather(*(_post(client, args.url, body, headers) for _ in range(copies)))
            for r in results:
                print(f"{payload['event_id']}: {r}")


if __name__ == "__main__":
    asyncio.run(main())
