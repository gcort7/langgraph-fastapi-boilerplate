from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.dependencies import get_poetry_graph
from app.api.middleware import REQUEST_ID_HEADER
from app.api.routers import API_V1_PREFIX
from app.config import Settings

from .fakes import FakeGraph

POEMS_URL = f"{API_V1_PREFIX}/poems"
TOPIC = {"topic": "a lighthouse in fog"}


def test_poems_is_served_under_the_v1_prefix(client: TestClient) -> None:
    assert client.post(POEMS_URL, json=TOPIC).status_code == 200
    assert client.post("/poems", json=TOPIC).status_code == 404


def test_response_exposes_the_final_draft(
    client: TestClient, fake_graph: FakeGraph
) -> None:
    fake_graph.result = {
        "approved": True,
        "iteration": 2,
        "feedback": "",
        "poem": {"title": "Fog", "body": "a line\nanother line"},
    }

    body = client.post(POEMS_URL, json=TOPIC).json()

    assert body["approved"] is True
    assert body["iteration"] == 2
    assert body["poem"]["title"] == "Fog"
    assert body["critique"] == ""


def test_unapproved_response_carries_the_critique(
    client: TestClient, fake_graph: FakeGraph
) -> None:
    fake_graph.result = {
        "approved": False,
        "iteration": 3,
        "feedback": "the ending is flat",
        "poem": {"title": "Fog", "body": "a line"},
    }

    body = client.post(POEMS_URL, json=TOPIC).json()

    assert body["approved"] is False
    assert body["critique"] == "the ending is flat"


def test_max_iterations_defaults_to_settings(
    client: TestClient, fake_graph: FakeGraph, settings: Settings
) -> None:
    client.post(POEMS_URL, json=TOPIC)

    assert fake_graph.calls[0]["max_iterations"] == settings.max_iterations


def test_max_iterations_can_be_overridden_per_request(
    client: TestClient, fake_graph: FakeGraph
) -> None:
    client.post(POEMS_URL, json={**TOPIC, "max_iterations": 7})

    assert fake_graph.calls[0]["max_iterations"] == 7


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"topic": ""},
        {"topic": "a lighthouse", "max_iterations": 0},
        {"topic": "a lighthouse", "max_iterations": 11},
        {"topic": "x" * 2_001},
    ],
)
def test_invalid_payloads_are_rejected(
    client: TestClient, payload: dict[str, Any]
) -> None:
    response = client.post(POEMS_URL, json=payload)

    assert response.status_code == 422
    assert response.json()["error"] == "invalid_request"


def test_workflow_failure_returns_a_502_envelope(app: FastAPI) -> None:
    class BrokenGraph:
        async def ainvoke(
            self, payload: dict[str, Any], config: dict[str, Any] | None = None
        ) -> dict[str, Any]:
            raise RuntimeError("upstream exploded")

    app.dependency_overrides[get_poetry_graph] = BrokenGraph
    with TestClient(app) as client:
        response = client.post(POEMS_URL, json=TOPIC)

    assert response.status_code == 502
    body = response.json()
    assert body["error"] == "workflow_failed"
    assert "poetry" in body["detail"]
    # The envelope is how a caller reports a failure back to an operator.
    assert body["request_id"] == response.headers[REQUEST_ID_HEADER]


def test_recursion_limit_is_derived_from_the_iteration_cap(app: FastAPI) -> None:
    class RecordingGraph:
        def __init__(self) -> None:
            self.config: dict[str, Any] | None = None

        async def ainvoke(
            self, payload: dict[str, Any], config: dict[str, Any] | None = None
        ) -> dict[str, Any]:
            self.config = config
            return {**payload, "approved": True, "iteration": 1, "feedback": ""}

    graph = RecordingGraph()
    app.dependency_overrides[get_poetry_graph] = lambda: graph
    with TestClient(app) as client:
        client.post(POEMS_URL, json={**TOPIC, "max_iterations": 4})

    assert graph.config is not None
    assert graph.config["recursion_limit"] == 13
