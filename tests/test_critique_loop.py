import pytest
from pydantic import BaseModel, ValidationError

from app.orchestrator.critique_loop import Critique, CritiqueLoopState, should_continue
from app.orchestrator.workflows.poetry import Poem, PoetryState, build_poetry_graph
from app.orchestrator.workflows.poetry.prompts import judge_prompt

from .fakes import StubChatModel


def _state(**overrides: object) -> CritiqueLoopState:
    base: dict[str, object] = {"max_iterations": 3}
    return CritiqueLoopState(**{**base, **overrides})  # type: ignore[arg-type]


def _poem(title: str) -> Poem:
    return Poem(title=title, body="a line\nanother line")


def _stub(poems: list[BaseModel], critiques: list[BaseModel]) -> StubChatModel:
    return StubChatModel(queues={"Poem": poems, "Critique": critiques})


async def _run(stub: StubChatModel, max_iterations: int = 3) -> PoetryState:
    graph = build_poetry_graph(llm=stub)
    result = await graph.ainvoke(
        PoetryState(
            topic="a lighthouse in fog", max_iterations=max_iterations
        ).model_dump()
    )
    return PoetryState.model_validate(result)


def test_approved_candidate_stops_the_loop() -> None:
    assert should_continue(_state(approved=True, iteration=1)) == "stop"


def test_loop_stops_once_max_iterations_is_reached() -> None:
    assert should_continue(_state(approved=False, iteration=3)) == "stop"


def test_rejected_candidate_goes_back_for_revision() -> None:
    assert should_continue(_state(approved=False, iteration=1)) == "continue"


def test_state_requires_a_positive_iteration_cap() -> None:
    with pytest.raises(ValidationError):
        _state(max_iterations=0)


async def test_first_draft_approved_runs_a_single_round() -> None:
    stub = _stub(
        poems=[_poem("Fog")],
        critiques=[Critique(approved=True, feedback="")],
    )

    final = await _run(stub)

    assert final.approved is True
    assert final.iteration == 1
    assert final.feedback == ""
    assert final.poem == _poem("Fog")


async def test_rejection_feeds_the_critique_into_the_next_draft() -> None:
    stub = _stub(
        poems=[_poem("Draft"), _poem("Revised")],
        critiques=[
            Critique(approved=False, feedback="line 2 is a cliché"),
            Critique(approved=True, feedback=""),
        ],
    )

    final = await _run(stub)

    assert final.approved is True
    assert final.iteration == 2
    assert final.poem == _poem("Revised")
    # The revision prompt must carry both the feedback and the rejected draft.
    revisions = stub.prompts_containing("line 2 is a cliché")
    assert len(revisions) == 1
    assert "Draft" in revisions[0]


async def test_persistent_rejection_stops_at_the_iteration_cap() -> None:
    stub = _stub(
        poems=[_poem("Draft")],
        critiques=[Critique(approved=False, feedback="still not there")],
    )

    final = await _run(stub, max_iterations=2)

    assert final.approved is False
    assert final.iteration == 2
    assert final.feedback == "still not there"


@pytest.mark.parametrize("failing_schema", ["Poem", "Critique"])
async def test_model_failures_propagate_out_of_the_loop(failing_schema: str) -> None:
    stub = _stub(poems=[_poem("Fog")], critiques=[Critique(approved=True, feedback="")])
    stub.errors[failing_schema] = RuntimeError("gateway exploded")

    with pytest.raises(RuntimeError, match="gateway exploded"):
        await _run(stub)


async def test_judging_without_a_candidate_is_a_programming_error() -> None:
    state = PoetryState(topic="fog", max_iterations=1)

    with pytest.raises(ValueError, match="poem is required"):
        judge_prompt(state)


async def test_first_draft_prompt_is_not_a_revision() -> None:
    stub = _stub(
        poems=[_poem("Fog")],
        critiques=[Critique(approved=True, feedback="")],
    )

    await _run(stub)

    assert "a lighthouse in fog" in stub.prompts[0]
    assert "previous draft" not in stub.prompts[0].lower()
