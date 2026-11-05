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


# ------------------------------------------------------------------ LLM

Message = dict[str, str]  # {"role": "system" | "user" | "assistant", "content": "..."}


@dataclass(frozen=True)
class LLMResult:
    text: str
    input_tokens: int
    output_tokens: int
    model: str


class TransientLLMError(RuntimeError):
    """Worth retrying: rate limit (429), server error (5xx), timeout, connection problem."""


class PermanentLLMError(RuntimeError):
    """Not worth retrying: bad request, auth failure, unknown model, ..."""


class LLMProvider(Protocol):
    name: str
    model: str

    async def complete_json(self, messages: list[Message], *, max_output_tokens: int) -> LLMResult:
        """One chat completion constrained to a JSON object. Raises Transient/PermanentLLMError."""
        ...
