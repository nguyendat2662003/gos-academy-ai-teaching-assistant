"""Shared FastAPI dependencies: who is calling the admin area, and what they may see (DECISIONS D-83).

Roles
- admin:      ADMIN_API_KEY. Every class, plus system-wide actions (bot on/off, security events, demo,
              documents shared by several classes).
- instructor: one key per class in INSTRUCTOR_API_KEYS. Only that class's tickets, documents and stats;
              another class's ticket/document answers 404 (its existence is not revealed).
- students never get a key: they only talk to the bot in their group, and their class comes from group_id.

Both kinds of key travel in the same header (X-Admin-Key = "key of the admin area"); the server decides the
role from which key matched, never from anything the client claims.
"""

from dataclasses import dataclass
from functools import lru_cache
from typing import Literal

from fastapi import Depends, Header, HTTPException, status

from app.core.classes import get_registry
from app.core.config import get_settings
from app.core.security import constant_time_equals

Role = Literal["admin", "instructor"]


@dataclass(frozen=True)
class Principal:
    role: Role
    name: str
    class_id: str | None = None  # None = every class (admin)

    @property
    def is_admin(self) -> bool:
        return self.role == "admin"

    def owns(self, class_id: str | None) -> bool:
        """May act on data of `class_id` (admin: any)."""
        return self.is_admin or (class_id is not None and class_id == self.class_id)

    def class_filter(self, requested: str | None) -> str | None:
        """The class a list/stats query is limited to: admin keeps the request, an instructor is pinned to
        their own class and may not ask for another one (403: class ids are not secret)."""
        if self.is_admin:
            return requested or None
        if requested and requested != self.class_id:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "instructor key: own class only")
        return self.class_id


@lru_cache
def staff_keys() -> tuple[tuple[str, Principal], ...]:
    """(key, principal) for the admin key and every instructor key, validated against classes.yaml.

    Called at startup (fail fast on a typo) and on each request (cached)."""
    settings = get_settings()
    registry = get_registry()
    admin_key = settings.admin_api_key.get_secret_value()
    names = {c.id: c.instructor_name for c in registry.classes}
    keys = [(admin_key, Principal("admin", "Quản trị"))]
    for class_id, secret in settings.instructor_api_keys.items():
        if class_id not in names:  # also rejects the shared COMMON scope: it has no instructor
            raise ValueError(f"INSTRUCTOR_API_KEYS: unknown class {class_id}")
        key = secret.get_secret_value()
        if key == admin_key:
            raise ValueError(f"INSTRUCTOR_API_KEYS: key of {class_id} equals ADMIN_API_KEY")
        keys.append((key, Principal("instructor", names[class_id], class_id)))
    return tuple(keys)


async def require_staff(x_admin_key: str | None = Header(default=None)) -> Principal:
    """Admin area: header X-Admin-Key holding the admin key or a class instructor key (constant time)."""
    found: Principal | None = None
    for key, principal in staff_keys():  # no early exit: same work whichever key matches
        if constant_time_equals(x_admin_key, key) and found is None:
            found = principal
    if found is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid admin key")
    return found


async def require_admin(principal: Principal = Depends(require_staff)) -> Principal:
    """System-wide actions: the admin key only (an instructor key gets 403)."""
    if not principal.is_admin:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "admin key required")
    return principal
