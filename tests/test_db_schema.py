"""The migration must produce exactly the schema declared by the ORM models, plus seeding works."""

import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import select, text

from app.core.classes import get_registry
from app.db.models import Base, ChannelGroup, ClassRoom
from app.db.seed import sync_classes
from app.db.session import get_engine

pytestmark = pytest.mark.db


async def test_migration_matches_models(migrated_db: str) -> None:
    def _diff(sync_conn):  # type: ignore[no-untyped-def]
        return compare_metadata(MigrationContext.configure(sync_conn), Base.metadata)

    async with get_engine().connect() as conn:
        diff = await conn.run_sync(_diff)
    assert diff == [], diff


async def test_pgvector_extension_installed(db_session) -> None:
    ext = (await db_session.execute(text("SELECT extname FROM pg_extension WHERE extname='vector'"))).scalar()
    assert ext == "vector"


async def test_seed_classes_is_idempotent(db_session) -> None:
    registry = get_registry()
    await sync_classes(db_session, registry)
    await sync_classes(db_session, registry)

    classes = {c.id: c for c in (await db_session.execute(select(ClassRoom))).scalars()}
    assert set(classes) == {"COMMON", "GS-KPI-01", "AUTO-N8N-01"}
    assert classes["COMMON"].is_shared and not classes["GS-KPI-01"].is_shared

    groups = (await db_session.execute(select(ChannelGroup))).scalars().all()
    assert {(g.external_group_id, g.class_id) for g in groups} == {
        ("grp_gs_kpi_01", "GS-KPI-01"),
        ("grp_auto_n8n_01", "AUTO-N8N-01"),
    }
