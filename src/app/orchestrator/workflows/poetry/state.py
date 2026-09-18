from pydantic import BaseModel, Field

from app.orchestrator.critique_loop import CritiqueLoopState


class Poem(BaseModel):
    """One candidate poem produced by the poet."""

    title: str = Field(description="A short title for the poem.")
    body: str = Field(description="The poem itself, with line breaks preserved.")


class PoetryState(CritiqueLoopState):
    """Workflow state: the request plus whatever the loop has produced so far.

    `max_iterations`, `feedback`, `approved` and `iteration` come from
    `CritiqueLoopState` and are managed by the loop.
    """

    topic: str = Field(description="What the poem should be about")
    poem: Poem | None = None
