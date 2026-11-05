"""Admin API (X-Admin-Key). More endpoints are added in Phase 5."""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_admin
from app.db import repositories as repo
from app.db.session import get_session

router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[Depends(require_admin)])


class ToggleRequest(BaseModel):
    enabled: bool


@router.post("/classes/{class_id}/toggle")
async def toggle_class(
    class_id: str, body: ToggleRequest, session: AsyncSession = Depends(get_session)
) -> dict[str, object]:
    """Turn the bot on/off for one class (the shared COMMON scope cannot be toggled)."""
    if not await repo.set_class_enabled(session, class_id, body.enabled):
        raise HTTPException(404, "class not found")
    return {"class_id": class_id, "enabled": body.enabled}
