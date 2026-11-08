"""HTML pages (Jinja2): the minimal admin page and the dev-only /demo chat.

Pages carry no data and no secret: their scripts call the JSON APIs with the admin key the operator types
in (kept in sessionStorage). Every response gets a strict CSP with a per-request nonce, so only our inline
script/style run, and the scripts insert student text with textContent only (no HTML injection).
"""

import secrets
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from app.core.classes import get_registry
from app.core.config import get_settings

TEMPLATES = Jinja2Templates(directory=str(Path(__file__).resolve().parent.parent / "templates"))

router = APIRouter(tags=["pages"])


def csp(nonce: str) -> str:
    return (
        "default-src 'none'; "
        f"script-src 'nonce-{nonce}'; style-src 'nonce-{nonce}'; "
        "connect-src 'self'; img-src 'self' data:; "
        "base-uri 'none'; form-action 'none'; frame-ancestors 'none'"
    )


def render(request: Request, name: str, context: dict[str, object]) -> HTMLResponse:
    nonce = secrets.token_urlsafe(16)
    response = TEMPLATES.TemplateResponse(request, name, {**context, "nonce": nonce})
    response.headers["Content-Security-Policy"] = csp(nonce)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Cache-Control"] = "no-store"
    return response


@router.get("/admin/ui", response_class=HTMLResponse, include_in_schema=False)
async def admin_page(request: Request) -> HTMLResponse:
    """Tickets, FAQ and course material for instructors. Static shell: data is fetched with X-Admin-Key."""
    registry = get_registry()
    classes = [{"id": c.id, "name": c.name} for c in registry.classes]
    shared = {"id": registry.shared_scope.id, "name": registry.shared_scope.name}
    context = {"classes": classes, "shared": shared, "max_upload_mb": get_settings().max_upload_mb}
    return render(request, "admin.html", context)
