"""The agent's model, built from the four AGENT_* settings. Never named in code."""

import uuid

from openai import AsyncOpenAI
from pydantic_ai.models import Model
from pydantic_ai.models.openai import OpenAIChatModel, OpenAIResponsesModel
from pydantic_ai.providers.openai import OpenAIProvider

from app.config import Settings

USER_AGENT = "namesake/0.1"


class ModelNotConfigured(RuntimeError):
    """One of AGENT_BASE_URL, AGENT_API_KEY or AGENT_MODEL is missing."""


def build_model(settings: Settings, session_id: str | None = None) -> Model:
    """A model for one agent run.

    `session_id` is sent as `x-opencode-session`: OpenCode Go asks direct API
    callers for a stable session per conversation and their own user agent.
    Other OpenAI-compatible endpoints ignore both headers.
    """
    if not (settings.agent_base_url and settings.agent_api_key and settings.agent_model):
        raise ModelNotConfigured("set AGENT_BASE_URL, AGENT_API_KEY and AGENT_MODEL")
    client = AsyncOpenAI(
        base_url=settings.agent_base_url,
        api_key=settings.agent_api_key.get_secret_value(),
        default_headers={
            "x-opencode-session": session_id or uuid.uuid4().hex,
            "User-Agent": USER_AGENT,
        },
    )
    provider = OpenAIProvider(openai_client=client)
    model_cls = OpenAIResponsesModel if settings.agent_api == "responses" else OpenAIChatModel
    return model_cls(settings.agent_model, provider=provider)
