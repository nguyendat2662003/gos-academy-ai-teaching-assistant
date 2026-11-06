"""Admin area (X-Admin-Key): who am I, classes, bot on/off. Documents and handoffs live in admin_documents /
admin_handoffs. Roles: app/api/deps.py (D-83)."""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import Principal, require_admin, require_staff
from app.db import repositories as repo
from app.db.models import ClassRoom
from app.db.session import get_session

router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[Depends(require_staff)])


class ToggleRequest(BaseModel):
    enabled: bool


class ClassOut(BaseModel):
    id: str
    name: str
    enabled: bool
    instructor_name: str | None  # instructor_contact stays internal: not exposed


class MeOut(BaseModel):
    role: str
    name: str
    class_id: str | None  # null = every class


@router.get("/me")
async def me(principal: Principal = Depends(require_staff)) -> MeOut:
    """Which role the key in X-Admin-Key opens (the admin page adapts to it)."""
    return MeOut(role=principal.role, name=principal.name, class_id=principal.class_id)


@router.get("/classes")
async def list_classes(
    session: AsyncSession = Depends(get_session), principal: Principal = Depends(require_staff)
) -> list[ClassOut]:
    """Real classes only (the shared COMMON scope is not a class and cannot be toggled); an instructor
    sees only their own class."""
    stmt = select(ClassRoom).where(ClassRoom.is_shared.is_(False)).order_by(ClassRoom.id)
    if not principal.is_admin:
        stmt = stmt.where(ClassRoom.id == principal.class_id)
    rows = await session.execute(stmt)
    return [
        ClassOut(id=c.id, name=c.name, enabled=c.enabled, instructor_name=c.instructor_name)
        for c in rows.scalars()
    ]


@router.post("/classes/{class_id}/toggle", dependencies=[Depends(require_admin)])
async def toggle_class(
    class_id: str, body: ToggleRequest, session: AsyncSession = Depends(get_session)
) -> dict[str, object]:
    """Turn the bot on/off for one class (admin only; the shared COMMON scope cannot be toggled)."""
    if not await repo.set_class_enabled(session, class_id, body.enabled):
        raise HTTPException(404, "class not found")
    return {"class_id": class_id, "enabled": body.enabled}
