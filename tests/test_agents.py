"""The agents and the pipeline, driven by scripted models and the fake Qloo.

No test reaches a real model or Qloo: FunctionModel plays the model's turns.
"""

import asyncio
import json

from pydantic_ai.messages import ModelResponse, RetryPromptPart, TextPart, ToolCallPart
from pydantic_ai.models.function import FunctionModel

from app.agent.listing_agent import ListingDraft
from app.agent.pipeline import run_pipeline
from app.agent.results import CHECKS_VERSION, ListingResult
from app.agent.steps import StepLog
from app.store import Store
from tests.qloo_fakes import (
    BASELINE,
    CAT_SHOW,
    DOG_SHOW,
    LOCATION,
    SEEDS,
    FakeQloo,
    envelope,
    key,
    standard_script,
    venue_id,
)


def full_script():
    script = standard_script()
    q = LOCATION.query
    script[
        key(
            "rank",
            {"option_type": "tv_show", "options": [DOG_SHOW, CAT_SHOW], "signal_location": q},
        )
    ] = envelope(
        "rank",
        results=[
            {"entity_id": CAT_SHOW, "name": "Example Cat Show", "type": "urn:entity:tv_show"},
            {"entity_id": DOG_SHOW, "name": "Example Dog Show", "type": "urn:entity:tv_show"},
        ],
    )
    return script


def call(name, **args):
    return ModelResponse(parts=[ToolCallPart(tool_name=name, args=args)])


def answer(data):
    return ModelResponse(parts=[TextPart(content=json.dumps(data))])


def retried(messages) -> bool:
    return any(isinstance(p, RetryPromptPart) for m in messages for p in getattr(m, "parts", []))


PLAN = {
    "titles": [
        {"entity_id": DOG_SHOW, "why": "about a dog family", "choice_reason": "the 2018 one"},
        {"entity_id": CAT_SHOW, "why": "about cats"},
    ],
    "venues": [{"entity_id": venue_id(3), "reason": "a community arts centre"}],
    "rejected_venues": [{"entity_id": venue_id(1), "reason": "a large arena"}],
}

DRAFT = {
    "names": [
        {
            "name": "Bingo",
            "source": "pet",
            "entity_id": DOG_SHOW,
            "character": "Bingo",
            "role": "dog",
            "reference_role": "friend",
            "why": "It suits a dog who knows basic commands.",
        },
        {
            "name": "Biscuit",
            "source": "pet",
            "entity_id": CAT_SHOW,
            "character": "Biscuit",
            "role": "cat",
            "reference_role": "friend",
            "why": "It fits her short brindle coat.",
        },
        {
            "name": "Scout",
            "source": "pet",
            "entity_id": DOG_SHOW,
            "character": "Scout",
            "role": "puppy",
            "reference_role": "friend",
            "why": "It suits a big dog.",
        },
    ],
    "bio": [
        {
            "text": "She is strong but gentle and leans on people for attention.",
            "facts": ["temperament"],
        },
        {"text": "She needs an owner comfortable with a big dog.", "facts": ["fact:0"]},
        {"text": "She knows basic commands.", "facts": ["fact:1"]},
    ],
}


class Script:
    """Plays the model: the profile agent's tool calls, then each queued answer."""

    def __init__(self, profile_answers, listing_answers):
        self.profile_answers = list(profile_answers)
        self.listing_answers = list(listing_answers)

    def __call__(self, messages, info):
        tools = {t.name for t in info.function_tools}
        done = {
            p.tool_name
            for m in messages
            for p in getattr(m, "parts", [])
            if getattr(p, "part_kind", "") == "tool-return"
        }
        if "look_up_title" in tools:
            if "look_up_title" not in done:
                return ModelResponse(
                    parts=[
                        ToolCallPart(
                            "look_up_title", {"name": "Example Dog Show", "kind": "tv_show"}
                        ),
                        ToolCallPart(
                            "look_up_title", {"name": "Example Cat Show", "kind": "tv_show"}
                        ),
                    ]
                )
            if "rank_titles" not in done:
                return call("rank_titles", entity_ids=[DOG_SHOW, CAT_SHOW], kind="tv_show")
            if "find_venues" not in done:
                return call("find_venues", entity_ids=[DOG_SHOW, CAT_SHOW])
            return answer(self.profile_answers.pop(0))
        return answer(self.listing_answers.pop(0))


def run(script: Script, roster, *, model=True, animal="dog-02", store=None, qloo=None):
    settings_store = store or Store(_tmp_db())
    log = StepLog()
    result = asyncio.run(
        run_pipeline(
            roster.get(animal),
            LOCATION,
            qloo=qloo or FakeQloo(full_script()),
            store=settings_store,
            seeds=SEEDS,
            model_factory=(lambda: FunctionModel(script)) if model else None,
            log=log,
        )
    )
    return result, settings_store, log


_counter = iter(range(10_000))


def _tmp_db():
    import tempfile
    from pathlib import Path

    return Path(tempfile.mkdtemp()) / f"store{next(_counter)}.sqlite"


def test_full_run_uses_the_agents_choices(roster):
    result, store, log = run(Script([PLAN], [DRAFT]), roster)
    profile = store.get_profile(LOCATION.id, "dog")
    assert profile.made_by == "agent" and profile.order_source == "qloo_rank"
    # Qloo's ranking put the cat show first.
    assert [e.id for e in profile.pet_entities] == [CAT_SHOW, DOG_SHOW]
    dog = next(e for e in profile.pet_entities if e.id == DOG_SHOW)
    assert dog.choice_reason == "the 2018 one" and dog.resolution == "chosen"
    hall = next(v for v in profile.venues if v.entity_id == venue_id(3))
    assert hall.chosen_reason == "a community arts centre" and hall.distinctive
    assert profile.local_tastes[0].name == "Example Puppy Club"
    # The baseline is the area's top shows, leaving out the pet-themed one.
    assert [e.name for e in profile.baselines] == ["Example Drama", "Example Comedy"]
    assert result.draft.names[0].name == "Bingo" and result.fallback_reason is None
    # The hook is built by code from the first name's reference.
    saved = store.get_listing("dog-02", LOCATION.id)
    assert saved.hook == "Named after Bingo, a dog in Example Dog Show."
    assert saved.references[1] == "Biscuit, a cat in Example Cat Show"
    kinds = [s.kind for s in log.steps]
    assert "qloo" in kinds and kinds[-1] == "done"


def test_invented_ids_are_sent_back_once_then_accepted_when_fixed(roster):
    bad = {**PLAN, "venues": [{"entity_id": venue_id(99), "reason": "made up"}]}
    result, store, log = run(Script([bad, PLAN], [DRAFT]), roster)
    assert store.get_profile(LOCATION.id, "dog").made_by == "agent"
    assert any("was not returned by find_venues" in s.text for s in log.steps)


def test_a_screened_venue_cannot_be_picked(roster):
    hookah = {**PLAN, "venues": [{"entity_id": venue_id(2), "reason": "lively"}]}
    _, store, log = run(Script([hookah, hookah], [DRAFT]), roster)
    # Two bad plans: the agent gives up and the fixed seed lookup takes over.
    assert store.get_profile(LOCATION.id, "dog").made_by == "seeds"
    assert any("screened out: hookah" in s.text for s in log.steps)


def test_listing_that_fails_twice_falls_back_to_the_template(roster):
    padded = {
        **DRAFT,
        "bio": [
            {"text": "She came in as a stray and is great with children.", "facts": ["fact:0"]}
        ],
    }
    result, _, log = run(Script([PLAN], [padded, padded]), roster)
    assert result.draft is None and "templated listing" in result.fallback_reason
    messages = " ".join(s.text for s in log.steps)
    assert "leave out backstory" in messages and "'children'" in messages


def test_the_confirmed_checks_are_added_by_code(roster):
    # dog-01 is confirmed good with children and house-trained.
    draft = {
        **DRAFT,
        "bio": [
            {"text": "He is calm and gentle; a slow-walk companion.", "facts": ["temperament"]},
        ],
        "names": [{**n, "why": "It suits a calm dog."} for n in DRAFT["names"]],
    }
    result, _, _ = run(Script([PLAN], [draft]), roster, animal="dog-01")
    texts = [s.text for s in result.bio]
    assert texts[-2:] == ["He is good with children.", "He is house-trained."]


def test_a_contradicting_bio_is_sent_back(roster):
    # Regression (Codex, milestone 3, P1): "aggressive" citing "strong but gentle" passed.
    bad = {
        **DRAFT,
        "bio": [{"text": "She is aggressive.", "facts": ["temperament"]}, *DRAFT["bio"][1:]],
    }
    result, _, log = run(Script([PLAN], [bad, DRAFT]), roster)
    assert result.draft is not None
    assert any("'aggressive'" in s.text for s in log.steps)


def test_a_name_used_at_the_shelter_is_refused(roster):
    store = Store(_tmp_db())
    # Another dog at the same shelter is already called Bingo.
    store.put_listing(
        ListingResult(
            animal_id="dog-03",
            location_id=LOCATION.id,
            draft=ListingDraft.model_validate(DRAFT),
            checks_version=CHECKS_VERSION,
        )
    )
    rubble = {**DRAFT["names"][2], "name": "Rubble", "character": "Rubble"}
    renamed = {**DRAFT, "names": [DRAFT["names"][1], DRAFT["names"][2], rubble]}
    second, _, log = run(Script([PLAN], [DRAFT, renamed]), roster, store=store)
    assert any("already used at this shelter" in s.text for s in log.steps)
    assert second.draft.names[0].name == "Biscuit"


def test_bully_type_dog_gets_only_pet_title_names(roster):
    local = {
        **DRAFT,
        "names": [{**DRAFT["names"][0], "source": "local", "entity_id": BASELINE}]
        + DRAFT["names"][1:],
    }
    result, _, log = run(Script([PLAN], [local, DRAFT]), roster)
    assert result.draft is not None
    assert any(
        "only names drawn from the pet-themed or lookalike titles" in s.text for s in log.steps
    )


def test_without_a_model_everything_falls_back_and_says_so(roster):
    result, store, log = run(Script([], []), roster, model=False)
    assert store.get_profile(LOCATION.id, "dog").made_by == "seeds"
    assert result.draft is None and "No model is configured" in result.fallback_reason


def test_a_saved_profile_is_reused_without_qloo(roster):
    first, store, _ = run(Script([PLAN], [DRAFT]), roster)
    qloo = FakeQloo({})
    second, _, log = run(Script([], [DRAFT]), roster, store=store, qloo=qloo)
    assert second.draft is not None and qloo.calls == []
    assert any("saved profile" in s.text for s in log.steps)


def test_the_step_log_replays_and_then_follows():
    async def go():
        log = StepLog(asyncio.get_running_loop())
        log.add("start", "one")
        seen = []

        async def reader():
            async for step in log.follow():
                seen.append(step.text)

        task = asyncio.create_task(reader())
        await asyncio.sleep(0)
        log.add("qloo", "two")
        log.finish()
        await asyncio.wait_for(task, 1)
        return seen

    assert asyncio.run(go()) == ["one", "two"]


def test_a_step_added_from_a_thread_just_before_finish_is_streamed():
    # Regression (Codex, milestone 3): a reader that pauses between steps, as a
    # streaming response does, missed a step added and finished meanwhile.
    import threading

    async def go():
        log = StepLog(asyncio.get_running_loop())
        log.add("start", "first")
        got_first = asyncio.Event()
        seen = []

        async def reader():
            async for step in log.follow():
                seen.append(step.text)
                got_first.set()
                await asyncio.sleep(0.01)

        task = asyncio.create_task(reader())
        await got_first.wait()

        def worker():
            log.add("qloo", "final Qloo step")
            log.finish()

        thread = threading.Thread(target=worker)
        thread.start()
        thread.join()
        await asyncio.wait_for(task, 1)
        return seen

    assert asyncio.run(go()) == ["first", "final Qloo step"]


def test_following_a_finished_log_replays_everything():
    async def go():
        log = StepLog(asyncio.get_running_loop())
        log.add("start", "one")
        log.add("done", "two")
        log.finish()
        return [s.text async for s in log.follow()]

    assert asyncio.run(go()) == ["one", "two"]


def test_a_villain_name_is_sent_back(roster):
    # Regression (Codex, milestone 3): "Scar" passed the name screen.
    villain = {
        **DRAFT,
        "names": [{**DRAFT["names"][0], "name": "Scar", "character": "Scar"}] + DRAFT["names"][1:],
    }
    result, _, log = run(Script([PLAN], [villain, DRAFT]), roster)
    assert result.draft.names[0].name == "Bingo"
    assert any("villain" in s.text for s in log.steps)


def test_a_bio_sentence_that_invents_is_sent_back(roster):
    # Regression (Codex, milestone 3): a sentence citing a real fact could say anything.
    invented = {
        **DRAFT,
        "bio": [
            {"text": "She loves swimming at the beach and chasing balls.", "facts": ["fact:1"]}
        ],
    }
    result, _, log = run(Script([PLAN], [invented, invented]), roster)
    assert result.draft is None
    assert any("says things its facts do not" in s.text for s in log.steps)


def test_a_degraded_ranking_is_not_used(roster):
    script = full_script()
    q = LOCATION.query
    k = key(
        "rank", {"option_type": "tv_show", "options": [DOG_SHOW, CAT_SHOW], "signal_location": q}
    )
    script[k] = envelope("rank", "degraded", results=script[k].results, warnings=["no location"])
    _, store, log = run(Script([PLAN], [DRAFT]), roster, qloo=FakeQloo(script))
    profile = store.get_profile(LOCATION.id, "dog")
    assert profile.order_source == "agent" and profile.ranked == []
    assert any("ranking was degraded" in s.text for s in log.steps)


def test_venues_from_an_earlier_search_cannot_be_picked():
    from types import SimpleNamespace

    import pytest
    from pydantic_ai import ModelRetry

    from app.agent.profile_agent import ProfileDeps, ProfilePlan, check_plan
    from app.profile import Entity

    deps = ProfileDeps(qloo=None, location=LOCATION, species="dog", log=StepLog())
    deps.titles_seen[DOG_SHOW] = Entity(id=DOG_SHOW, name="Example Dog Show", type="tv_show")
    deps.venues_seen[venue_id(3)] = {"name": "Community Hall", "excluded": None}
    deps.venue_signals = [DOG_SHOW]
    deps.latest_venues = {venue_id(4)}
    plan = ProfilePlan.model_validate(
        {
            "titles": [{"entity_id": DOG_SHOW, "why": "dogs"}],
            "venues": [{"entity_id": venue_id(3), "reason": "a hall"}],
        }
    )
    with pytest.raises(ModelRetry, match="earlier search"):
        check_plan(SimpleNamespace(deps=deps), plan)


def test_two_runs_at_once_build_the_profile_once(roster, monkeypatch):
    # Regression (Codex, milestone 3): concurrent requests both built and saved the profile.
    import app.agent.pipeline as pipeline
    from app.profile import LocationProfile

    builds = []

    async def slow_build(animal, location, **kwargs):
        builds.append(animal.id)
        await asyncio.sleep(0.05)
        profile = LocationProfile(location_id=location.id, species=animal.species)
        kwargs["store"].put_profile(profile)
        return profile

    monkeypatch.setattr(pipeline, "_build_profile", slow_build)
    store = Store(_tmp_db())

    async def go():
        args = dict(
            qloo=FakeQloo({}), store=store, seeds=SEEDS, model_factory=None, output_mode="native"
        )
        await asyncio.gather(
            pipeline.get_profile(roster.get("dog-02"), LOCATION, log=StepLog(), **args),
            pipeline.get_profile(roster.get("dog-01"), LOCATION, log=StepLog(), **args),
        )

    asyncio.run(go())
    assert len(builds) == 1


def test_an_old_saved_draft_is_rerun_not_shown(roster):
    # Regression (Codex, milestone 3): drafts saved before the current checks were shown.
    store = Store(_tmp_db())
    old = ListingResult(
        animal_id="dog-02", location_id=LOCATION.id, draft=ListingDraft.model_validate(DRAFT)
    )
    store.put_listing(old)
    assert store.get_listing("dog-02", LOCATION.id) is None


def test_a_dropped_negation_or_a_half_cited_fact_is_sent_back(roster):
    # Regression (Codex, milestone 3, P1): "not suited" without "not" passed.
    from app.agent.checks import check_bio

    dog = roster.get("dog-03")
    temperament = (f"He is {dog.temperament}.", ["temperament"])
    tricks = ("He learns tricks in minutes.", ["fact:0"])
    dropped = ("He is suited to being left alone all day.", ["fact:1"])
    assert any("drops the 'not'" in p for p in check_bio(dog, [temperament, tricks, dropped]))
    half = ("He is very active.", ["temperament", "fact:0"])
    problems = check_bio(dog, [half, ("He is not suited to being left alone all day.", ["fact:1"])])
    assert any("leaves out" in p and "fact:0" in p for p in problems)


def test_the_hook_carries_no_free_text_from_the_model():
    # Regression (Codex, milestone 3): a free-text reference put "she enjoys cuddles"
    # into the hook. The model now gives only a character's name and a fixed role.
    from app.agent.checks import check_character, reference_text

    assert any(
        "up to four words" in p for p in check_character("Bingo and she enjoys cuddles", "dog")
    )
    assert any("temperament" in p for p in check_character("Playful Bingo", "dog"))
    assert reference_text("Bingo", "puppy", "Bluey") == "Bingo, a puppy in Bluey"
    assert reference_text("Bluey", "title", "Bluey") == "Bluey"


def test_appended_check_sentences_count_toward_the_word_limit(roster):
    from app.agent.checks import check_bio

    dog = roster.get("dog-02")
    words = "She knows basic commands. " * 30  # 120 words
    bio = [
        ("She is strong but gentle; leans on people for attention.", ["temperament"]),
        ("She needs an owner comfortable with a big dog.", ["fact:0"]),
        (words.strip(), ["fact:1"]),
    ]
    assert not any("150" in p for p in check_bio(dog, bio))
    assert any("150" in p for p in check_bio(dog, bio, extra_words=20))


def test_concurrent_listings_at_one_shelter_get_different_names(roster):
    # Regression (Codex, milestone 3): two runs both read "no names taken" and saved Bingo.
    store = Store(_tmp_db())
    twin = roster.get("dog-02").model_copy(update={"id": "dog-02-twin"})
    rubble = {**DRAFT["names"][2], "name": "Rubble", "character": "Rubble"}
    renamed = {**DRAFT, "names": [DRAFT["names"][1], DRAFT["names"][2], rubble]}

    async def go():
        qloo = FakeQloo(full_script())

        def one(animal, answers):
            return run_pipeline(
                animal,
                LOCATION,
                qloo=qloo,
                store=store,
                seeds=SEEDS,
                model_factory=lambda: FunctionModel(Script([PLAN], answers)),
                log=StepLog(),
            )

        return await asyncio.gather(
            one(roster.get("dog-02"), [DRAFT, renamed]), one(twin, [DRAFT, renamed])
        )

    first, second = asyncio.run(go())
    assert {first.draft.names[0].name, second.draft.names[0].name} == {"Bingo", "Biscuit"}


def test_a_badge_reports_qloos_position_even_for_a_dropped_title(roster):
    # Regression (Codex, milestone 3): keeping only Qloo's 2nd title made it "1st of 1".
    from app.views.build import name_badge

    dog_only = {**PLAN, "titles": [PLAN["titles"][0]]}
    rubble = {**DRAFT["names"][2], "name": "Rubble", "character": "Rubble"}
    dog_names = {**DRAFT, "names": [DRAFT["names"][0], DRAFT["names"][2], rubble]}
    _, store, _ = run(Script([dog_only], [dog_names]), roster)
    profile = store.get_profile(LOCATION.id, "dog")
    assert profile.ranked == [CAT_SHOW, DOG_SHOW]
    assert name_badge("pet", DOG_SHOW, profile) == (
        "Pet-themed title, ranked 2nd of 2 here by Qloo"
    )


def test_find_venues_tells_the_agent_where_each_place_ranks():
    from types import SimpleNamespace

    from app.agent.profile_agent import INSTRUCTIONS, ProfileDeps, find_venues
    from app.profile import Entity

    deps = ProfileDeps(
        qloo=FakeQloo(full_script()), location=LOCATION, species="dog", log=StepLog()
    )
    for i, name in [(DOG_SHOW, "Example Dog Show"), (CAT_SHOW, "Example Cat Show")]:
        deps.titles_seen[i] = Entity(id=i, name=name, type="urn:entity:tv_show")
    out = find_venues(SimpleNamespace(deps=deps), [DOG_SHOW, CAT_SHOW])
    venues = out["venues"]
    assert [v["rank"] for v in venues] == list(range(1, len(venues) + 1))
    assert {v["out_of"] for v in venues} == {len(venues)}
    assert venues[0]["position"] == "top" and venues[-1]["position"] != "top"
    # The instructions name the field the agent should weigh.
    assert 'position "top"' in INSTRUCTIONS
