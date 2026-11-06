"""Test configuration.

- All secrets are replaced by obviously fake values BEFORE the app is imported.
- LLM/embedding providers are forced to `fake` so tests run offline.
- DB tests use a separate database (TEST_DATABASE_URL, default gos_test) that is dropped and
  re-migrated once per test session. Start it with: docker compose up -d postgres redis
"""

import asyncio
import os
import tempfile
from urllib.parse import urlsplit, urlunsplit

import pytest
from pydantic_settings import BaseSettings, SettingsConfigDict


class _TestEnv(BaseSettings):
    """Reads only the test connection strings (from env or .env); nothing else from .env is used."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")
    test_database_url: str = "postgresql+asyncpg://gos:change-me@127.0.0.1:5433/gos_test"
    test_redis_url: str = "redis://127.0.0.1:6380/15"


_test_env = _TestEnv()


def _ipv4(url: str) -> str:
    # On Windows "localhost" may resolve to ::1 first while docker publishes on 127.0.0.1 only.
    return url.replace("@localhost:", "@127.0.0.1:").replace("//localhost:", "//127.0.0.1:")


FAKE_ENV = {
    "APP_ENV": "test",
    "LOG_LEVEL": "WARNING",
    "DATABASE_URL": _ipv4(_test_env.test_database_url),
    "REDIS_URL": _ipv4(_test_env.test_redis_url),
    "WEBHOOK_SECRET": "test-webhook-secret",
    "ADMIN_API_KEY": "test-admin-key",
    "INSTRUCTOR_API_KEYS": "GS-KPI-01=test-gs-instructor-key,AUTO-N8N-01=test-auto-instructor-key",
    "ASK_API_KEY": "test-ask-key",
    "USER_HASH_SALT": "test-salt",
    "LLM_PROVIDER": "fake",
    "LLM_MODEL": "fake-llm",
    "EMBEDDING_PROVIDER": "fake",
    "EMBEDDING_MODEL": "fake-embedding",
    "EMBEDDING_DIM": "768",
    "GEMINI_API_KEY": "",
    "OPENAI_API_KEY": "",
    # Uploaded originals go to a throw-away folder, never into the repo.
    "STORAGE_DIR": tempfile.mkdtemp(prefix="gos_uploads_"),
}
os.environ.update(FAKE_ENV)


def _admin_dsn(url: str) -> tuple[str, str]:
    """Return (asyncpg DSN of the maintenance db, test db name)."""
    parts = urlsplit(url.replace("+asyncpg", ""))
    db_name = parts.path.lstrip("/")
    return urlunsplit(parts._replace(path="/postgres")), db_name


async def _recreate_database(url: str) -> None:
    import asyncpg

    dsn, db_name = _admin_dsn(url)
    if not db_name.endswith("_test"):
        raise RuntimeError("refusing to drop a database whose name does not end with _test")
    conn = await asyncpg.connect(dsn)
    try:
        await conn.execute(f'DROP DATABASE IF EXISTS "{db_name}" WITH (FORCE)')
        await conn.execute(f'CREATE DATABASE "{db_name}"')
    finally:
        await conn.close()


@pytest.fixture(scope="session")
def migrated_db() -> str:
    """Create a fresh test database and apply all Alembic migrations (sync fixture, own loop)."""
    from alembic import command
    from alembic.config import Config

    try:
        asyncio.run(_recreate_database(FAKE_ENV["DATABASE_URL"]))
    except OSError as exc:  # connection refused etc.
        pytest.fail(f"PostgreSQL test DB not reachable ({exc}). Run: docker compose up -d postgres redis")
    command.upgrade(Config("alembic.ini"), "head")
    return FAKE_ENV["DATABASE_URL"]


@pytest.fixture
async def db_session(migrated_db: str):
    """A session on the migrated test database."""
    from app.db.session import get_sessionmaker

    async with get_sessionmaker()() as session:
        yield session


_TABLES = (
    "outbox, processed_events, request_logs, security_events, conversation_turns, chunks, "
    "faq_entries, handoff_tickets, documents, channel_groups, classes"
)


@pytest.fixture
async def clean_state(migrated_db: str) -> None:
    """Empty every table, re-seed classes.yaml and flush the test Redis DB."""
    from sqlalchemy import text

    from app.core.classes import get_registry
    from app.core.redis import get_redis
    from app.db.seed import sync_classes
    from app.db.session import get_sessionmaker

    async with get_sessionmaker()() as session:
        await session.execute(text(f"TRUNCATE {_TABLES} RESTART IDENTITY CASCADE"))
        await session.commit()
        await sync_classes(session, get_registry())
    await get_redis().flushdb()


class FakeQueue:
    """Records jobs instead of sending them to arq; `run_all` executes them like the worker would."""

    def __init__(self) -> None:
        self.messages: list = []
        self.notices: list = []
        self.fail_next = False

    async def enqueue_message(self, job) -> None:  # type: ignore[no-untyped-def]
        if self.fail_next:
            self.fail_next = False
            raise ConnectionError("queue down")
        self.messages.append(job)

    async def enqueue_notice(self, job) -> None:  # type: ignore[no-untyped-def]
        self.notices.append(job)

    async def run_all(self) -> None:
        from app.workers.tasks import process_message, send_notice

        for job in self.messages:
            await process_message({}, job.model_dump())
        for job in self.notices:
            await send_notice({}, job.model_dump())


@pytest.fixture
def fake_queue() -> FakeQueue:
    return FakeQueue()


@pytest.fixture
async def client(clean_state: None, fake_queue: FakeQueue):
    """HTTP client against the ASGI app with the job queue replaced by FakeQueue."""
    import httpx

    from app.main import app
    from app.workers.queue import get_job_queue

    app.dependency_overrides[get_job_queue] = lambda: fake_queue
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()


SAMPLE_FILES = {
    "GS-KPI-01": "data/samples/GS-KPI-01/01_Giao_trinh_Google_Sheets_KPI_Dashboard.docx",
    "AUTO-N8N-01": "data/samples/AUTO-N8N-01/02_Giao_trinh_AI_Automation_n8n.docx",
    "COMMON": "data/samples/COMMON/03_FAQ_Quy_dinh_lop_hoc_GIA_LAP.docx",
}


async def ingest_file(session, path: str, scope: str):  # type: ignore[no-untyped-def]
    from pathlib import Path

    from app.core.classes import get_registry
    from app.ingestion import indexer
    from app.providers.registry import get_embedding_provider

    data = Path(path).read_bytes()
    return await indexer.index_file(
        session,
        data=data,
        filename=Path(path).name,
        origin_scope=scope,
        embedder=get_embedding_provider(),
        registry=get_registry(),
    )


@pytest.fixture
async def kb(clean_state, db_session) -> None:
    """The real sample material indexed with the fake embedding."""
    for scope, path in SAMPLE_FILES.items():
        await ingest_file(db_session, path, scope)


@pytest.fixture
def llm(monkeypatch):  # type: ignore[no-untyped-def]
    """A fresh FakeLLM wired into the worker and /api/ask; inspect `.calls` to see every prompt sent.

    Also: threshold 0 (the fake embedding's cosine scores are not calibrated; the threshold has its own test)
    and no retry delay."""
    from app.api import ask
    from app.core.config import get_settings
    from app.providers.fake_llm import FakeLLM
    from app.workers import tasks

    fake = FakeLLM()
    monkeypatch.setattr(tasks, "get_llm_provider", lambda: fake)
    monkeypatch.setattr(ask, "get_llm_provider", lambda: fake)
    monkeypatch.setattr(get_settings(), "retrieval_min_score", 0.0)
    monkeypatch.setattr(get_settings(), "llm_retry_base_delay", 0.0)
    return fake
