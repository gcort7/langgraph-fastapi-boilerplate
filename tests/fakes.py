from typing import Any

from langchain_core.callbacks import CallbackManagerForLLMRun
from langchain_core.language_models import BaseChatModel, LanguageModelInput
from langchain_core.messages import BaseMessage
from langchain_core.outputs import ChatResult
from langchain_core.runnables import Runnable, RunnableLambda
from pydantic import BaseModel, Field


class StubChatModel(BaseChatModel):
    """Chat model that replays scripted structured responses.

    `with_structured_output` is overridden because the real implementation
    negotiates a provider-specific response format that no fake can honour.
    Queues are keyed by schema name so the generator's and the judge's replies
    are scripted independently; the last entry in a queue repeats forever, so a
    test only has to script the responses it cares about.
    """

    queues: dict[str, list[BaseModel]] = Field(default_factory=dict)
    prompts: list[str] = Field(default_factory=list)
    errors: dict[str, Exception] = Field(default_factory=dict)

    @property
    def _llm_type(self) -> str:
        return "stub"

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        raise NotImplementedError("StubChatModel only supports structured output")

    def with_structured_output(
        self,
        schema: dict[str, Any] | type,
        *,
        include_raw: bool = False,
        **kwargs: Any,
    ) -> Runnable[LanguageModelInput, dict[str, Any] | BaseModel]:
        name = schema.__name__ if isinstance(schema, type) else str(schema)

        async def respond(prompt: LanguageModelInput) -> BaseModel:
            self.prompts.append(str(prompt))
            if name in self.errors:
                raise self.errors[name]
            queue = self.queues[name]
            return queue.pop(0) if len(queue) > 1 else queue[0]

        return RunnableLambda(respond)

    def prompts_containing(self, needle: str) -> list[str]:
        return [prompt for prompt in self.prompts if needle in prompt]


class FakeGraph:
    """Stands in for a compiled LangGraph: records input, returns a fixed state."""

    def __init__(self, result: dict[str, Any]) -> None:
        self.result = result
        self.calls: list[dict[str, Any]] = []

    async def ainvoke(
        self, payload: dict[str, Any], config: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        self.calls.append(payload)
        return {**payload, **self.result}
