"""Gemini generate_content in JSON mode via google-genai.

Not exercised by the automated tests (no network); verify against https://ai.google.dev before relying on it.
"""

from google import genai
from google.genai import errors, types

from app.providers.base import LLMResult, Message, PermanentLLMError, TransientLLMError


class GeminiLLM:
    name = "gemini"

    def __init__(self, api_key: str, model: str, timeout: float) -> None:
        self.model = model
        self._client = genai.Client(
            api_key=api_key, http_options=types.HttpOptions(timeout=int(timeout * 1000))
        )

    async def complete_json(self, messages: list[Message], *, max_output_tokens: int) -> LLMResult:
        system = "\n\n".join(m["content"] for m in messages if m["role"] == "system")
        contents = [
            types.Content(
                role="model" if m["role"] == "assistant" else "user", parts=[types.Part(text=m["content"])]
            )
            for m in messages
            if m["role"] != "system"
        ]
        try:
            response = await self._client.aio.models.generate_content(
                model=self.model,
                contents=contents,
                config=types.GenerateContentConfig(
                    system_instruction=system or None,
                    response_mime_type="application/json",
                    max_output_tokens=max_output_tokens,
                ),
            )
        except errors.APIError as exc:
            code = getattr(exc, "code", 0) or 0
            if code == 429 or code >= 500:
                raise TransientLLMError(f"http {code}") from exc
            raise PermanentLLMError(f"http {code}") from exc
        usage = response.usage_metadata
        return LLMResult(
            text=response.text or "",
            input_tokens=(usage.prompt_token_count or 0) if usage else 0,
            output_tokens=(usage.candidates_token_count or 0) if usage else 0,
            model=self.model,
        )
