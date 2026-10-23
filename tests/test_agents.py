"""The agents and the pipeline, driven by scripted models and the fake Qloo.

No test reaches a real model or Qloo: FunctionModel plays the model's turns.
"""

import asyncio
import json

import pytest
from pydantic_ai.messages import ModelResponse, RetryPromptPart, TextPart, ToolCallPart
from pydantic_ai.models.function import FunctionModel

from app.agent.listing_agent import ListingDraft, Lookalike, facts_block
from app.agent.pipeline import kept_names, run_pipeline
from app.agent.results import CHECKS_VERSION, ListingResult
from app.agent.steps import StepLog
from app.profile import Entity
from app.store import Store
from tests.qloo_fakes import (
    BASELINE,
    CAT_SHOW,
    DOG_SHOW,
    LOCAL_PET_SHOW,
    LOCATION,
    PET_VENUES,
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
            "why": "A short name, easy to say.",
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
            "why": "It suits her broad head.",
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

    def __init__(self, profile_answers, listing_answers, venue_titles=(DOG_SHOW, CAT_SHOW)):
        self.profile_answers = list(profile_answers)
        self.listing_answers = list(listing_answers)
        self.venue_titles = list(venue_titles)

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
                return call("find_venues", entity_ids=self.venue_titles)
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
    # The calls Namesake's AI chose are credited to it, and so are its answers.
    by_ai = [s.text for s in log.steps if s.actor == "ai"]
    assert any(t.startswith("Namesake's AI asks Qloo to rank") for t in by_ai)
    assert any(t.startswith("Namesake's AI asks Qloo for places near") for t in by_ai)
    assert any(t.startswith("Namesake's AI answered:") for t in by_ai)
    # Code's fixed calls stay Qloo's: the baseline and what the area tends to watch.
    fixed = [s for s in log.steps if s.text.startswith(("Baseline:", "Looking up what people"))]
    assert len(fixed) == 2 and all(s.actor == "qloo" for s in fixed)


def test_invented_ids_are_sent_back_once_then_accepted_when_fixed(roster):
    bad = {**PLAN, "venues": [{"entity_id": venue_id(99), "reason": "made up"}]}
    result, store, log = run(Script([bad, PLAN], [DRAFT]), roster)
    assert store.get_profile(LOCATION.id, "dog").made_by == "agent"
    # The log words it plainly (tool names reworded); the model got the original.
    assert any("was not among the places Qloo returned" in s.text for s in log.steps)
    sent_back = next(s.text for s in log.steps if "was not among the places" in s.text)
    assert sent_back.startswith("Code sent the answer back to Namesake's AI, asking: “")
    assert "find_venues" not in sent_back and venue_id(99) not in sent_back


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
    # The visitor reads the step log: no exception names in it.
    assert "UnexpectedModelBehavior" not in messages
    assert "did not finish a listing that passes the checks" in messages


def test_the_confirmed_checks_are_added_by_code(roster):
    # dog-01 is confirmed good with children and house-trained.
    draft = {
        **DRAFT,
        "bio": [
            {"text": "He is calm and gentle; a slow-walk companion.", "facts": ["temperament"]},
        ],
        # dog-01 is not bully-type, so the area's other titles are usable: one name each.
        "names": [{**n, "why": "It suits his yellow coat."} for n in DRAFT["names"][:2]]
        + [{**DRAFT["names"][2], "source": "local", "entity_id": LOCAL_PET_SHOW,
            "why": "It suits his yellow coat."}],
    }  # fmt: skip
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
    # The log prints the model's list as words: "… not in its facts: aggressive".
    assert any(s.kind == "check" and "aggressive" in s.text for s in log.steps)


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


def test_the_name_screen_reads_the_title_qloo_returned():
    from app.agent.listing_agent import NameOption, screen_names
    from app.profile import Entity

    talk = Entity(
        id=BASELINE,
        name="Example Talk",
        type="urn:entity:tv_show",
        description="A talk show with Bingo, the studio dog.",
    )
    host = NameOption(
        **{**DRAFT["names"][0], "source": "local", "entity_id": BASELINE, "role": "character"}
    )
    assert any("about real people" in p for p in screen_names([host], {BASELINE: talk}, False))
    dog = NameOption(**{**DRAFT["names"][0], "source": "local", "entity_id": BASELINE})
    assert screen_names([dog], {BASELINE: talk}, False) == []


def test_without_a_model_everything_falls_back_and_says_so(roster):
    result, store, log = run(Script([], []), roster, model=False)
    assert store.get_profile(LOCATION.id, "dog").made_by == "seeds"
    assert result.draft is None and "No model is configured" in result.fallback_reason


def test_a_saved_profile_is_reused_without_qloo(roster):
    first, store, _ = run(Script([PLAN], [DRAFT]), roster)
    qloo = FakeQloo({})
    second, _, log = run(Script([], [DRAFT]), roster, store=store, qloo=qloo)
    # Only the listing's own call, who tends to like its titles (decision 31).
    assert second.draft is not None
    titles = dict.fromkeys(o["entity_id"] for o in DRAFT["names"])
    assert qloo.calls == [("audience_demographics", {"entity": i}) for i in titles]
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
    assert reference_text("Bingo", "puppy", "Bluey") == "Bingo, a dog in Bluey"
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
    # The venues are asked for the titles the plan keeps (check_plan).
    venues = key(
        "recommend",
        {"target_type": "place", "signals": [DOG_SHOW], "filter_location": LOCATION.query,
         "limit": 15},
    )  # fmt: skip
    qloo = FakeQloo({**full_script(), venues: envelope("recommend", results=PET_VENUES)})
    _, store, _ = run(Script([dog_only], [dog_names], [DOG_SHOW]), roster, qloo=qloo)
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
    # The instructions name the fields the agent should weigh, in order: suitability, then
    # standing out among top and middle places, then rank; the bottom third last.
    flat = " ".join(INSTRUCTIONS.split())
    assert 'with position "top" or "middle", pick those marked stands_out first' in flat
    assert "Then the rest by rank" in flat
    assert 'position "bottom" only when no higher one is suitable' in flat


def test_two_names_from_one_title_are_sent_back_while_another_is_usable(roster):
    # Decided 18 October: dog-01 may name from the area's other titles, so a repeat is
    # sent back; the fix takes the third name from another title.
    names = [{**n, "why": "It suits his yellow coat."} for n in DRAFT["names"]]
    bio = [{"text": "He is calm and gentle; a slow-walk companion.", "facts": ["temperament"]}]
    repeat = {**DRAFT, "names": names, "bio": bio}
    fixed = {**repeat, "names": [*names[:2], {**names[2], "source": "local",
                                             "entity_id": LOCAL_PET_SHOW}]}  # fmt: skip
    result, _, log = run(Script([PLAN], [repeat, fixed]), roster, animal="dog-01")
    assert result.draft is not None
    assert any("come from one title" in s.text for s in log.steps)
    assert len({o.entity_id for o in result.draft.names}) == 3


def test_the_instructions_ask_for_separate_sentences_and_look_only_reasons():
    from app.agent.listing_agent import INSTRUCTIONS
    from app.agent.profile_agent import INSTRUCTIONS as PROFILE

    assert "what the animal needs from an adopter its own sentence" in INSTRUCTIONS
    assert "Never its temperament or behaviour" in INSTRUCTIONS
    assert "Take each option from a different title" in INSTRUCTIONS
    assert "why it suits an adoption event or a flyer" in PROFILE
    assert "claim no feature it does not mention" in PROFILE


def test_a_repeat_is_allowed_once_every_pet_title_is_used(roster):
    # dog-02 is bully-type: only the two pet titles count, and DRAFT uses both.
    result, _, log = run(Script([PLAN], [DRAFT]), roster)
    assert result.draft is not None
    assert not any("come from one title" in s.text for s in log.steps)


def test_repeats_count_only_open_area_titles():
    from app.agent.listing_agent import NameOption, repeated_titles
    from app.profile import Entity

    def title(i, name, description="A made-up show."):
        return Entity(id=f"00000000-0000-4000-8000-00000000009{i}", name=name,
                      type="urn:entity:tv_show", description=description)  # fmt: skip

    pet, other = title(1, "Example Dog Show"), title(2, "Example Cat Show")
    names = [NameOption(**{**n, "entity_id": pet.id}) for n in DRAFT["names"][:2]]
    names.append(NameOption(**{**DRAFT["names"][2], "entity_id": other.id}))
    offered = {pet.id: (pet, "pet"), other.id: (other, "pet")}
    assert repeated_titles(names, offered, strict=False) == []
    # An identity-coded or real-people local title, or a lookalike, gives no way out.
    for extra, source in (
        (title(3, "Example Choir", "A made-up show about a choir that sings of Christ."), "local"),
        (title(4, "Example Talk", "A made-up talk show with celebrity guests."), "local"),
        (title(5, "Example Dog Film"), "lookalike"),
    ):
        assert repeated_titles(names, {**offered, extra.id: (extra, source)}, strict=False) == []
    open_local = title(6, "Example Puppy Club")
    problems = repeated_titles(names, {**offered, open_local.id: (open_local, "local")}, False)
    assert problems and "such as 'Example Puppy Club'" in problems[0]
    assert repeated_titles(names, {**offered, open_local.id: (open_local, "local")}, True) == []


def test_a_litter_named_as_a_set_may_take_every_name_from_one_title(roster):
    from types import SimpleNamespace

    from pydantic_ai import ModelRetry

    from app.agent.listing_agent import ListingDeps, check_draft
    from app.agent.steps import StepLog
    from app.profile import Entity

    def show(entity_id, name):
        return Entity(id=entity_id, name=name, type="urn:entity:tv_show", description="Made up.")

    titles = {DOG_SHOW: (show(DOG_SHOW, "Example Dog Show"), "pet"),
              LOCAL_PET_SHOW: (show(LOCAL_PET_SHOW, "Example Puppy Club"), "local")}  # fmt: skip
    names = [{**n, "entity_id": DOG_SHOW, "why": "It suits a grey tabby."} for n in DRAFT["names"]]
    draft = ListingDraft.model_validate({**DRAFT, "names": names})
    for litter in ({"first_of_litter": True}, {"litter_title": "Example Dog Show"}, {}):
        deps = ListingDeps(animal=roster.get("kitten-01"), titles=titles, log=StepLog(), **litter)
        problems = []
        try:
            check_draft(SimpleNamespace(deps=deps), draft)
        except ModelRetry as retry:
            problems = [str(retry)]
        repeated = any("come from one title" in p for p in problems)
        assert repeated == (not litter)  # the same draft for a lone kitten is sent back


def test_the_agent_is_shown_every_recorded_fact(roster):
    # Hiding one would send every draft back: the 22 October walkthrough's failure.
    pet = roster.get("dog-02").model_copy(
        update={"facts": ["knows basic commands", "came in as a stray"]}
    )
    block = facts_block(pet)
    assert '- fact:0: "knows basic commands"' in block
    assert '- fact:1: "came in as a stray"' in block


# A refine keeps the names unless it asks for other ones (decision 37).

REORDERED = {**DRAFT, "names": [DRAFT["names"][1], DRAFT["names"][2], DRAFT["names"][0]]}
WITHOUT_BINGO = {
    **DRAFT,
    "names": [
        DRAFT["names"][1],
        DRAFT["names"][2],
        {**DRAFT["names"][0], "name": "Rusty", "character": "Rusty"},
    ],
}


class Seen(Script):
    """A Script that keeps the listing agent's instructions, as the model saw them."""

    instructions: list[str]

    def __call__(self, messages, info):
        if "look_up_title" not in {t.name for t in info.function_tools}:
            self.__dict__.setdefault("instructions", []).append(
                " ".join(getattr(m, "instructions", None) or "" for m in messages)
            )
        return super().__call__(messages, info)


def refine(roster, previous, request, answers, also_taken=frozenset()):
    log, script = StepLog(), Seen([PLAN], answers)
    result = asyncio.run(
        run_pipeline(
            roster.get("dog-02"),
            LOCATION,
            qloo=FakeQloo(full_script()),
            store=Store(_tmp_db()),
            seeds=SEEDS,
            model_factory=lambda: FunctionModel(script),
            log=log,
            request=request,
            previous=previous,
            also_taken=also_taken,
        )
    )
    return result, log, script


def test_a_refine_shows_the_agent_the_names_to_keep(roster):
    first, _, _ = run(Script([PLAN], [DRAFT]), roster)
    result, log, script = refine(roster, first, "shorter sentences, a bit warmer", [DRAFT])
    assert "Unless the request asks for" in script.instructions[0]
    assert '"name":"Bingo"' in script.instructions[0]
    assert result.names_kept and any(s.text == "The names are kept" for s in log.steps)


def test_names_the_agent_changes_are_said_to_be_changed(roster):
    first, _, _ = run(Script([PLAN], [DRAFT]), roster)
    result, log, _ = refine(roster, first, "other names please", [WITHOUT_BINGO])
    assert result.names_kept is False and result.draft.names[2].name == "Rusty"
    assert any(s.text == "Namesake's AI changed the names" for s in log.steps)
    # The same names in another order are the names kept.
    result, _, _ = refine(roster, first, "warmer", [REORDERED])
    assert result.names_kept
    # A name whose title left the area's lists cannot be kept: the names changed.
    gone = first.draft.names[2].model_copy(
        update={"entity_id": "00000000-0000-4000-8000-0000000000aa"}
    )
    left = first.model_copy(
        update={"draft": first.draft.model_copy(update={"names": [*first.draft.names[:2], gone]})}
    )
    result, _, script = refine(roster, left, "warmer", [DRAFT])
    assert result.names_kept is False and "Unless the request asks" not in script.instructions[0]
    # A refine of a listing with no names has none to keep.
    result, _, _ = refine(roster, first.model_copy(update={"draft": None}), "warmer", [DRAFT])
    assert result.names_kept is None


def test_kept_names_are_checked_like_new_ones(roster):
    # Another animal here took "Bingo" since the first run: keeping it is refused.
    first, _, _ = run(Script([PLAN], [DRAFT]), roster)
    result, log, _ = refine(
        roster, first, "shorter sentences", [DRAFT, WITHOUT_BINGO], also_taken=frozenset({"bingo"})
    )
    assert not result.names_kept and result.draft.names[2].name == "Rusty"
    assert any("'Bingo' is already used" in s.text for s in log.steps)


def test_no_names_are_offered_to_keep_without_a_refine_or_a_draft(roster):
    first, _, _ = run(Script([PLAN], [DRAFT]), roster)
    titles = {o.entity_id: (None, "pet") for o in first.draft.names}
    assert kept_names(None, first, titles) == []
    assert kept_names("warmer", first.model_copy(update={"draft": None}), titles) == []
    # A title no longer on offer: the agent names afresh.
    assert kept_names("warmer", first, {}) == []
    assert kept_names("warmer", first, titles) == first.draft.names
    # A lookalike title its first run found is still on offer to keep.
    look = "00000000-0000-4000-8000-00000000f00d"
    found = Lookalike(
        entity=Entity(id=look, name="Example Film", type="movie"), animal="a dog", shared_look=[]
    )
    names = [*first.draft.names[:2], first.draft.names[2].model_copy(update={"entity_id": look})]
    earlier = first.model_copy(
        update={"draft": first.draft.model_copy(update={"names": names}), "lookalikes": [found]}
    )
    assert kept_names("warmer", earlier, titles) == names


def test_a_fix_request_is_logged_in_plain_words():
    from app.agent.steps import fix_request

    known = "00000000-0000-4000-8000-000000000001"
    cafe = "00000000-0000-4000-8000-000000000002"
    unknown = "00000000-0000-4000-8000-0000000000ff"
    names = {known: "Example Dog Show", cafe: "Example Cafe"}
    text = fix_request(
        [
            f"title {known} came back as candidates; give choice_reason",
            f"venue {unknown} is not among your latest find_venues results",
        ],
        names,
    )
    assert text == (
        "Code sent the answer back to Namesake's AI, asking: “title ‘Example Dog Show’ came "
        "back as candidates; say which one you meant, and why; venue with an ID this run's "
        "results do not name is not among the places Qloo returned last”"
    )
    # Reviewers, PR #87: a name followed by its own ID shows once, a list prints as words,
    # and the plan's own field is reworded.
    text = fix_request(
        [
            f"pick one of these that stand out (Example Cafe ({cafe})), or add each to "
            "rejected_venues with its reason",
            f"venues {sorted([cafe, known])} are both picked and rejected; choose one",
        ],
        names,
    )
    assert "(Example Cafe)" in text and "set each aside with a reason" in text
    assert "venues ‘Example Dog Show’ and ‘Example Cafe’ are both" in text
    # An item with an apostrophe comes as a double-quoted repr; it prints as words too.
    looks = ["broad head", "cat's eyes"]
    assert fix_request([f"not in the record: {looks}"]).endswith(
        "not in the record: broad head and cat's eyes”"
    )
    assert "rejected_venues" not in text and "[" not in text and cafe not in text
