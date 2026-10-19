"""The agent's models, built from the AGENT_* settings. Never named in code.

The main model comes from the four AGENT_* settings; up to two fallbacks from the
AGENT_FALLBACK_1_* and AGENT_FALLBACK_2_* ones. A run that fails to reach a model
starts again on the next (app/agent/pipeline.py).
"""

import uuid
from collections.abc import Callable
from dataclasses import dataclass

from anthropic import AsyncAnthropic
from openai import AsyncOpenAI
from pydantic import SecretStr
from pydantic_ai.models import Model
from pydantic_ai.models.anthropic import AnthropicModel
from pydantic_ai.models.openai import OpenAIChatModel, OpenAIResponsesModel
from pydantic_ai.providers.anthropic import AnthropicProvider
from pydantic_ai.providers.openai import OpenAIProvider

from app.config import Settings

USER_AGENT = "namesake/0.1"
# Seconds a single model request may take, and retries of a failed one. Without a
# timeout a hung endpoint holds a run for the SDK's ten minutes per try, and the run
# never fails over to the next model.
REQUEST_TIMEOUT = 90.0
REQUEST_RETRIES = 1
APIS = ("chat", "responses", "anthropic")
OUTPUT_MODES = ("native", "prompted", "tool")


class ModelNotConfigured(RuntimeError):
    """One of AGENT_BASE_URL, AGENT_API_KEY or AGENT_MODEL is missing."""


@dataclass(frozen=True)
class ModelChoice:
    """One model a run may use: how to build it, and how it returns structured output."""

    make: Callable[[], Model]
    output_mode: str
    label: str = "main"


def _build(
    base_url: str | None,
    api_key: SecretStr | None,
    model: str | None,
    api: str,
    session_id: str | None,
) -> Model:
    """One model from one set of settings. `api` is "chat", "responses" or "anthropic"
    (Anthropic's own API, through its SDK; no base URL needed)."""
    if not (api_key and model and (base_url or api == "anthropic")):
        raise ModelNotConfigured("set the base URL, API key and model")
    if api not in APIS:
        # A typo would otherwise send the request in the wrong format, and the refusal
        # would quietly hand every run to the next model.
        raise ModelNotConfigured(f"the API must be one of {', '.join(APIS)}")
    if api == "anthropic":
        client = AsyncAnthropic(
            api_key=api_key.get_secret_value(),
            base_url=base_url or None,
            timeout=REQUEST_TIMEOUT,
            max_retries=REQUEST_RETRIES,
        )
        return AnthropicModel(model, provider=AnthropicProvider(anthropic_client=client))
    client = AsyncOpenAI(
        base_url=base_url,
        api_key=api_key.get_secret_value(),
        timeout=REQUEST_TIMEOUT,
        max_retries=REQUEST_RETRIES,
        # OpenCode Go asks direct API callers for a stable session per conversation and
        # their own user agent; other OpenAI-compatible endpoints ignore both headers.
        default_headers={
            "x-opencode-session": session_id or uuid.uuid4().hex,
            "User-Agent": USER_AGENT,
        },
    )
    provider = OpenAIProvider(openai_client=client)
    model_cls = OpenAIResponsesModel if api == "responses" else OpenAIChatModel
    return model_cls(model, provider=provider)


def build_model(settings: Settings, session_id: str | None = None) -> Model:
    """The main model, for one agent run."""
    if not (settings.agent_base_url or settings.agent_api == "anthropic"):
        raise ModelNotConfigured("set AGENT_BASE_URL, AGENT_API_KEY and AGENT_MODEL")
    try:
        return _build(
            settings.agent_base_url,
            settings.agent_api_key,
            settings.agent_model,
            settings.agent_api,
            session_id,
        )
    except ModelNotConfigured:
        raise ModelNotConfigured("set AGENT_BASE_URL, AGENT_API_KEY and AGENT_MODEL") from None


def fallback_models(settings: Settings) -> tuple[ModelChoice, ...]:
    """The configured fallbacks, in order. A fallback with no key or no model is skipped."""
    choices = []
    for n in (1, 2):
        base_url = getattr(settings, f"agent_fallback_{n}_base_url")
        api_key = getattr(settings, f"agent_fallback_{n}_api_key")
        model = getattr(settings, f"agent_fallback_{n}_model")
        api = getattr(settings, f"agent_fallback_{n}_api")
        mode = getattr(settings, f"agent_fallback_{n}_output_mode")
        try:
            _build(base_url, api_key, model, api, None)
        except ModelNotConfigured:
            continue
        if mode not in OUTPUT_MODES:
            continue

        def make(base_url=base_url, api_key=api_key, model=model, api=api) -> Model:
            return _build(base_url, api_key, model, api, uuid.uuid4().hex)

        choices.append(ModelChoice(make, mode, label=str(n)))
    return tuple(choices)
