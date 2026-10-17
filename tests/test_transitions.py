import json
from collections.abc import Sequence
from pathlib import Path
from uuid import uuid4

import pytest
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, LLMResult
from langgraph.graph import END, START
from pydantic import BaseModel

from app.orchestrator.critique_loop import (
    EXHAUSTED,
    GENERATE,
    JUDGE,
    SUCCESS,
    Critique,
)
from app.orchestrator.transitions import (
    LITELLM_COST_HEADER,
    JsonlTransitionSink,
    LLMUsageCollector,
    Transition,
    run_recorded,
)
from app.orchestrator.workflows.poetry import (
    POETRY,
    Poem,
    PoetryState,
    build_poetry_graph,
)

from .fakes import StubChatModel


class MemorySink:
    def __init__(self) -> None:
        self.transitions: list[Transition] = []

    async def write(self, transitions: Sequence[Transition]) -> None:
        self.transitions.extend(transitions)


def _graph(critiques: list[BaseModel]) -> StubChatModel:
    return StubChatModel(
        queues={"Poem": [Poem(title="Fog", body="a line")], "Critique": critiques}
    )


async def test_records_the_full_path_from_start_to_end() -> None:
    graph = build_poetry_graph(
        llm=_graph(
            [
                Critique(approved=False, feedback="sharper"),
                Critique(approved=True, feedback=""),
            ]
        )
    )
    sink = MemorySink()

    result = await run_recorded(
        graph,
        PoetryState(topic="fog", max_iterations=3).model_dump(),
        workflow=POETRY,
        sink=sink,
    )

    path = [(t.origin, t.destination) for t in sink.transitions]
    assert path == [
        (START, GENERATE),
        (GENERATE, JUDGE),
        (JUDGE, GENERATE),
        (GENERATE, JUDGE),
        (JUDGE, SUCCESS),
        (SUCCESS, END),
    ]
    assert [t.iteration for t in sink.transitions] == [1, 1, 2, 2, 2, 2]
    assert [t.step for t in sink.transitions] == [0, 1, 2, 3, 4, 5]
    assert {t.workflow for t in sink.transitions} == {POETRY}
    assert len({t.run_id for t in sink.transitions}) == 1
    assert PoetryState.model_validate(result).approved is True


async def test_unapproved_run_ends_in_exhausted() -> None:
    graph = build_poetry_graph(llm=_graph([Critique(approved=False, feedback="no")]))
    sink = MemorySink()

    await run_recorded(
        graph,
        PoetryState(topic="fog", max_iterations=2).model_dump(),
        workflow=POETRY,
        sink=sink,
    )

    assert [(t.origin, t.destination) for t in sink.transitions][-2:] == [
        (JUDGE, EXHAUSTED),
        (EXHAUSTED, END),
    ]


async def test_partial_path_is_persisted_when_the_workflow_fails() -> None:
    stub = _graph([Critique(approved=True, feedback="")])
    stub.errors["Critique"] = RuntimeError("boom")
    sink = MemorySink()

    with pytest.raises(RuntimeError):
        await run_recorded(
            build_poetry_graph(llm=stub),
            PoetryState(topic="fog", max_iterations=3).model_dump(),
            workflow=POETRY,
            sink=sink,
        )

    assert [(t.origin, t.destination) for t in sink.transitions] == [(START, GENERATE)]


def test_collector_attributes_model_tokens_and_cost_to_the_node() -> None:
    collector = LLMUsageCollector()
    run_id = uuid4()
    message = AIMessage(
        content="{}",
        usage_metadata={"input_tokens": 10, "output_tokens": 5, "total_tokens": 15},
    )
    collector.on_chat_model_start(
        {}, [], run_id=run_id, metadata={"langgraph_node": JUDGE}
    )
    collector.on_llm_end(
        LLMResult(
            generations=[
                [
                    ChatGeneration(
                        message=message,
                        generation_info={"headers": {LITELLM_COST_HEADER: "0.0012"}},
                    )
                ]
            ],
            llm_output={"model_name": "gpt-5-nano"},
        ),
        run_id=run_id,
    )

    [call] = collector.drain(JUDGE)
    assert call.model == "gpt-5-nano"
    assert (call.input_tokens, call.output_tokens) == (10, 5)
    assert call.cost_usd == 0.0012
    assert collector.drain(JUDGE) == []


async def test_jsonl_sink_appends_one_object_per_line(tmp_path: Path) -> None:
    path = tmp_path / "nested" / "transitions.jsonl"
    sink = JsonlTransitionSink(path)
    transition = Transition(
        run_id=uuid4(),
        request_id="q",
        workflow=POETRY,
        step=0,
        iteration=1,
        origin=START,
        destination=GENERATE,
        elapsed_seconds=0.1,
        model="gpt-5-nano",
        input_tokens=10,
        output_tokens=5,
        cost_usd=0.001,
    )

    await sink.write([transition])
    await sink.write([transition])

    lines = path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    assert json.loads(lines[0])["destination"] == GENERATE
