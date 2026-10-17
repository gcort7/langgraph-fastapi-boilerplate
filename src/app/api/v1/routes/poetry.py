import logging

from fastapi import APIRouter

from app.api.dependencies import PoetryGraph, TransitionSinkDep
from app.api.errors import WorkflowError
from app.api.v1.schemas import PoemRequest, PoemResponse
from app.config import get_settings
from app.orchestrator import POETRY
from app.orchestrator.transitions import run_recorded
from app.orchestrator.workflows.poetry import PoetryState

logger = logging.getLogger(__name__)

router = APIRouter(tags=["poetry"])


@router.post("/poems", response_model=PoemResponse)
async def write_poem(
    body: PoemRequest, graph: PoetryGraph, sink: TransitionSinkDep
) -> PoemResponse:
    max_iterations = body.max_iterations or get_settings().max_iterations
    logger.info(
        "Received poem request topic_chars=%s max_iterations=%s",
        len(body.topic),
        max_iterations,
    )

    initial_state = PoetryState(topic=body.topic, max_iterations=max_iterations)
    try:
        result = await run_recorded(
            graph,
            initial_state.model_dump(),
            workflow=POETRY,
            sink=sink,
            # Two nodes per round, plus headroom, so the cap is enforced by the
            # loop's own accounting rather than by LangGraph's recursion guard.
            config={"recursion_limit": 2 * max_iterations + 5},
        )
    except Exception as exc:
        logger.exception("Poetry workflow failed")
        raise WorkflowError(POETRY) from exc

    final_state = PoetryState.model_validate(result)
    logger.info(
        "Poem request finished approved=%s iteration=%s",
        final_state.approved,
        final_state.iteration,
    )
    return PoemResponse.from_state(final_state)
