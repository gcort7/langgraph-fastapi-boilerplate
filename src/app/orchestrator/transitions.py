"""Record every node-to-node transition of a workflow run for offline Markov analysis.

One JSON object per line (JSONL), so concurrent runs and different workflows
can append to the same file without rewriting it.
"""

import asyncio
import logging
import threading
import time
from collections import defaultdict
from collections.abc import Sequence
from pathlib import Path
from typing import Any, Protocol, cast
from uuid import UUID, uuid4

from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.messages import AIMessage
from langchain_core.messages.ai import UsageMetadata
from langchain_core.outputs import ChatGeneration, LLMResult
from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, START
from langgraph.graph.state import CompiledStateGraph
from pydantic import BaseModel

from app.config import get_request_id

logger = logging.getLogger(__name__)

# Set by the LiteLLM proxy; requires `include_response_headers=True` on the client.
LITELLM_COST_HEADER = "x-litellm-response-cost"


class LLMCall(BaseModel):
    model: str
    input_tokens: int
    output_tokens: int
    cost_usd: float | None


class Transition(BaseModel):
    run_id: UUID
    request_id: str
    workflow: str
    step: int
    iteration: int | None
    origin: str
    destination: str
    elapsed_seconds: float
    model: str | None
    input_tokens: int
    output_tokens: int
    cost_usd: float | None


class TransitionSink(Protocol):
    async def write(self, transitions: Sequence[Transition]) -> None: ...


class JsonlTransitionSink:
    def __init__(self, path: Path) -> None:
        self._path = path
        self._lock = threading.Lock()

    async def write(self, transitions: Sequence[Transition]) -> None:
        payload = "".join(t.model_dump_json() + "\n" for t in transitions)
        await asyncio.to_thread(self._append, payload)

    def _append(self, payload: str) -> None:
        with self._lock:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            with self._path.open("a", encoding="utf-8") as f:
                f.write(payload)


class LLMUsageCollector(BaseCallbackHandler):
    """Attributes each chat-model call to the graph node that made it."""

    # Mutate shared state on the event loop instead of a thread pool.
    run_inline = True

    def __init__(self) -> None:
        self._node_by_run: dict[UUID, str] = {}
        self._calls_by_node: defaultdict[str, list[LLMCall]] = defaultdict(list)

    def on_chat_model_start(
        self,
        serialized: dict[str, Any],
        messages: list[list[Any]],
        *,
        run_id: UUID,
        metadata: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> None:
        self._node_by_run[run_id] = (metadata or {}).get("langgraph_node", "")

    def on_llm_end(self, response: LLMResult, *, run_id: UUID, **kwargs: Any) -> None:
        node = self._node_by_run.pop(run_id, "")
        generation = response.generations[0][0]
        usage: UsageMetadata | dict[str, int] = (
            generation.message.usage_metadata
            if isinstance(generation, ChatGeneration)
            and isinstance(generation.message, AIMessage)
            else None
        ) or {}
        cost = ((generation.generation_info or {}).get("headers") or {}).get(
            LITELLM_COST_HEADER
        )
        self._calls_by_node[node].append(
            LLMCall(
                model=(response.llm_output or {}).get("model_name", "unknown"),
                input_tokens=usage.get("input_tokens", 0),
                output_tokens=usage.get("output_tokens", 0),
                cost_usd=float(cost) if cost is not None else None,
            )
        )

    def drain(self, node: str) -> list[LLMCall]:
        return self._calls_by_node.pop(node, [])


async def run_recorded(
    graph: CompiledStateGraph,
    state: dict[str, Any],
    *,
    workflow: str,
    sink: TransitionSink | None,
    config: RunnableConfig | None = None,
) -> dict[str, Any]:
    """Run `graph` to completion, recording START -> ... -> END transitions."""
    run_id = uuid4()
    request_id = get_request_id()
    collector = LLMUsageCollector()
    run_config = RunnableConfig(**(config or {}))
    run_config["callbacks"] = [collector]
    run_config["run_id"] = run_id
    transitions: list[Transition] = []
    values = state
    origin = START
    started = time.perf_counter()

    def record(destination: str, iteration: int | None, calls: list[LLMCall]) -> None:
        nonlocal origin, started
        now = time.perf_counter()
        costs = [c.cost_usd for c in calls if c.cost_usd is not None]
        transitions.append(
            Transition(
                run_id=run_id,
                request_id=request_id,
                workflow=workflow,
                step=len(transitions),
                iteration=iteration,
                origin=origin,
                destination=destination,
                elapsed_seconds=now - started,
                # A node may call the model more than once; usage is summed per transition.
                model=",".join(dict.fromkeys(c.model for c in calls)) or None,
                input_tokens=sum(c.input_tokens for c in calls),
                output_tokens=sum(c.output_tokens for c in calls),
                cost_usd=sum(costs) if costs else None,
            )
        )
        origin, started = destination, now

    try:
        async for mode, chunk in graph.astream(
            state, run_config, stream_mode=["updates", "values"]
        ):
            payload = cast(dict[str, Any], chunk)
            if mode == "values":
                values = payload
                continue
            for node, update in payload.items():
                iteration = (update or {}).get("iteration", values.get("iteration"))
                record(node, iteration, collector.drain(node))
        record(END, values.get("iteration"), [])
        return values
    finally:
        if sink is not None and transitions:
            try:
                await sink.write(transitions)
            except Exception:
                # Analytics must never fail the request it is observing.
                logger.exception("Failed to persist transitions run_id=%s", run_id)
