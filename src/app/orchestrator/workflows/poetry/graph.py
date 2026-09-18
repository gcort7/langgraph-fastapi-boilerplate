from langchain_core.language_models import BaseChatModel
from langgraph.graph.state import CompiledStateGraph

from app.orchestrator.critique_loop import build_critique_loop
from app.orchestrator.llm import default_llm

from .prompts import generate_prompt, judge_prompt
from .state import Poem, PoetryState

POETRY = "poetry"


def build_poetry_graph(llm: BaseChatModel | None = None) -> CompiledStateGraph:
    """Poet writes, critic judges, poet revises until approved or out of tries.

    `llm` is injectable so tests can drive the whole loop without a network.
    """
    return build_critique_loop(
        workflow=POETRY,
        state_schema=PoetryState,
        llm=llm or default_llm(),
        output_model=Poem,
        output_field="poem",
        generate_prompt=generate_prompt,
        judge_prompt=judge_prompt,
    )
