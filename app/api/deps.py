"""Shared FastAPI dependencies."""

from fastapi import Header, HTTPException, status

from app.core.config import get_settings
from app.core.security import constant_time_equals


async def require_admin(x_admin_key: str | None = Header(default=None)) -> None:
    """Admin endpoints: header X-Admin-Key, compared in constant time."""
    if not constant_time_equals(x_admin_key, get_settings().admin_api_key.get_secret_value()):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid admin key")
