from .state import PoetryState

WRITE_PROMPT = """You are an accomplished poet.

Write a short poem, at most 16 lines, about the following topic.
Favour concrete images over abstraction, and avoid cliché and forced rhyme.

Topic:
{topic}
"""

REVISE_PROMPT = """You are an accomplished poet.

Revise your poem using the critic's feedback. Address every point raised, and
keep the lines that already work rather than starting over.

Topic:
{topic}

Your previous draft:
{previous_draft}

Critic's feedback:
{feedback}
"""

CRITIQUE_PROMPT = """You are a demanding poetry critic.

Judge the poem on imagery, rhythm, originality and how well it serves the topic.
Approve it only if you would publish it as it stands. Otherwise set approved to
false and say precisely what to change, naming the lines you mean.

Topic:
{topic}

Poem:
{poem}
"""


def generate_prompt(state: PoetryState) -> str:
    """First pass writes from the topic; later passes revise against feedback."""
    if state.poem is None or not state.feedback:
        return WRITE_PROMPT.format(topic=state.topic)

    return REVISE_PROMPT.format(
        topic=state.topic,
        previous_draft=state.poem.model_dump_json(indent=2),
        feedback=state.feedback,
    )


def judge_prompt(state: PoetryState) -> str:
    if state.poem is None:
        raise ValueError("poem is required before judging")

    return CRITIQUE_PROMPT.format(
        topic=state.topic,
        poem=state.poem.model_dump_json(indent=2),
    )
