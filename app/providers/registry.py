"""Build providers from settings (EMBEDDING_PROVIDER / LLM_PROVIDER)."""

from functools import lru_cache

from app.core.config import Settings, get_settings
from app.providers.base import EmbeddingProvider
from app.providers.fake import FakeEmbeddingProvider


class ProviderConfigError(RuntimeError):
    """Raised when a provider is selected but its API key is missing (the key itself is never shown)."""


def build_embedding_provider(settings: Settings) -> EmbeddingProvider:
    name, model, dim = settings.embedding_provider, settings.embedding_model, settings.embedding_dim
    if name == "fake":
        return FakeEmbeddingProvider(model, dim)
    if name == "openai":
        from app.providers.openai_provider import OpenAIEmbeddingProvider

        if settings.openai_api_key is None:
            raise ProviderConfigError("EMBEDDING_PROVIDER=openai but OPENAI_API_KEY is not set")
        return OpenAIEmbeddingProvider(
            settings.openai_api_key.get_secret_value(),
            model,
            dim,
            settings.llm_timeout_seconds,
            settings.llm_max_retries,
        )
    if name == "gemini":
        from app.providers.gemini_provider import GeminiEmbeddingProvider

        if settings.gemini_api_key is None:
            raise ProviderConfigError("EMBEDDING_PROVIDER=gemini but GEMINI_API_KEY is not set")
        return GeminiEmbeddingProvider(
            settings.gemini_api_key.get_secret_value(), model, dim, settings.llm_timeout_seconds
        )
    raise ProviderConfigError(f"unknown embedding provider {name!r}")


@lru_cache
def get_embedding_provider() -> EmbeddingProvider:
    return build_embedding_provider(get_settings())
