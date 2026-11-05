"""Build providers from settings (EMBEDDING_PROVIDER / LLM_PROVIDER)."""

from functools import lru_cache

from app.core.config import Settings, get_settings
from app.providers.base import EmbeddingProvider, LLMProvider
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


def build_llm_provider(settings: Settings) -> LLMProvider:
    name, model, timeout = settings.llm_provider, settings.llm_model, settings.llm_timeout_seconds
    if name == "fake":
        from app.providers.fake_llm import FakeLLM

        return FakeLLM(model)
    if name == "openai":
        from app.providers.openai_llm import OpenAILLM

        if settings.openai_api_key is None:
            raise ProviderConfigError("LLM_PROVIDER=openai but OPENAI_API_KEY is not set")
        return OpenAILLM(settings.openai_api_key.get_secret_value(), model, timeout)
    if name == "gemini":
        from app.providers.gemini_llm import GeminiLLM

        if settings.gemini_api_key is None:
            raise ProviderConfigError("LLM_PROVIDER=gemini but GEMINI_API_KEY is not set")
        return GeminiLLM(settings.gemini_api_key.get_secret_value(), model, timeout)
    raise ProviderConfigError(f"unknown llm provider {name!r}")


@lru_cache
def get_llm_provider() -> LLMProvider:
    return build_llm_provider(get_settings())
