"""The generate → judge → revise loop that every workflow here is built on.

A workflow supplies its own state model, output model and prompts. The graph
topology, the iteration cap, the approval bookkeeping and the tracing all live
in this module, so adding a workflow is a state model plus three prompts.
"""

import logging
from collections.abc import Callable
from typing import Any, Literal, cast

from langchain_core.language_models import BaseChatModel
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from opentelemetry import trace
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)
tracer = trace.get_tracer(__name__)

GENERATE = "generate"
JUDGE = "judge"


class Critique(BaseModel):
    """The judge's verdict on one generated candidate."""

    approved: bool = Field(
        description="True only if the candidate needs no further revision."
    )
    feedback: str = Field(
        description="If not approved, concrete instructions the generator must follow to improve. Empty if approved."
    )


class CritiqueLoopState(BaseModel):
    """Fields the loop itself owns. Workflow states inherit from this."""

    max_iterations: int = Field(
        gt=0,
        description="Stop after this many generation attempts. Resolved by the caller.",
    )
    feedback: str = Field(
        default="",
        description="The judge's latest feedback, so the generator can revise",
    )
    approved: bool = Field(
        default=False, description="True once the judge approves the candidate"
    )
    iteration: int = Field(
        default=0, description="Number of generation attempts so far"
    )


def should_continue(state: CritiqueLoopState) -> Literal["continue", "stop"]:
    """Decide whether to revise again. Kept name-free so it is testable alone."""
    if state.approved:
        return "stop"
    if state.iteration >= state.max_iterations:
        return "stop"
    return "continue"


def build_critique_loop[StateT: CritiqueLoopState, OutputT: BaseModel](
    *,
    workflow: str,
    state_schema: type[StateT],
    llm: BaseChatModel,
    output_model: type[OutputT],
    output_field: str,
    generate_prompt: Callable[[StateT], str],
    judge_prompt: Callable[[StateT], str],
) -> CompiledStateGraph:
    """Compile a generate/judge/revise graph for one workflow.

    `generate_prompt` receives the whole state, so it can branch on `feedback`
    to decide between a first-pass prompt and a revision prompt.
    """
    generator = llm.with_structured_output(output_model, method="json_schema")
    judger = llm.with_structured_output(Critique, method="json_schema")

    async def generate(state: StateT) -> dict[str, Any]:
        iteration = state.iteration + 1
        revising = bool(state.feedback)
        with tracer.start_as_current_span(f"{workflow}.generate") as span:
            span.set_attribute("workflow.name", workflow)
            span.set_attribute("workflow.iteration", iteration)
            span.set_attribute("workflow.revising", revising)
            logger.info(
                "Generate node started workflow=%s iteration=%s revising=%s",
                workflow,
                iteration,
                revising,
            )
            try:
                candidate = await generator.ainvoke(generate_prompt(state))
            except Exception:
                logger.exception(
                    "Generate node failed workflow=%s iteration=%s",
                    workflow,
                    iteration,
                )
                raise

        logger.debug("Generated candidate: %s", candidate)
        return {output_field: cast(OutputT, candidate), "iteration": iteration}

    async def judge(state: StateT) -> dict[str, Any]:
        with tracer.start_as_current_span(f"{workflow}.judge") as span:
            span.set_attribute("workflow.name", workflow)
            span.set_attribute("workflow.iteration", state.iteration)
            logger.info(
                "Judge node started workflow=%s iteration=%s",
                workflow,
                state.iteration,
            )
            try:
                critique = cast(Critique, await judger.ainvoke(judge_prompt(state)))
            except Exception:
                logger.exception(
                    "Judge node failed workflow=%s iteration=%s",
                    workflow,
                    state.iteration,
                )
                raise
            span.set_attribute("workflow.approved", critique.approved)

        if critique.approved:
            logger.info(
                "Judge approved workflow=%s iteration=%s", workflow, state.iteration
            )
        else:
            logger.warning(
                "Judge rejected workflow=%s iteration=%s feedback=%s",
                workflow,
                state.iteration,
                critique.feedback,
            )
        return {
            "approved": critique.approved,
            "feedback": "" if critique.approved else critique.feedback,
        }

    def route(state: StateT) -> Literal["continue", "stop"]:
        decision = should_continue(state)
        logger.info(
            "Loop %s workflow=%s approved=%s iteration=%s/%s",
            "finished" if decision == "stop" else "continuing",
            workflow,
            state.approved,
            state.iteration,
            state.max_iterations,
        )
        return decision

    logger.info("Building workflow graph workflow=%s", workflow)
    graph = StateGraph(state_schema)
    graph.add_node(GENERATE, generate)
    graph.add_node(JUDGE, judge)
    graph.add_edge(START, GENERATE)
    graph.add_edge(GENERATE, JUDGE)
    graph.add_conditional_edges(JUDGE, route, {"continue": GENERATE, "stop": END})
    return graph.compile()
