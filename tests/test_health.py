import httpx
import pytest

from app.api import health
from app.main import app


async def _get_health() -> httpx.Response:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.get("/health")


async def test_health_reports_degraded_without_leaking_config(monkeypatch) -> None:
    async def ok() -> bool:
        return True

    async def fail() -> bool:
        return False

    monkeypatch.setattr(health, "check_db", ok)
    monkeypatch.setattr(health, "check_redis", fail)
    resp = await _get_health()
    assert resp.status_code == 503
    assert resp.json() == {"status": "degraded", "checks": {"db": "ok", "redis": "fail"}}
    assert "X-Request-ID" in resp.headers


@pytest.mark.db
async def test_health_ok_against_real_services(migrated_db: str) -> None:
    resp = await _get_health()
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body == {"status": "ok", "checks": {"db": "ok", "redis": "ok"}}
    for forbidden in ("test-webhook-secret", "postgresql", "redis://", "change-me"):
        assert forbidden not in resp.text
