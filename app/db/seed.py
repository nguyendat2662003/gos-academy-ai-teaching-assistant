"""Sync config/classes.yaml into the classes / channel_groups tables (idempotent).

Run: python -m app.db.seed
"""

import asyncio

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.classes import ClassRegistry, get_registry
from app.db.models import ChannelGroup, ClassRoom
from app.db.session import get_sessionmaker


async def sync_classes(session: AsyncSession, registry: ClassRegistry) -> None:
    """Upsert classes and replace group mappings. The YAML file is the source of truth for mappings;
    the `enabled` flag is only set on first insert so admin toggles survive restarts."""
    shared = registry.shared_scope
    rows = [(shared.id, shared.name, True, None, None, False)] + [
        (c.id, c.name, False, c.instructor_name, c.instructor_contact, c.enabled) for c in registry.classes
    ]
    for class_id, name, is_shared, instructor, contact, enabled in rows:
        existing = await session.get(ClassRoom, class_id)
        if existing is None:
            session.add(
                ClassRoom(
                    id=class_id,
                    name=name,
                    is_shared=is_shared,
                    instructor_name=instructor,
                    instructor_contact=contact,
                    enabled=enabled,
                )
            )
        else:
            existing.name = name
            existing.is_shared = is_shared
            existing.instructor_name = instructor
            existing.instructor_contact = contact
    await session.flush()

    await session.execute(delete(ChannelGroup))
    for c in registry.classes:
        for g in c.groups:
            session.add(ChannelGroup(channel=g.channel, external_group_id=g.external_group_id, class_id=c.id))
    await session.commit()


async def _main() -> None:
    async with get_sessionmaker()() as session:
        await sync_classes(session, get_registry())
        count = len((await session.execute(select(ClassRoom.id))).all())
    print(f"classes synced: {count} rows (incl. shared scope)")


if __name__ == "__main__":
    asyncio.run(_main())
