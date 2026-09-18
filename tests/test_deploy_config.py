"""Guards on the infrastructure config, which no unit test would otherwise cover."""

from pathlib import Path
from typing import Any

import pytest
import yaml

DEPLOY = Path(__file__).parents[1] / "deploy"


def _load(relative: str) -> Any:
    return yaml.safe_load((DEPLOY / relative).read_text(encoding="utf-8"))


def test_every_litellm_model_reads_its_key_from_the_environment() -> None:
    config = _load("litellm/config.yaml")

    for model in config["model_list"]:
        assert model["litellm_params"]["api_key"].startswith("os.environ/"), (
            f"{model['model_name']} has a literal credential in config.yaml"
        )


def test_the_default_model_alias_exists() -> None:
    config = _load("litellm/config.yaml")
    aliases = {model["model_name"] for model in config["model_list"]}

    # app.config.Settings.llm_model defaults to this alias.
    assert "default" in aliases


@pytest.mark.parametrize(
    "path",
    ["litellm/config.yaml", "otel/collector-config.yaml", "../compose.yml"],
)
def test_infrastructure_config_holds_no_inline_secrets(path: str) -> None:
    text = (DEPLOY / path).read_text(encoding="utf-8")

    assert "sk-proj-" not in text
    assert "sk-lf-" not in text


def test_collector_exports_authenticated_v4_traces_to_langfuse() -> None:
    config = _load("otel/collector-config.yaml")

    exporter = config["exporters"]["otlphttp/langfuse"]
    assert exporter["headers"]["x-langfuse-ingestion-version"] == "4"
    assert exporter["auth"]["authenticator"] == "basicauth/langfuse"
    assert "basicauth/langfuse" in config["service"]["extensions"]
    traces = config["service"]["pipelines"]["traces"]["exporters"]
    assert "otlphttp/langfuse" in traces
    # Langfuse ingests traces only; metrics must not be pointed at it.
    metrics = config["service"]["pipelines"]["metrics"]["exporters"]
    assert "otlphttp/langfuse" not in metrics
