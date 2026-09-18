from collections.abc import Iterator

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import SecretStr

from app.api.dependencies import get_poetry_graph
from app.api.server import create_app
from app.config import Settings
from app.config.config import get_settings
from app.orchestrator.llm import default_llm

from .fakes import FakeGraph


@pytest.fixture(autouse=True)
def isolated_environment(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Keep tests off the developer's .env and off any cached client.

    `create_app` compiles graphs in its lifespan, which resolves the process
    settings, so the required variables have to exist even though no test ever
    reaches the network.
    """
    monkeypatch.setenv("LLM_API_KEY", "test-key")
    monkeypatch.setenv("OTEL_ENABLED", "false")
    get_settings.cache_clear()
    default_llm.cache_clear()
    yield
    get_settings.cache_clear()
    default_llm.cache_clear()


@pytest.fixture
def settings() -> Settings:
    # _env_file=None keeps tests independent of a developer's local .env.
    return Settings(  # type: ignore[call-arg]
        llm_api_key=SecretStr("test-key"),
        max_iterations=3,
        log_level="INFO",
        log_format="text",
        otel_enabled=False,
        _env_file=None,
    )


@pytest.fixture
def fake_graph() -> FakeGraph:
    return FakeGraph({"approved": True, "iteration": 1, "feedback": ""})


@pytest.fixture
def app(settings: Settings) -> FastAPI:
    return create_app(settings)


@pytest.fixture
def client(app: FastAPI, fake_graph: FakeGraph) -> Iterator[TestClient]:
    app.dependency_overrides[get_poetry_graph] = lambda: fake_graph
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()
