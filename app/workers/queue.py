"""Job contract between the webhook (producer) and the arq worker (consumer)."""

from typing import Protocol

from arq import ArqRedis, create_pool
from arq.connections import RedisSettings
from pydantic import BaseModel

from app.core.config import get_settings

PROCESS_MESSAGE = "process_message"
SEND_NOTICE = "send_notice"


class MessageJob(BaseModel):
    """Everything the worker needs. Contains the user HASH, never the raw platform user id."""

    request_id: str
    channel: str
    event_id: str
    group_id: str
    class_id: str
    user_hash: str
    question: str
    msg_id: str | None = None
    received_at_ms: int


class NoticeJob(BaseModel):
    """A fixed bot message (e.g. rate-limit notice) to send to a group, at most once per event."""

    channel: str
    event_id: str
    group_id: str
    text: str
    reply_to: str | None = None
    kind: str = "notice"


class JobQueue(Protocol):
    async def enqueue_message(self, job: MessageJob) -> None: ...

    async def enqueue_notice(self, job: NoticeJob) -> None: ...


class ArqJobQueue:
    def __init__(self, pool: ArqRedis) -> None:
        self._pool = pool

    async def enqueue_message(self, job: MessageJob) -> None:
        # _job_id = event key: arq itself also refuses a second job with the same id (defence in depth).
        await self._pool.enqueue_job(
            PROCESS_MESSAGE, job.model_dump(), _job_id=f"msg:{job.channel}:{job.event_id}"
        )

    async def enqueue_notice(self, job: NoticeJob) -> None:
        await self._pool.enqueue_job(
            SEND_NOTICE, job.model_dump(), _job_id=f"notice:{job.channel}:{job.event_id}"
        )


_queue: ArqJobQueue | None = None


async def get_job_queue() -> JobQueue:
    """FastAPI dependency; the arq pool is created lazily on first use."""
    global _queue
    if _queue is None:
        pool = await create_pool(RedisSettings.from_dsn(get_settings().redis_url.get_secret_value()))
        _queue = ArqJobQueue(pool)
    return _queue
