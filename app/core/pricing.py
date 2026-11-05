"""Token prices from config/pricing.yaml (filled in by hand from the official pricing pages; never hardcoded).

Unknown price -> cost None (never silently 0): stats then report the cost as incomplete and name the model.
Zero tokens always cost 0, so requests that never called a provider are fully priced.
"""

from functools import lru_cache
from pathlib import Path

import yaml
from pydantic import BaseModel, Field

from app.core.config import get_settings


class ModelPrice(BaseModel):
    input: float | None = Field(default=None, ge=0)
    output: float | None = Field(default=None, ge=0)


class Pricing(BaseModel):
    checked_at: str | None = None
    currency: str = "USD"
    unit_tokens: int = Field(default=1_000_000, gt=0)
    models: dict[str, ModelPrice] = Field(default_factory=dict)

    def price_for(self, model: str | None) -> ModelPrice | None:
        """Exact name, else the longest configured prefix ('gpt-x-2026-01-01' -> 'gpt-x')."""
        if not model:
            return None
        if model in self.models:
            return self.models[model]
        prefixes = [name for name in self.models if model.startswith(name + "-")]
        return self.models[max(prefixes, key=len)] if prefixes else None

    def _part(self, model: str | None, tokens: int, kind: str) -> float | None:
        if not tokens:
            return 0.0
        price = self.price_for(model)
        per_unit = getattr(price, kind) if price else None
        return None if per_unit is None else tokens * per_unit / self.unit_tokens

    def llm_cost(self, model: str | None, input_tokens: int, output_tokens: int) -> float | None:
        parts = (self._part(model, input_tokens, "input"), self._part(model, output_tokens, "output"))
        return None if None in parts else sum(parts)  # type: ignore[arg-type]

    def embedding_cost(self, model: str | None, tokens: int) -> float | None:
        return self._part(model, tokens, "input")

    def request_cost(
        self,
        *,
        model: str | None,
        input_tokens: int,
        output_tokens: int,
        embedding_model: str | None,
        embedding_tokens: int,
    ) -> float | None:
        parts = (
            self.llm_cost(model, input_tokens, output_tokens),
            self.embedding_cost(embedding_model, embedding_tokens),
        )
        return None if None in parts else sum(parts)  # type: ignore[arg-type]


def load_pricing(path: str | Path) -> Pricing:
    with open(path, encoding="utf-8") as fh:
        return Pricing.model_validate(yaml.safe_load(fh) or {})


@lru_cache
def get_pricing() -> Pricing:
    return load_pricing(get_settings().pricing_config_path)
