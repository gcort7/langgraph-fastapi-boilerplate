from collections.abc import Callable
from typing import Annotated

from fastapi import Depends, Request
from langgraph.graph.state import CompiledStateGraph

from app.orchestrator import POETRY
from app.orchestrator.transitions import TransitionSink


def graph_dependency(name: str) -> Callable[[Request], CompiledStateGraph]:
    """Resolve a graph compiled at startup, so routes stay injectable in tests."""

    def dependency(request: Request) -> CompiledStateGraph:
        return request.app.state.graphs[name]

    return dependency


# Named at module level so tests can target it with `dependency_overrides`.
get_poetry_graph = graph_dependency(POETRY)

PoetryGraph = Annotated[CompiledStateGraph, Depends(get_poetry_graph)]


def get_transition_sink(request: Request) -> TransitionSink | None:
    return request.app.state.transition_sink


TransitionSinkDep = Annotated[TransitionSink | None, Depends(get_transition_sink)]
