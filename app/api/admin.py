"""Admin API (X-Admin-Key): classes. Documents and handoffs live in admin_documents / admin_handoffs."""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_admin
from app.db import repositories as repo
from app.db.models import ClassRoom
from app.db.session import get_session

router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[Depends(require_admin)])


class ToggleRequest(BaseModel):
    enabled: bool


class ClassOut(BaseModel):
    id: str
    name: str
    enabled: bool
    instructor_name: str | None  # instructor_contact stays internal: not exposed


@router.get("/classes")
async def list_classes(session: AsyncSession = Depends(get_session)) -> list[ClassOut]:
    """Real classes only (the shared COMMON scope is not a class and cannot be toggled)."""
    rows = await session.execute(
        select(ClassRoom).where(ClassRoom.is_shared.is_(False)).order_by(ClassRoom.id)
    )
    return [
        ClassOut(id=c.id, name=c.name, enabled=c.enabled, instructor_name=c.instructor_name)
        for c in rows.scalars()
    ]


@router.post("/classes/{class_id}/toggle")
async def toggle_class(
    class_id: str, body: ToggleRequest, session: AsyncSession = Depends(get_session)
) -> dict[str, object]:
    """Turn the bot on/off for one class (the shared COMMON scope cannot be toggled)."""
    if not await repo.set_class_enabled(session, class_id, body.enabled):
        raise HTTPException(404, "class not found")
    return {"class_id": class_id, "enabled": body.enabled}
