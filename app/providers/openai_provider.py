"""OpenAI embeddings via the official SDK.

`dimensions` asks text-embedding-3 models to return shortened vectors, so EMBEDDING_DIM can stay at the DB
column size (DECISIONS D-35). Retries with exponential backoff on 429/5xx/timeouts are done by the SDK
(max_retries = LLM_MAX_RETRIES).
"""

from openai import AsyncOpenAI

from app.providers.base import EmbeddingResult, EmbedKind, check_dimensions


class OpenAIEmbeddingProvider:
    name = "openai"

    def __init__(self, api_key: str, model: str, dim: int, timeout: float, max_retries: int) -> None:
        self.model = model
        self.dim = dim
        self._client = AsyncOpenAI(api_key=api_key, timeout=timeout, max_retries=max_retries)

    async def embed(self, texts: list[str], kind: EmbedKind) -> EmbeddingResult:
        # OpenAI embeddings are symmetric: no separate query/document mode.
        response = await self._client.embeddings.create(model=self.model, input=texts, dimensions=self.dim)
        vectors = [item.embedding for item in sorted(response.data, key=lambda d: d.index)]
        check_dimensions(vectors, self.dim)
        return EmbeddingResult(vectors=vectors, tokens=response.usage.total_tokens)
