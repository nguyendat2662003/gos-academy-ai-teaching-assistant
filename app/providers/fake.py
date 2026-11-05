"""Deterministic offline embedding for tests: hashed bag of (accent-folded) words and word bigrams.

Texts sharing words get a high cosine similarity, so retrieval logic can be tested without any API.
"""

import hashlib
import math
import re

from app.ingestion.text import estimate_tokens, fold
from app.providers.base import EmbeddingResult, EmbedKind

_WORD_RE = re.compile(r"\w+", re.UNICODE)


def _bucket(feature: str, dim: int) -> tuple[int, float]:
    digest = hashlib.blake2b(feature.encode(), digest_size=8).digest()
    value = int.from_bytes(digest, "big")
    return value % dim, 1.0 if (value >> 63) & 1 else -1.0


def fake_vector(text: str, dim: int) -> list[float]:
    words = _WORD_RE.findall(fold(text))
    features = words + [f"{a} {b}" for a, b in zip(words, words[1:], strict=False)]
    vec = [0.0] * dim
    vec[0] = 0.01  # keeps the vector non-zero for empty text (cosine of a zero vector is undefined)
    for feature in features:
        index, sign = _bucket(feature, dim)
        vec[index] += sign
    norm = math.sqrt(sum(v * v for v in vec))
    return [v / norm for v in vec]


class FakeEmbeddingProvider:
    name = "fake"

    def __init__(self, model: str, dim: int) -> None:
        self.model = model
        self.dim = dim
        self.calls = 0

    async def embed(self, texts: list[str], kind: EmbedKind) -> EmbeddingResult:
        self.calls += 1
        return EmbeddingResult(
            vectors=[fake_vector(t, self.dim) for t in texts],
            tokens=sum(estimate_tokens(t) for t in texts),
            tokens_estimated=True,
        )
