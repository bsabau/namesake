"""The run starts again on a backup model when the one before it cannot be reached.

Scripted models only: a model "fails" by raising the error PydanticAI raises for an
unreachable or refusing endpoint, or by taking longer than the run allows.
"""

import asyncio
import re

from pydantic_ai.exceptions import ModelHTTPError
from pydantic_ai.models.anthropic import AnthropicModel
from pydantic_ai.models.function import FunctionModel
from pydantic_ai.models.openai import OpenAIChatModel

from app.agent import pipeline
from app.agent.model import ModelChoice, fallback_models
from app.agent.pipeline import run_pipeline
from app.agent.steps import StepLog
from app.config import Settings
from app.store import Store
from tests.qloo_fakes import LOCATION, SEEDS, FakeQloo
from tests.test_agents import DRAFT, PLAN, Script, _tmp_db, full_script


def unreachable(messages, info):
    raise ModelHTTPError(status_code=429, model_name="main", body="plan used up")


def run(roster, main, fallbacks):
    store, log = Store(_tmp_db()), StepLog()
    result = asyncio.run(
        run_pipeline(
            roster.get("dog-02"),
            LOCATION,
            qloo=FakeQloo(full_script()),
            store=store,
            seeds=SEEDS,
            model_factory=(lambda: FunctionModel(main)) if main else None,
            log=log,
            fallbacks=[ModelChoice(lambda f=f: FunctionModel(f), "native") for f in fallbacks],
        )
    )
    return result, store, log


def test_an_unreachable_model_hands_the_run_to_the_backup(roster):
    result, store, log = run(roster, unreachable, [Script([PLAN], [DRAFT])])
    assert store.get_profile(LOCATION.id, "dog").made_by == "agent"
    assert result.draft is not None and result.fallback_reason is None
    notes = [s.text for s in log.steps if "backup model" in s.text]
    # Once for the profile, once for the listing: each run starts again on the backup.
    assert len(notes) == 2


def test_the_backups_are_tried_in_order(roster):
    result, _, log = run(roster, unreachable, [unreachable, Script([PLAN], [DRAFT])])
    assert result.draft is not None
    assert sum("backup model" in s.text for s in log.steps) == 4


def test_with_every_model_unreachable_the_fallbacks_are_the_old_ones(roster):
    result, store, log = run(roster, unreachable, [unreachable])
    assert store.get_profile(LOCATION.id, "dog").made_by != "agent"
    # No model answered, so no draft failed: the reason says so (Flash review, PR #42).
    assert result.draft is None
    assert result.fallback_reason == (
        "Namesake's AI could not be reached, so this is the templated listing."
    )
    # The visitor reads the step log: no exception names in it (22 October walkthrough).
    assert not any(re.search(r"[A-Z]\w+(Error|Exception|Behavior)\b", s.text) for s in log.steps)


def test_a_draft_that_fails_its_checks_is_not_handed_on(roster):
    # The model answered; its listing failed the checks twice. That is the template's
    # case, not the backup's.
    called = []

    def backup(messages, info):
        called.append(True)
        return Script([PLAN], [DRAFT])(messages, info)

    result, _, log = run(roster, Script([PLAN], ["not a listing", "still not"]), [backup])
    assert result.draft is None and "did not pass the checks" in result.fallback_reason
    assert not called and not any("backup model" in s.text for s in log.steps)


def test_a_model_that_takes_too_long_hands_the_run_on(roster, monkeypatch, caplog):
    monkeypatch.setattr(pipeline, "PROFILE_TIMEOUT", 0.05)
    monkeypatch.setattr(pipeline, "LISTING_TIMEOUT", 0.05)

    async def slow(messages, info):
        await asyncio.sleep(1)

    store, log = Store(_tmp_db()), StepLog()
    result = asyncio.run(
        run_pipeline(
            roster.get("dog-02"),
            LOCATION,
            qloo=FakeQloo(full_script()),
            store=store,
            seeds=SEEDS,
            model_factory=lambda: FunctionModel(slow),
            log=log,
            fallbacks=[ModelChoice(lambda: FunctionModel(Script([PLAN], [DRAFT])), "native")],
        )
    )
    assert store.get_profile(LOCATION.id, "dog").made_by == "agent"
    assert sum("backup model" in s.text for s in log.steps) == 2
    # The step says it plainly; the server log names the failure.
    assert "TimeoutError" in caplog.text
    assert result.draft is not None


def test_only_configured_fallbacks_are_used_each_with_its_output_mode(monkeypatch):
    # Settings read the process environment too: clear any fallback set there.
    import os

    for name in [k for k in os.environ if k.startswith("AGENT_FALLBACK_")]:
        monkeypatch.delenv(name)
    settings = Settings(
        _env_file=None,
        agent_fallback_1_model="some-model",  # no key: skipped
        agent_fallback_2_api_key="test-key",
        agent_fallback_2_model="test-model",
        agent_fallback_2_api="anthropic",  # no base URL needed
        agent_fallback_2_output_mode="prompted",
    )
    (only,) = fallback_models(settings)
    assert only.output_mode == "prompted" and isinstance(only.make(), AnthropicModel)
    settings = Settings(
        _env_file=None,
        agent_fallback_1_base_url="https://models.example/v1",
        agent_fallback_1_api_key="test-key",
        agent_fallback_1_model="test-model",
    )
    (only,) = fallback_models(settings)
    assert only.output_mode == "native" and isinstance(only.make(), OpenAIChatModel)
    assert fallback_models(Settings(_env_file=None)) == ()
    # A typo in the API or the output mode skips that fallback instead of misrouting it.
    for typo in ({"agent_fallback_1_api": "chats"}, {"agent_fallback_1_output_mode": "json"}):
        broken = Settings(
            _env_file=None,
            agent_fallback_1_base_url="https://models.example/v1",
            agent_fallback_1_api_key="test-key",
            agent_fallback_1_model="test-model",
            **typo,
        )
        assert fallback_models(broken) == ()


def test_the_example_scripts_echo_a_steps_actor():
    # The final audit, 19 October: the wrapper took no actor, so the classifier's step crashed it.
    from scripts.precompute_examples import echo_log

    log = echo_log()
    log.add("qloo", "Sorted the titles", actor="classifier")
    assert log.steps[-1].actor == "classifier"


def test_no_test_can_reach_a_configured_fallback():
    # A local .env with fallback keys once let four tests call real models; the conftest
    # clears every fallback's key and model, whatever fallbacks the settings grow.
    from app.config import get_settings

    settings = get_settings()
    fields = [f for f in type(settings).model_fields if f.startswith("agent_fallback_")]
    assert fields and all(
        getattr(settings, f) is None for f in fields if f.endswith(("_api_key", "_model"))
    )
    assert fallback_models(settings) == ()


def test_a_typo_in_the_main_models_settings_is_said_out_loud(caplog):
    # Flash review, PR #42: a typo once dropped the main model silently, sending every run
    # to the paid fallback.
    from app.runs import model_factory

    settings = Settings(
        _env_file=None,
        agent_base_url="https://models.example/v1",
        agent_api_key="test-key",
        agent_model="test-model",
        agent_api="response",
    )
    assert model_factory(settings) is None
    assert "AGENT_API must be one of" in caplog.text
    settings.agent_api, settings.agent_output_mode = "chat", "json"
    assert model_factory(settings) is None and "AGENT_OUTPUT_MODE" in caplog.text
    settings.agent_output_mode = "native"
    assert model_factory(settings) is not None


def test_an_empty_api_or_output_mode_line_means_the_default():
    settings = Settings(_env_file=None, agent_api="", agent_output_mode="", agent_fallback_2_api="")
    assert settings.agent_api == "chat" and settings.agent_output_mode == "native"
    assert settings.agent_fallback_2_api == "chat"
