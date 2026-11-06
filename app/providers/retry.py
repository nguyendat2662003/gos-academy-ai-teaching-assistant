"""Timeout + retry with exponential backoff around one LLM call.

Only TransientLLMError (429 / 5xx / timeout / connection) is retried, at most `max_retries` times, with delays
base, 2·base, 4·base … plus a little jitter. Provider SDK retries are disabled so this is the single policy.
"""

import asyncio
import logging
import random

from app.providers.base import LLMProvider, LLMResult, Message, TransientLLMError

logger = logging.getLogger(__name__)


async def complete_with_retry(
    llm: LLMProvider,
    messages: list[Message],
    *,
    max_output_tokens: int,
    timeout_s: float,
    max_retries: int,
    base_delay: float,
) -> LLMResult:
    attempt = 0
    while True:
        try:
            return await asyncio.wait_for(
                llm.complete_json(messages, max_output_tokens=max_output_tokens), timeout=timeout_s
            )
        except TimeoutError as exc:
            error: TransientLLMError = TransientLLMError(f"timeout after {timeout_s}s")
            error.__cause__ = exc
        except TransientLLMError as exc:
            error = exc
        if attempt >= max_retries:
            raise error
        delay = base_delay * (2**attempt) * (1 + random.random() * 0.25)  # noqa: S311 - jitter, not crypto
        logger.warning(
            "llm transient error, retrying",
            extra={
                "fields": {"attempt": attempt + 1, "delay_s": round(delay, 2), "error": type(error).__name__}
            },
        )
        await asyncio.sleep(delay)
        attempt += 1
