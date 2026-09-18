"""Single place where workflow graphs are declared.

To add a workflow: build it under `workflows/<name>/` exposing a
`build_*_graph(llm=None)` function, then add one entry to `GRAPH_BUILDERS`.
"""

import logging
from collections.abc import Callable

from langgraph.graph.state import CompiledStateGraph

from .workflows.poetry import POETRY, build_poetry_graph

GRAPH_BUILDERS: dict[str, Callable[[], CompiledStateGraph]] = {
    POETRY: build_poetry_graph,
}

logger = logging.getLogger(__name__)


def build_graphs() -> dict[str, CompiledStateGraph]:
    """Compile every registered graph once, at application startup."""
    graphs = {name: builder() for name, builder in GRAPH_BUILDERS.items()}
    logger.info("Compiled workflow graphs: %s", sorted(graphs))
    return graphs
