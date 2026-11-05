"""arq worker settings.

Run: arq app.workers.main.WorkerSettings
"""

from typing import Any

from arq.connections import RedisSettings

from app.core.config import get_settings
from app.core.logging import setup_logging
from app.workers.tasks import process_message, send_notice


async def on_startup(_ctx: dict[str, Any]) -> None:
    setup_logging(get_settings().log_level)


class WorkerSettings:
    functions = [process_message, send_notice]
    on_startup = on_startup
    redis_settings = RedisSettings.from_dsn(get_settings().redis_url.get_secret_value())
    max_tries = 3
