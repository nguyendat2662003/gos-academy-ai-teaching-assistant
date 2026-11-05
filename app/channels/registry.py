"""Resolve a channel name to its adapter instance."""

from functools import lru_cache

from app.channels.base import ChannelAdapter
from app.channels.mock import MockWebhookAdapter
from app.core.config import get_settings
from app.db.session import get_sessionmaker


@lru_cache
def get_mock_adapter() -> MockWebhookAdapter:
    return MockWebhookAdapter(get_settings().webhook_secret.get_secret_value(), get_sessionmaker())


def get_adapter(channel: str) -> ChannelAdapter:
    """Only adapters that can actually send are returned; the Zalo stub is not wired in."""
    if channel == "mock":
        return get_mock_adapter()
    raise LookupError(f"no adapter for channel {channel!r}")
