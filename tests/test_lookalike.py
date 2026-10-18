"""Lookalike names: titles the listing agent looks up for an animal that looks like this one.

Scripted models and the fake Qloo only; every ID and name is invented.
"""

from types import SimpleNamespace

from pydantic_ai.messages import ModelResponse, ToolCallPart

from app.agent.listing_agent import (
    ListingDeps,
    Lookalike,
    NameOption,
    check_lookalike,
    look_up_lookalike,
)
from app.agent.steps import StepLog
from app.profile import Entity
from app.views.build import build_result_view
from tests.qloo_fakes import (
    LOCATION,
    FakeQloo,
    envelope,
    key,
)
from tests.test_agents import DRAFT, PLAN, Script, full_script, run

DOG_FILM = "00000000-0000-4000-8000-000000000105"
DOG_FILM_OLD = "00000000-0000-4000-8000-000000000106"
FILM_LOOKUP = {"entity": "Example Dog Film", "type": "movie"}

REX = {
    "name": "Rex",
    "source": "lookalike",
    "entity_id": DOG_FILM,
    "character": "Rex",
    "role": "dog",
    "reference_role": "hero",
    "why": "It fits her short brindle coat.",
}


def film_script(ambiguous: bool = False, single: bool = False):
    script = full_script()
    if ambiguous:
        script[key("describe", FILM_LOOKUP)] = envelope(
            "describe",
            "needs_input",
            resolution={
                "issues": [
                    {
                        "input": "Example Dog Film",
                        "kind": "ambiguous",
                        "candidates": [
                            {
                                "id": DOG_FILM,
                                "name": "Example Dog Film",
                                "type": "urn:entity:movie",
                                "description": "Example Dog Film (1989) is a made-up film.",
                            },
                            {
                                "id": DOG_FILM_OLD,
                                "name": "Example Dog Film",
                                "type": "urn:entity:movie",
                                "description": "A different made-up film (1950).",
                            },
                        ][: 1 if single else 2],
                    }
                ]
            },
        )
    else:
        script[key("describe", FILM_LOOKUP)] = envelope(
            "describe",
            results=[
                {
                    "entity_id": DOG_FILM,
                    "name": "Example Dog Film",
                    "type": "urn:entity:movie",
                    "properties": {"short_description": "A made-up film about a big dog."},
                }
            ],
        )
    return script


class LookalikeScript(Script):
    """The listing agent looks one title up before answering."""

    def __init__(self, profile_answers, listing_answers, shared_look=("brindle",)):
        super().__init__(profile_answers, listing_answers)
        self.shared_look = list(shared_look)

    def __call__(self, messages, info):
        tools = {t.name for t in info.function_tools}
        returned = {
            p.tool_name
            for m in messages
            for p in getattr(m, "parts", [])
            if getattr(p, "part_kind", "") == "tool-return"
        }
        if "look_up_title" not in tools and "look_up_lookalike" not in returned:
            return ModelResponse(
                parts=[
                    ToolCallPart(
                        "look_up_lookalike",
                        {
                            "title": "Example Dog Film",
                            "kind": "movie",
                            "animal_in_it": "Rex",
                            "shared_look": self.shared_look,
                        },
                    )
                ]
            )
        return super().__call__(messages, info)


def with_rex(first: bool = False) -> dict:
    names = [REX, *DRAFT["names"]] if first else [*DRAFT["names"], REX]
    return {**DRAFT, "names": names}


def deps(roster, animal="dog-02", **kw) -> ListingDeps:
    return ListingDeps(
        animal=roster.get(animal),
        titles={},
        log=StepLog(),
        qloo=FakeQloo(film_script(kw.pop("ambiguous", False), kw.pop("single", False))),
        **kw,
    )


def test_a_lookalike_name_is_offered_with_its_own_badge_and_why(roster):
    result, store, log = run(
        LookalikeScript([PLAN], [with_rex()]), roster, qloo=FakeQloo(film_script())
    )
    assert result.draft is not None and result.draft.names[-1].name == "Rex"
    assert result.references[-1] == "Rex, a dog in Example Dog Film"
    [look] = result.lookalikes
    assert look.entity.id == DOG_FILM and look.shared_look == ["brindle"]
    # The local version keeps a name from the area's titles.
    assert result.hook == "Named after Bingo, a dog in Example Dog Show."
    assert any("Rex shares this dog's look (brindle)" in s.text for s in log.steps)

    profile = store.get_profile(LOCATION.id, "dog")
    view = build_result_view(roster.get("dog-02"), LOCATION, profile, result)
    rex = next(o for o in view.name.options if o.name == "Rex")
    assert rex.badge == "Has a lookalike in Example Dog Film"
    assert rex.title == "Example Dog Film"
    returned = {i.title: i.detail for i in view.qloo_returned}
    reading = {i.title: i.detail for i in view.our_reading}
    assert returned["Example Dog Film (film)"].startswith("Found in Qloo.")
    assert "recorded look: brindle" in reading["Why Example Dog Film"]
    assert "Qloo confirmed the title, not how its animals look" in reading["Why Example Dog Film"]


def test_a_lookalike_cannot_be_the_first_name(roster):
    result, _, log = run(
        LookalikeScript([PLAN], [with_rex(first=True), with_rex()]),
        roster,
        qloo=FakeQloo(film_script()),
    )
    assert any("the first name must come from the area's titles" in s.text for s in log.steps)
    assert result.draft.names[0].name == "Bingo"


def test_shared_look_must_quote_the_record(roster):
    d = deps(roster)
    out = look_up_lookalike(SimpleNamespace(deps=d), "Example Dog Film", "movie", "Rex", ["golden"])
    assert out["status"].startswith("refused") and "golden" in out["status"]
    # Words only every big dog shares are not a lookalike.
    out = look_up_lookalike(
        SimpleNamespace(deps=d), "Example Dog Film", "movie", "Rex", ["large", "mixed breed"]
    )
    assert out["status"].startswith("refused")
    assert d.qloo.calls == [] and d.lookups == 0


def test_lookups_are_capped_and_never_for_a_litter(roster):
    d = deps(roster)
    ctx = SimpleNamespace(deps=d)
    first = look_up_lookalike(ctx, "Example Dog Film", "movie", "Rex", ["brindle"])
    # Asking again, as after a repair, gives the same answer without another lookup.
    again = look_up_lookalike(ctx, "example dog film ", "movie", "Rex", ["brindle"])
    assert first["status"] == "found" and again == first
    assert d.lookups == 1 and len(d.qloo.calls) == 1
    d.lookups = 2
    third = look_up_lookalike(ctx, "Another Dog Film", "movie", "Max", ["brindle"])
    assert third["status"].startswith("unavailable") and len(d.qloo.calls) == 1

    kitten = deps(roster, animal="kitten-01", first_of_litter=True)
    out = look_up_lookalike(
        SimpleNamespace(deps=kitten), "Example Dog Film", "movie", "Rex", ["grey"]
    )
    assert out["status"].startswith("unavailable") and kitten.qloo.calls == []


def test_a_profile_title_keeps_its_own_source(roster):
    d = deps(roster)
    shown = Entity(id=DOG_FILM, name="Example Dog Film", type="urn:entity:movie")
    d.titles[DOG_FILM] = (shown, "pet")
    look_up_lookalike(SimpleNamespace(deps=d), "Example Dog Film", "movie", "Rex", ["brindle"])
    assert d.titles[DOG_FILM][1] == "pet" and d.lookalikes == {}


def test_an_ambiguous_lookalike_needs_a_reason_and_the_named_animal(roster):
    d = deps(roster, ambiguous=True)
    out = look_up_lookalike(
        SimpleNamespace(deps=d), "Example Dog Film", "movie", "Rex", ["brindle"]
    )
    assert out["status"] == "ambiguous" and len(out["candidates"]) == 2
    look = d.lookalikes[DOG_FILM]
    assert look.candidates == 2
    assert any("give choice_reason" in p for p in check_lookalike(NameOption(**REX), look))
    fixed = NameOption(**REX, choice_reason="the 1989 film")
    assert check_lookalike(fixed, look) == []
    # The name must be the lookalike animal's own, and an animal's.
    other = NameOption(**{**REX, "name": "Turner", "character": "Turner", "role": "character"})
    problems = check_lookalike(other, look)
    assert any("must be Rex" in p for p in problems)
    assert any("the animal's own name" in p for p in problems)


def test_a_strict_dog_may_take_a_lookalike_name():
    from app.agent.checks import check_name

    assert check_name("Rex", source="lookalike", role="dog", strict=True) == []


def test_the_lookalike_record_round_trips():
    look = Lookalike(
        entity=Entity(id=DOG_FILM, name="Example Dog Film", type="urn:entity:movie"),
        animal="Rex",
        shared_look=["brindle"],
    )
    assert Lookalike.model_validate_json(look.model_dump_json()) == look


def test_a_longer_form_of_the_lookalikes_name_is_the_same_animal(roster):
    look = Lookalike(
        entity=Entity(id=DOG_FILM, name="Example Dog Film", type="urn:entity:movie"),
        animal="Rex",
        shared_look=["brindle"],
    )
    longer = NameOption(**{**REX, "character": "Rex-Max"})
    assert check_lookalike(longer, look) == []
    other = NameOption(**{**REX, "name": "Max", "character": "Max"})
    assert any("its character 'Max' must be Rex" in p for p in check_lookalike(other, look))


LOOK = Lookalike(
    entity=Entity(id=DOG_FILM, name="Example Dog Film", type="urn:entity:movie"),
    animal="Rex",
    shared_look=["brindle"],
)


def test_the_offered_name_must_be_the_lookalikes_own():
    # Codex: name "John" with character "Rex" passed the strict screen.
    john = NameOption(**{**REX, "name": "John"})
    problems = check_lookalike(john, LOOK)
    assert any("its name 'John' must be Rex" in p for p in problems)
    assert check_lookalike(NameOption(**{**REX, "name": "Rex"}), LOOK) == []


def test_a_single_needs_input_candidate_is_a_choice_not_a_confirmation(roster):
    # Codex: one candidate passed without a reason and showed as "Found in Qloo".
    d = deps(roster, ambiguous=True, single=True)
    look_up_lookalike(SimpleNamespace(deps=d), "Example Dog Film", "movie", "Rex", ["brindle"])
    look = d.lookalikes[DOG_FILM]
    assert look.chosen and look.candidates == 1
    assert any("give choice_reason" in p for p in check_lookalike(NameOption(**REX), look))

    rex = {**REX, "choice_reason": "the 1989 film"}
    result, store, _ = run(
        LookalikeScript([PLAN], [{**DRAFT, "names": [*DRAFT["names"], rex]}]),
        roster,
        qloo=FakeQloo(film_script(ambiguous=True, single=True)),
    )
    profile = store.get_profile(LOCATION.id, "dog")
    view = build_result_view(roster.get("dog-02"), LOCATION, profile, result)
    returned = {i.title: i.detail for i in view.qloo_returned}
    reading = {i.title: i.detail for i in view.our_reading}
    assert returned["Example Dog Film (film)"].startswith(
        "Qloo asked which title was meant and offered one candidate."
    )
    assert "Found in Qloo" not in returned["Example Dog Film (film)"]
    why = reading["Why Example Dog Film"]
    assert "Namesake's AI chose this title among Qloo's candidates" in why
    assert "Qloo confirmed" not in why and why.endswith("Why this one: the 1989 film.")


def test_lookalikes_come_only_from_stories():
    # muse: a brand is not a story with an animal in it.
    from typing import get_args

    from app.agent.profile_agent import StoryKind

    assert set(get_args(StoryKind)) == {"tv_show", "movie", "book"}


def test_a_lookalike_badge_without_a_title_still_reads():
    from app.views.build import name_badge

    assert name_badge("lookalike", DOG_FILM, None, None) == "Has a lookalike"


def test_a_choice_reason_cannot_carry_a_taste_claim():
    # muse: the reason is shown as our reading, so it may only say which work it is.
    from app.agent.checks import check_choice_reason

    taste = NameOption(**REX, choice_reason="because locals love it")
    assert any("claim about tastes" in p for p in check_lookalike(taste, LOOK))
    assert check_choice_reason("the 1989 film, not the 1950 one", "x") == []
    assert check_choice_reason("the playful one", "x")


def test_a_failed_lookup_is_not_sent_again(roster):
    # Codex: QlooClient already retried a retryable error once, and a call Qloo marked
    # not retryable must not be repeated, so a failure is remembered like an answer.
    d = deps(roster)
    d.qloo.script = {}
    ctx = SimpleNamespace(deps=d)
    first = look_up_lookalike(ctx, "Example Dog Film", "movie", "Rex", ["brindle"])
    assert first["status"].startswith("unavailable")
    d.qloo.script = film_script()
    assert look_up_lookalike(ctx, "Example Dog Film", "movie", "Rex", ["brindle"]) == first
    assert len(d.qloo.calls) == 1


def test_saved_listings_with_lookalike_names_are_rerun_under_the_new_checks(roster, tmp_path):
    # Codex: a listing saved before the lookalike fixes still loaded as current.
    from app.agent.listing_agent import ListingDraft
    from app.agent.recheck import recheck
    from app.agent.results import CHECKS_VERSION, ListingResult
    from app.store import Store
    from tests.test_recheck import save_profile

    store = Store(tmp_path / "store.sqlite")
    save_profile(store)
    plain = ListingDraft.model_validate(DRAFT)
    looks = ListingDraft.model_validate(with_rex())
    for animal, draft, version in [
        ("dog-02", plain, 5),
        ("dog-01", plain, 4),
        ("dog-03", looks, 6),
        ("cat-01", looks, 7),
    ]:
        store.put_listing(
            ListingResult(animal_id=animal, location_id="x", checks_version=version, draft=draft)
        )
    # An older draft is never shown as it is, only once a recheck has held it to today's
    # checks.
    assert store.listings_at("x") == []
    recheck(store, roster)
    current = {r.animal_id for r in store.listings_at("x")}
    # Only the lookalike checks changed after version 5, so a plain listing from 5 on can
    # be rechecked; one with a lookalike name only from 7, when those checks last changed.
    assert "dog-02" in current
    assert not current & {"dog-01", "dog-03"}
    assert store.get_listing("dog-02", "x").checks_version == CHECKS_VERSION


def test_the_profile_agents_choice_reason_is_screened_too(roster):
    titles = [{**PLAN["titles"][0], "choice_reason": "the one locals love"}, *PLAN["titles"][1:]]
    _, store, log = run(Script([{**PLAN, "titles": titles}, PLAN], [DRAFT]), roster)
    assert any("makes a claim about tastes" in s.text for s in log.steps)
    assert store.get_profile(LOCATION.id, "dog").made_by == "agent"


def test_a_lookalike_name_may_shorten_the_animal_never_lengthen_it():
    # muse: "Rex the Brave" passed as Rex's own name.
    brave = NameOption(**{**REX, "name": "Rex the Brave"})
    assert any("its name 'Rex the Brave' must be Rex" in p for p in check_lookalike(brave, LOOK))
    scooby = LOOK.model_copy(update={"animal": "Scooby-Doo"})
    short = NameOption(**{**REX, "name": "Scooby", "character": "Scooby-Doo"})
    assert check_lookalike(short, scooby) == []


def test_asking_again_about_another_animal_records_that_animal(roster):
    # muse: a re-ask with a different animal returned the old record, naming the old animal.
    d = deps(roster)
    ctx = SimpleNamespace(deps=d)
    look_up_lookalike(ctx, "Example Dog Film", "movie", "Rex", ["brindle"])
    look_up_lookalike(ctx, "Example Dog Film", "movie", "Max", ["brindle"])
    # One request to Qloo; the record names the animal asked about last.
    assert d.lookalikes[DOG_FILM].animal == "Max" and d.lookups == 1 and len(d.qloo.calls) == 1
    max_ = NameOption(**{**REX, "name": "Max", "character": "Max"})
    assert check_lookalike(max_, d.lookalikes[DOG_FILM]) == []
    # Codex: Rex, then Max, then Rex again must leave Rex recorded.
    look_up_lookalike(ctx, "Example Dog Film", "movie", "Rex", ["brindle"])
    assert d.lookalikes[DOG_FILM].animal == "Rex"
    assert check_lookalike(NameOption(**REX), d.lookalikes[DOG_FILM]) == []


def test_a_failed_request_is_not_sent_again_for_another_animal(roster):
    # Codex: keying failures by animal re-sent an identical failed request.
    d = deps(roster)
    d.qloo.script = {}
    ctx = SimpleNamespace(deps=d)
    look_up_lookalike(ctx, "Example Dog Film", "movie", "Rex", ["brindle"])
    d.qloo.script = film_script()
    again = look_up_lookalike(ctx, "Example Dog Film", "movie", "Max", ["brindle"])
    assert again["status"].startswith("unavailable") and len(d.qloo.calls) == 1
