"""OpenAI chat completions in JSON mode. SDK retries are off (max_retries=0): see providers/retry.py."""

import openai
from openai import AsyncOpenAI

from app.providers.base import LLMResult, Message, PermanentLLMError, TransientLLMError

_TRANSIENT = (
    openai.APITimeoutError,
    openai.APIConnectionError,
    openai.RateLimitError,
    openai.InternalServerError,
)


class OpenAILLM:
    name = "openai"

    def __init__(self, api_key: str, model: str, timeout: float) -> None:
        self.model = model
        self._client = AsyncOpenAI(api_key=api_key, timeout=timeout, max_retries=0)

    async def complete_json(self, messages: list[Message], *, max_output_tokens: int) -> LLMResult:
        try:
            response = await self._client.chat.completions.create(
                model=self.model,
                messages=messages,  # type: ignore[arg-type]
                response_format={"type": "json_object"},
                max_completion_tokens=max_output_tokens,
            )
        except _TRANSIENT as exc:
            raise TransientLLMError(type(exc).__name__) from exc
        except openai.APIStatusError as exc:
            if exc.status_code >= 500:
                raise TransientLLMError(f"http {exc.status_code}") from exc
            raise PermanentLLMError(f"http {exc.status_code}") from exc
        usage = response.usage
        return LLMResult(
            text=response.choices[0].message.content or "",
            input_tokens=usage.prompt_tokens if usage else 0,
            output_tokens=usage.completion_tokens if usage else 0,
            model=response.model or self.model,
        )
