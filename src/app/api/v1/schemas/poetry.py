from pydantic import BaseModel, Field

from app.orchestrator.workflows.poetry import Poem, PoetryState

MAX_TOPIC_CHARS = 2_000


class PoemRequest(BaseModel):
    topic: str = Field(
        min_length=1,
        max_length=MAX_TOPIC_CHARS,
        description="What the poem should be about",
    )
    max_iterations: int | None = Field(
        default=None,
        gt=0,
        le=10,
        description="Optional cap on poet/critic rounds. Uses settings when omitted.",
    )


class PoemResponse(BaseModel):
    approved: bool = Field(description="True if the critic approved the final draft.")
    iteration: int = Field(description="How many drafts the poet wrote.")
    critique: str = Field(
        description="The critic's outstanding feedback. Empty when approved."
    )
    poem: Poem | None = None

    @classmethod
    def from_state(cls, state: PoetryState) -> "PoemResponse":
        return cls(
            approved=state.approved,
            iteration=state.iteration,
            critique=state.feedback,
            poem=state.poem,
        )
