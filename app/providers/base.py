"""Provider interfaces. Concrete providers: openai, gemini, fake (offline, deterministic)."""

from dataclasses import dataclass
from typing import Literal, Protocol

EmbedKind = Literal["document", "query"]


@dataclass(frozen=True)
class EmbeddingResult:
    vectors: list[list[float]]
    tokens: int  # as reported by the provider (estimated only when the provider does not report it)
    tokens_estimated: bool = False


class EmbeddingDimensionError(RuntimeError):
    """The provider returned vectors whose size differs from EMBEDDING_DIM (DB column size)."""


class EmbeddingProvider(Protocol):
    name: str
    model: str
    dim: int

    async def embed(self, texts: list[str], kind: EmbedKind) -> EmbeddingResult: ...


def check_dimensions(vectors: list[list[float]], dim: int) -> None:
    bad = {len(v) for v in vectors if len(v) != dim}
    if bad:
        raise EmbeddingDimensionError(f"expected {dim} dimensions, got {sorted(bad)}")
