import logging
from functools import lru_cache
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[3]
logger = logging.getLogger(__name__)


def _package_version() -> str:
    try:
        return version("app")
    except PackageNotFoundError:
        return "0.0.0"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # API
    api_title: str = "Agent Service"
    api_description: str = (
        "FastAPI + LangGraph boilerplate built around a generate/judge/revise loop."
    )
    api_version: str = Field(default_factory=_package_version)
    cors_allow_origins: list[str] = ["*"]

    # LLM gateway. Every model call goes through the LiteLLM proxy, which is
    # OpenAI-API compatible, so the application holds no provider credentials.
    llm_base_url: str = "http://litellm:4000/v1"
    llm_api_key: SecretStr
    llm_model: str = "default"
    llm_temperature: float = 0
    llm_timeout_seconds: float = 60
    llm_max_retries: int = 2

    # Workflow
    max_iterations: int = 3

    # Logging
    log_level: str = "INFO"
    log_format: Literal["text", "json"] = "text"

    # OpenTelemetry
    otel_enabled: bool = True
    otel_service_name: str = "agent-service"
    otel_exporter_otlp_endpoint: str = "http://otel-collector:4318"


@lru_cache
def get_settings() -> Settings:
    # Required fields come from the environment, which mypy cannot see.
    return Settings()  # type: ignore[call-arg]
