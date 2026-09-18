import logging
from functools import lru_cache

from langchain_core.language_models import BaseChatModel
from langchain_openai import ChatOpenAI

from app.config import get_settings

logger = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def default_llm() -> BaseChatModel:
    """The process-wide chat model, pointed at the LiteLLM proxy.

    Cached because each client owns an HTTP connection pool. Graph builders
    accept a model explicitly, so tests never reach this function.
    """
    settings = get_settings()
    logger.info(
        "Creating chat model model=%s base_url=%s",
        settings.llm_model,
        settings.llm_base_url,
    )
    return ChatOpenAI(
        model=settings.llm_model,
        base_url=settings.llm_base_url,
        api_key=settings.llm_api_key,
        temperature=settings.llm_temperature,
        timeout=settings.llm_timeout_seconds,
        max_retries=settings.llm_max_retries,
    )
