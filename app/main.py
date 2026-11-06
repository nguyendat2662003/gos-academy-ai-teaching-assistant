"""FastAPI application entrypoint."""

import logging
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response

from app.api import admin, admin_documents, admin_handoffs, admin_stats, ask, demo, health, pages, webhooks
from app.api.deps import staff_keys
from app.core.config import get_settings
from app.core.logging import new_request_id, request_id_var, setup_logging
from app.core.redis import get_redis
from app.db.session import get_engine

logger = logging.getLogger("app")


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    setup_logging(get_settings().log_level)
    instructors = len(staff_keys()) - 1  # validates INSTRUCTOR_API_KEYS against classes.yaml: fail fast
    logger.info(
        "api started", extra={"fields": {"app_env": get_settings().app_env, "instructor_keys": instructors}}
    )
    yield
    await get_redis().aclose()
    await get_engine().dispose()


def create_app() -> FastAPI:
    app = FastAPI(title="GOS Academy AI Teaching Assistant", version="0.1.0", lifespan=lifespan)

    @app.middleware("http")
    async def request_context(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        token = request_id_var.set(new_request_id())
        started = time.perf_counter()
        try:
            response = await call_next(request)
            response.headers["X-Request-ID"] = request_id_var.get() or ""
            logger.info(
                "http request",
                extra={
                    "fields": {
                        "method": request.method,
                        "path": request.url.path,  # path only: query strings may carry data
                        "status": response.status_code,
                        "latency_ms": round((time.perf_counter() - started) * 1000),
                    }
                },
            )
            return response
        finally:
            request_id_var.reset(token)

    app.include_router(health.router)
    app.include_router(webhooks.router)
    app.include_router(admin.router)
    app.include_router(admin_documents.router)
    app.include_router(admin_handoffs.router)
    app.include_router(admin_stats.router)
    app.include_router(ask.router)
    app.include_router(pages.router)
    app.include_router(demo.router)
    return app


app = create_app()
