"""Gemini embeddings via the official google-genai SDK.

Not exercised by the automated tests (no network); verify against https://ai.google.dev before relying on it.
Gemini distinguishes document and query embeddings through `task_type`; `output_dimensionality` shortens
vectors to EMBEDDING_DIM. The embed response does not report token usage, so tokens are estimated.
"""

from google import genai
from google.genai import types

from app.ingestion.text import estimate_tokens
from app.providers.base import EmbeddingResult, EmbedKind, check_dimensions

_TASK = {"document": "RETRIEVAL_DOCUMENT", "query": "RETRIEVAL_QUERY"}


class GeminiEmbeddingProvider:
    name = "gemini"

    def __init__(self, api_key: str, model: str, dim: int, timeout: float) -> None:
        self.model = model
        self.dim = dim
        self._client = genai.Client(
            api_key=api_key, http_options=types.HttpOptions(timeout=int(timeout * 1000))
        )

    async def embed(self, texts: list[str], kind: EmbedKind) -> EmbeddingResult:
        response = await self._client.aio.models.embed_content(
            model=self.model,
            contents=texts,
            config=types.EmbedContentConfig(task_type=_TASK[kind], output_dimensionality=self.dim),
        )
        vectors = [list(e.values or []) for e in response.embeddings or []]
        check_dimensions(vectors, self.dim)
        return EmbeddingResult(
            vectors=vectors, tokens=sum(estimate_tokens(t) for t in texts), tokens_estimated=True
        )
