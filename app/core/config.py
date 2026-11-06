"""Application settings loaded from environment variables (never from source code)."""

from functools import lru_cache
from typing import Annotated, Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

ProviderName = Literal["gemini", "openai", "fake"]


class Settings(BaseSettings):
    """All runtime configuration. Secrets are SecretStr so they never show up in repr/logs."""

    # hide_input_in_errors: a malformed secret must not be echoed into the startup error / container log.
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore", hide_input_in_errors=True
    )

    app_env: Literal["dev", "prod", "test"] = "dev"
    log_level: str = "INFO"

    database_url: SecretStr
    redis_url: SecretStr

    webhook_secret: SecretStr
    admin_api_key: SecretStr
    # One key per class for its instructor: "GS-KPI-01=<key>,AUTO-N8N-01=<key>". An instructor key only
    # opens that class's tickets/documents/stats in the admin area (DECISIONS D-83). Empty = admin only.
    instructor_api_keys: Annotated[dict[str, SecretStr], NoDecode] = {}
    ask_api_key: SecretStr
    user_hash_salt: SecretStr

    llm_provider: ProviderName = "fake"
    llm_model: str = "fake-llm"
    llm_timeout_seconds: float = 30.0
    llm_max_retries: int = Field(default=3, ge=0, le=10)
    llm_retry_base_delay: float = Field(default=1.0, ge=0)  # seconds; doubles on each retry
    llm_max_output_tokens: int = Field(default=1200, gt=0)
    gemini_api_key: SecretStr | None = None
    openai_api_key: SecretStr | None = None

    embedding_provider: ProviderName = "fake"
    embedding_model: str = "fake-embedding"
    embedding_dim: int = Field(default=768, gt=0, le=4000)

    guard_llm_enabled: bool = False
    trigger_prefixes: Annotated[list[str], NoDecode] = ["/hoi"]
    rate_limit_user_per_min: int = Field(default=5, gt=0)
    rate_limit_class_per_min: int = Field(default=30, gt=0)
    retrieval_top_k: int = Field(default=5, gt=0, le=50)
    retrieval_min_score: float = Field(default=0.35, ge=-1.0, le=1.0)
    context_max_turns: int = Field(default=6, ge=0)
    context_ttl_minutes: int = Field(default=30, gt=0)

    # FAQ tables (DOCX) / sheets (XLSX): header names recognised as question / answer / section-code columns.
    # Compared case- and accent-insensitively.
    faq_question_columns: Annotated[list[str], NoDecode] = ["câu hỏi", "question", "hỏi"]
    faq_answer_columns: Annotated[list[str], NoDecode] = ["trả lời mẫu", "trả lời", "answer", "đáp án"]
    faq_section_columns: Annotated[list[str], NoDecode] = ["mã mục", "section", "mục"]
    chunk_max_tokens: int = Field(default=800, gt=50)
    chunk_target_tokens: int = Field(default=600, gt=50)
    chunk_overlap_ratio: float = Field(default=0.12, ge=0, lt=0.5)

    embedding_batch_size: int = Field(default=64, gt=0, le=2048)
    storage_dir: str = "data/uploads"  # original files, kept so documents can be re-indexed
    max_upload_mb: int = Field(default=10, gt=0)

    classes_config_path: str = "config/classes.yaml"
    pricing_config_path: str = "config/pricing.yaml"

    @field_validator(
        "trigger_prefixes", "faq_question_columns", "faq_answer_columns", "faq_section_columns", mode="before"
    )
    @classmethod
    def _split_prefixes(cls, value: object) -> object:
        if isinstance(value, str):
            return [p.strip() for p in value.split(",") if p.strip()]
        return value

    @field_validator("instructor_api_keys", mode="before")
    @classmethod
    def _parse_instructor_keys(cls, value: object) -> object:
        """ "CLASS=key,CLASS=key" -> {class: key}. Errors never echo a key back."""
        if not isinstance(value, str):
            return value
        keys: dict[str, str] = {}
        for item in (p.strip() for p in value.split(",")):
            if not item:
                continue
            class_id, sep, key = (s.strip() for s in item.partition("="))
            if not sep or not class_id or len(key) < 16:
                raise ValueError("INSTRUCTOR_API_KEYS: expected CLASS_ID=<key of at least 16 characters>")
            if class_id in keys:
                raise ValueError(f"INSTRUCTOR_API_KEYS: class {class_id} listed twice")
            keys[class_id] = key
        if len(set(keys.values())) != len(keys):
            raise ValueError("INSTRUCTOR_API_KEYS: every class needs its own key")
        return keys

    @field_validator("gemini_api_key", "openai_api_key", mode="before")
    @classmethod
    def _empty_to_none(cls, value: object) -> object:
        return None if value == "" else value


@lru_cache
def get_settings() -> Settings:
    """Return the process-wide settings singleton."""
    return Settings()  # type: ignore[call-arg]
