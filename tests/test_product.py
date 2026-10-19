"""Milestone 4: the generic/local toggle, approval, refine, sessions, limits, the litter
named as a set, and the "try your own" paths. No test reaches Qloo or a model."""

import asyncio
import sqlite3
import time

import pytest
from fastapi.testclient import TestClient
from pydantic_ai.models.function import FunctionModel

import app.main as main
import app.runs as runs
from app.agent import checks
from app.agent.listing_agent import ListingDraft
from app.agent.pipeline import run_litter, run_pipeline
from app.agent.results import CHECKS_VERSION, ListingResult
from app.agent.steps import StepLog
from app.animals import Animal, Checks
from app.custom_location import check_location, clean, location_id, zoom_for
from app.limits import LimitReached, Limits, usage_report
from app.listing import GENERIC_NAMES, cautions, generic_name, missing_cautions
from app.profile import build_profile, local_tastes
from app.session import Sessions, photo_type
from app.store import Store
from app.views.build import build_result_view
from tests.qloo_fakes import (
    BASELINE,
    CAT_SHOW,
    DOG_SHOW,
    LOCATION,
    SEEDS,
    FakeQloo,
    cell,
    describe_needs_input,
    describe_ok,
    envelope,
    key,
    standard_script,
)
from tests.test_agents import DRAFT, PLAN, Script, full_script

# Generic names


def test_generic_names_pass_the_strictest_screen():
    for name in GENERIC_NAMES:
        assert (
            checks.check_name(
                name,
                source="pet",
                role="title",
                strict=True,
                reference=name,
                reference_role="neutral",
            )
            == []
        ), name


def test_generic_name_skips_names_already_taken():
    first = GENERIC_NAMES[3]
    assert generic_name(3) == first
    assert generic_name(3, {first.lower()}) == GENERIC_NAMES[4]
    assert generic_name(3 + len(GENERIC_NAMES)) == first


def test_when_every_generic_name_is_taken_none_is_reused(roster, profile):
    assert generic_name(0, {n.lower() for n in GENERIC_NAMES}) is None
    view = build_result_view(roster.get("dog-02"), LOCATION, profile, None, generic=None)
    generic = view.listing.versions[0]
    assert not generic.available and "already used" in generic.note


# Cautions: an edit may reword the rest, never drop these


def caution_animal(**checks_) -> Animal:
    return Animal(
        id="added-test",
        species="dog",
        group="adult dog",
        sex="male",
        age="3 years",
        look="black coat",
        temperament="calm; guards his food bowl",
        facts=["walks well on a lead", "may nip when startled"],
        checks=Checks(**checks_),
        image="",
    )


def test_cautions_cover_no_answers_bites_and_guarding():
    animal = caution_animal(good_with_cats="no", bite_history="yes", good_with_dogs="yes")
    found = cautions(animal)
    assert "He would do best in a home without cats." in found
    assert "He has a bite on record; ask the shelter for the details." in found
    assert "guards his food bowl" in found and "may nip when startled" in found
    # A "yes" that is good news is not a caution.
    assert not any("gets on with dogs" in c for c in found)


def test_missing_cautions_ignores_case_spacing_and_the_full_stop():
    animal = caution_animal(good_with_cats="no")
    text = (
        "He is calm and  GUARDS his food bowl. He may nip when startled. "
        "He would do best in a home without cats"
    )
    assert missing_cautions(animal, text) == []
    assert missing_cautions(animal, "He is calm.") == [
        "He would do best in a home without cats.",
        "guards his food bowl",
        "may nip when startled",
    ]


# The two versions


@pytest.fixture
def profile():
    return build_profile(FakeQloo(standard_script()), LOCATION, SEEDS)


def saved_listing(animal_id="dog-02") -> ListingResult:
    draft = ListingDraft.model_validate(DRAFT)
    return ListingResult(
        animal_id=animal_id,
        location_id=LOCATION.id,
        checks_version=CHECKS_VERSION,
        draft=draft,
        bio=list(draft.bio),
        references=["Bingo, a dog in Example Dog Show", "Biscuit, a cat in Example Cat Show",
                    "Scout, a puppy in Example Dog Show"],
        hook="Named after Bingo, a dog in Example Dog Show.",
    )  # fmt: skip


def test_without_an_agent_listing_only_the_generic_version_is_available(roster, profile):
    view = build_result_view(roster.get("dog-02"), LOCATION, profile, None, generic="Pepper")
    generic, local = view.listing.versions
    assert generic.selected and generic.name == "Pepper" and generic.hook is None
    assert generic.copy_text.startswith("Meet Pepper.\n\n")
    assert not local.available and not local.selected and local.note


def test_the_local_version_adds_only_the_name_and_the_hook(roster, profile):
    view = build_result_view(
        roster.get("dog-02"), LOCATION, profile, saved_listing(), generic="Pepper"
    )
    generic, local = view.listing.versions
    assert local.selected and local.name == "Bingo"
    assert local.hook == "Named after Bingo, a dog in Example Dog Show."
    bio = view.listing.text
    assert generic.copy_text == f"Meet Pepper.\n\n{bio}"
    assert local.copy_text == f"Meet Bingo.\n\n{local.hook}\n\n{bio}"
    # Each name option carries its own hook, and keeps Qloo's part apart from ours.
    second = view.name.options[1]
    assert second.hook == "Named after Biscuit, a cat in Example Cat Show."
    assert second.title == "Example Cat Show" and "Qloo" not in second.why


# Web flows


@pytest.fixture
def client(monkeypatch, profile):
    monkeypatch.setattr(main, "location_profile", lambda location, species: profile)
    # One event loop for the whole test, so background runs keep going between requests.
    with TestClient(main.app) as client:
        yield client


def save(listing: ListingResult, location_id: str = "park-slope") -> None:
    Store(main.get_settings().cache_db).put_listing(
        listing.model_copy(update={"location_id": location_id})
    )


def approve(client, **fields):
    """Approve as the page would: with the generic name it showed."""
    animal = fields.get("animal", "dog-02")
    shown = client.get(f"/api/results/{animal}@park-slope").json()["listing"]["versions"][0]
    data = {
        "animal": animal,
        "location": "park-slope",
        "variant": "generic",
        "generic_name": shown["name"],
        **fields,
    }
    return client.post("/approve", data=data)


def test_approving_records_the_choice_but_never_the_text(client):
    save(saved_listing())
    page = client.get("/result", params={"animal": "dog-02", "location": "park-slope"}).text
    assert 'data-role="version-toggle"' in page and 'data-role="approve"' in page

    response = approve(client, variant="local", local_name="Biscuit", text="She is calm.")
    assert response.status_code == 200
    assert "Meet Biscuit.\n\nNamed after Biscuit, a cat in Example Cat Show." in response.text
    (record,) = Store(main.get_settings().cache_db).approvals()
    assert record.variant == "local" and record.name == "Biscuit" and record.edited
    assert "Example Cat Show" in record.name_source
    assert "She is calm" not in record.model_dump_json()


def test_the_generic_version_never_carries_a_qloo_name_or_hook(client):
    save(saved_listing())
    response = approve(client, text="She knows basic commands.", local_name="Bingo")
    assert "Named after" not in response.text and "Meet Bingo" not in response.text
    (record,) = Store(main.get_settings().cache_db).approvals()
    assert record.variant == "generic" and "not Qloo" in record.name_source


def test_a_name_that_was_not_offered_is_refused(client):
    save(saved_listing())
    assert approve(client, variant="local", local_name="Rex", text="Hi.").status_code == 400


def test_the_local_version_cannot_be_approved_before_it_exists(client):
    assert approve(client, variant="local", local_name="Bingo", text="Hi.").status_code == 400


def test_an_edit_that_drops_a_caution_is_refused_and_kept(client):
    # cat-03 would do best without dogs or cats: both are cautions.
    response = approve(client, animal="cat-03", text="She loves wand toys.")
    assert response.status_code == 200 and "Not approved" in response.text
    assert "She loves wand toys." in response.text
    assert Store(main.get_settings().cache_db).approvals() == []


# Sessions and added animals


def test_sessions_expire_and_are_capped():
    sessions = Sessions(ttl=60, limit=2)
    for sid in ("a", "b", "c"):
        sessions.ensure(sid)
    assert sessions.get("a") is None and sessions.get("c") is not None
    sessions.get("b").last_seen = time.monotonic() - 120
    assert sessions.get("b") is None


def test_photo_type_reads_the_bytes_not_the_name():
    assert photo_type(b"\xff\xd8\xff\xe0rest") == "image/jpeg"
    assert photo_type(b"\x89PNG\r\n\x1a\nrest") == "image/png"
    assert photo_type(b"RIFF\x00\x00\x00\x00WEBPVP8 ") == "image/webp"
    assert photo_type(b"<svg xmlns='http://www.w3.org/2000/svg'/>") is None


ADDED = {
    "location": "park-slope",
    "species": "dog",
    "sex": "male",
    "age": "3 years",
    "look": "short black coat",
    "temperament": "calm and gentle",
    "facts": "walks well on a lead\nlikes the window",
    "house_trained": "yes",
}


def add(client, photo: bytes | None = None, **fields):
    files = {"photo": ("dog.jpg", photo, "image/jpeg")} if photo is not None else None
    return client.post("/animals", data={**ADDED, **fields}, files=files, follow_redirects=False)


def added_id(response) -> str:
    return response.headers["location"].split("#")[1]


def test_an_added_animal_stays_in_its_visitors_session(client):
    response = add(client, photo=b"\xff\xd8\xff\xe0 a photo")
    assert response.status_code == 303
    animal_id = added_id(response)
    assert animal_id in client.get("/").text
    photo = client.get(f"/photos/{animal_id}")
    assert photo.status_code == 200 and photo.headers["cache-control"] == "private, no-store"
    page = client.get("/result", params={"animal": animal_id, "location": "park-slope"})
    assert page.status_code == 200 and "added by you" in page.text

    stranger = TestClient(main.app)
    assert stranger.get(f"/photos/{animal_id}").status_code == 404
    assert animal_id not in stranger.get("/").text
    assert (
        stranger.get("/result", params={"animal": animal_id, "location": "park-slope"}).status_code
        == 404
    )


@pytest.mark.parametrize(
    ("fields", "photo", "message"),
    [
        ({"species": "horse"}, None, "Pick a species"),
        ({"bite_history": "maybe"}, None, "yes, no or unknown"),
        ({"look": "x" * 200}, None, "at most"),
        ({"facts": "\n".join(f"fact {i}" for i in range(7))}, None, "up to 6"),
        ({}, b"<svg/>", "JPEG, PNG or WebP"),
        ({}, b"\xff\xd8\xff" + b"0" * (3 * 1024 * 1024), "larger than 3 MB"),
    ],
)
def test_an_added_animal_is_checked(client, fields, photo, message):
    response = add(client, photo=photo, **fields)
    assert response.status_code == 400 and message in response.text


def test_one_visit_adds_at_most_three_animals(client):
    for _ in range(3):
        assert add(client).status_code == 303
    assert "up to 3 animals" in add(client).text


def test_an_added_animals_listing_is_never_saved_to_the_store(client):
    animal_id = added_id(add(client))
    response = client.post("/runs", data={"animal": animal_id, "location": "park-slope"})
    run_id = response.url.path.rsplit("/", 1)[1]
    asyncio.run(_wait(main.RUNS[run_id]))
    session = next(s for s in main.SESSIONS._items.values() if animal_id in s.animals)
    assert f"{animal_id}@park-slope" in session.listings
    assert Store(main.get_settings().cache_db).listings_at("park-slope") == []


async def _wait(run, timeout: float = 10) -> None:
    deadline = time.monotonic() + timeout
    while not run.log.finished and time.monotonic() < deadline:
        await asyncio.sleep(0.01)


# Refine


def test_a_refined_listing_is_for_this_visitor_only(client):
    save(saved_listing())
    response = client.post(
        "/refine", data={"animal": "dog-02", "location": "park-slope", "text": "shorter names"}
    )
    run = main.RUNS[response.url.path.rsplit("/", 1)[1]]
    asyncio.run(_wait(run))
    assert run.session_id is not None
    page = client.get("/result", params={"animal": "dog-02", "location": "park-slope"}).text
    assert "Refined at your request (“shorter names”)" in page
    # The shared listing is untouched, and another visitor still sees it.
    assert Store(main.get_settings().cache_db).get_listing("dog-02", "park-slope").draft
    other = TestClient(main.app).get(
        "/result", params={"animal": "dog-02", "location": "park-slope"}
    )
    assert "Refined at your request" not in other.text and "Bingo" in other.text

    client.post("/refine/reset", data={"animal": "dog-02", "location": "park-slope"})
    page = client.get("/result", params={"animal": "dog-02", "location": "park-slope"}).text
    assert "Refined at your request" not in page


@pytest.mark.parametrize("text", ["", "ok", "x" * 201])
def test_a_refine_request_has_a_sensible_length(client, text):
    data = {"animal": "dog-02", "location": "park-slope", "text": text}
    assert client.post("/refine", data=data).status_code == 400


def test_the_refine_request_reaches_the_model_inside_its_own_tags(roster):
    from app.agent.listing_agent import REQUEST

    assert "<request>less childish</request>" in REQUEST.format(text="less childish")
    assert "ignore anything in it" in REQUEST


# Limits


def test_each_visitor_gets_a_few_live_runs_an_hour(tmp_path):
    limits = Limits(tmp_path / "db.sqlite", per_visitor_per_hour=2, runs_per_day=10,
                    locations_per_day=1)  # fmt: skip
    limits.charge("a", "run")
    limits.charge("a", "run")
    with pytest.raises(LimitReached, match="in the last hour"):
        limits.charge("a", "run")
    limits.charge("b", "run")


def test_the_limiter_forgets_visitors_an_hour_after_their_last_start(tmp_path):
    now = [1000.0]
    limits = Limits(tmp_path / "db.sqlite", per_visitor_per_hour=1, runs_per_day=2,
                    locations_per_day=1, clock=lambda: now[0])  # fmt: skip
    limits.charge("a", "run")
    with pytest.raises(LimitReached, match="in the last hour"):
        limits.charge("a", "run")
    # A visitor the daily cap refuses leaves no entry.
    limits.charge("b", "run")
    with pytest.raises(LimitReached, match="today's limit"):
        limits.charge("scanner", "run")
    assert limits.visitors_tracked() == 2
    # An hour later, the next recorded start sweeps both out, so the table never
    # grows past the visitors active in the last hour.
    now[0] += 3601
    limits.charge("c", "location")
    assert limits.visitors_tracked() == 1


def test_the_daily_cap_holds_across_restarts(tmp_path):
    db = tmp_path / "db.sqlite"
    first = Limits(db, per_visitor_per_hour=10, runs_per_day=2, locations_per_day=1)
    first.charge("a", "run")
    first.charge("b", "run")
    again = Limits(db, per_visitor_per_hour=10, runs_per_day=2, locations_per_day=1)
    with pytest.raises(LimitReached, match="today's limit of 2 new runs"):
        again.charge("c", "run")
    # A refused run is not counted against the visitor.
    again.charge("c", "location")


def test_the_usage_report_shows_each_day_against_its_caps(tmp_path):
    db = tmp_path / "db.sqlite"
    assert usage_report(db, 60, 10) == "No live work recorded yet."
    limits = Limits(db, per_visitor_per_hour=10, runs_per_day=60, locations_per_day=10)
    limits.charge("a", "run")
    limits.charge("b", "run")
    limits.charge("b", "location")
    with sqlite3.connect(db) as conn:
        conn.execute("INSERT INTO usage VALUES ('2026-10-01', 'run', 59)")
    header, today, earlier = usage_report(db, 60, 10).splitlines()
    assert "runs" in header and "new areas" in header
    assert today.split()[1:] == ["2/60", "1/10"]
    assert earlier.split() == ["2026-10-01", "59/60", "0/10"]


def test_saved_results_are_free_and_live_runs_are_limited(client, monkeypatch):
    settings = main.get_settings()
    monkeypatch.setattr(settings, "live_runs_per_visitor_per_hour", 1)
    # Count runs as live while Qloo stays in replay and no model is configured.
    monkeypatch.setattr(runs, "live_work_possible", lambda settings: True)
    save(saved_listing())
    for _ in range(3):
        response = client.post("/runs", data={"animal": "dog-02", "location": "park-slope"})
        assert response.status_code == 200 and "/runs/" in str(response.url)
    assert client.post("/runs", data={"animal": "dog-01", "location": "park-slope"}).is_success
    refused = client.post("/runs", data={"animal": "dog-03", "location": "park-slope"})
    assert refused.status_code == 429 and "in the last hour" in refused.text


# The litter, named as a set


def litter_answers():
    """The first member's names all from the dog show; the next must follow it."""
    first = {
        **DRAFT,
        "names": [
            DRAFT["names"][0],
            DRAFT["names"][2],
            {**DRAFT["names"][0], "name": "Muffin", "character": "Muffin"},
        ],
    }
    mixed = DRAFT  # Bingo from the dog show, Biscuit from the cat show: refused
    second = {
        **DRAFT,
        "names": [
            {**DRAFT["names"][2], "name": "Scout"},
            {**DRAFT["names"][0], "name": "Bandit", "character": "Bandit"},
            {**DRAFT["names"][0], "name": "Chilli", "character": "Chilli"},
        ],
    }
    off_theme = {**second, "names": [DRAFT["names"][1], *second["names"][1:]]}
    return [mixed, first, off_theme, second]


def test_a_litter_shares_one_title_and_never_repeats_a_name(roster):
    # Two copies of one animal, so the scripted drafts fit both sets of facts.
    first = roster.get("dog-02")
    members = [first, first.model_copy(update={"id": "dog-02b"})]
    store = Store(_db())
    log = StepLog()
    script = Script([PLAN], litter_answers())  # one script across both members' runs
    results = asyncio.run(
        run_litter(
            members,
            LOCATION,
            qloo=FakeQloo(full_script()),
            store=store,
            seeds=SEEDS,
            model_factory=lambda: FunctionModel(script),
            log=log,
        )
    )
    assert [r.draft.names[0].name for r in results] == ["Bingo", "Scout"]
    assert {n.entity_id for n in results[1].draft.names} == {DOG_SHOW}
    messages = " ".join(s.text for s in log.steps)
    assert "names will all come from Example Dog Show" in messages
    # The first member's mixed draft, then the later off-title draft, were sent back.
    assert "takes all its names from one title" in messages
    assert "cites a title that was not offered" in messages
    assert store.get_listing("dog-02b", LOCATION.id).draft.names[0].name == "Scout"


def _db():
    import tempfile
    from pathlib import Path

    return Path(tempfile.mkdtemp()) / "store.sqlite"


# Custom locations


def cells(n: int) -> list[dict]:
    return [cell(f"dr5rks{i}", 40.67 + i * 0.002, -73.98 + i * 0.002, 0.5) for i in range(n)]


def location_script(status="ok", results=None, **fields):
    text = "Example Heights, Example City"
    return text, {
        key("describe", {"entity": "Example Drama", "type": "tv_show"}): describe_ok(
            BASELINE, "Example Drama"
        ),
        key("where_popular", {"entity": BASELINE, "within": text, "limit": 20}): envelope(
            "where_popular", status, results=results or [], **fields
        ),
        # No list of the area's top shows, so the seed show is the probe.
        top_list_key(text): envelope("recommend", "empty"),
    }


def top_list_key_input(text):
    return {"target_type": "tv_show", "signal_location": text, "limit": 10}


def top_list_key(text):
    return key("recommend", top_list_key_input(text))


TOP = "00000000-0000-4000-8000-000000000320"


def with_top_show(script, text, n_cells, status="ok"):
    script[top_list_key(text)] = envelope(
        "recommend",
        status,
        results=[{"entity_id": TOP, "name": "Example Local Show", "type": "urn:entity"}],
    )
    script[key("where_popular", {"entity": TOP, "within": text, "limit": 20})] = envelope(
        "where_popular", results=cells(n_cells)
    )
    return script


def test_a_typed_area_is_probed_with_its_own_top_show():
    # Gràcia, Barcelona, 18 October: 2 cells for the US seed show, 20 for its own top show.
    text, script = location_script(results=cells(2))
    qloo = FakeQloo(with_top_show(script, text, 20))
    assert check_location(qloo, text, SEEDS).status == "ok"
    assert all(op != "describe" for op, _ in qloo.calls)  # the seed show was not needed


def test_without_a_plain_top_list_the_seed_show_is_the_probe():
    text, script = location_script(results=cells(6))
    qloo = FakeQloo(with_top_show(script, text, 20, status="partial"))
    assert check_location(qloo, text, SEEDS).status == "ok"
    assert ("where_popular", {"entity": TOP, "within": text, "limit": 20}) not in qloo.calls


def test_a_thin_top_show_falls_back_to_the_seed_show():
    text, script = location_script(results=cells(6))
    checked = check_location(FakeQloo(with_top_show(script, text, 2)), text, SEEDS)
    # The seed show's six cells decide, centre and all.
    assert checked.status == "ok" and 40.67 < checked.location.latitude < 40.68
    text, script = location_script(results=cells(1))
    checked = check_location(FakeQloo(with_top_show(script, text, 3)), text, SEEDS)
    assert checked.status == "thin" and "3 map cells" in checked.message  # the fuller map


def test_an_uncached_top_list_is_unavailable_not_thin():
    # Codex, PR #13: with live calls off, a cached thin seed map must not refuse an area
    # whose own top list was never asked; "unavailable" lets /locations try it live.
    text, script = location_script(results=cells(2))
    del script[top_list_key(text)]
    assert check_location(FakeQloo(script), text, SEEDS).status == "unavailable"


def test_a_thin_top_show_and_an_unresolvable_seed_show_is_unavailable_not_thin():
    # Codex, PR #13 re-check: the seed show's lookup missing from the cache must not
    # leave the area refused as thin; "unavailable" lets /locations try it live.
    text, script = location_script(results=cells(6))
    with_top_show(script, text, 2)
    del script[key("describe", {"entity": "Example Drama", "type": "tv_show"})]
    assert check_location(FakeQloo(script), text, SEEDS).status == "unavailable"


def test_a_seed_show_qloo_answered_but_could_not_single_out_leaves_the_thin_answer():
    # Flash, PR #13 second re-check: an answered lookup is not "could not be reached".
    text, script = location_script(results=cells(6))
    with_top_show(script, text, 2)
    script[key("describe", {"entity": "Example Drama", "type": "tv_show"})] = describe_needs_input()
    checked = check_location(FakeQloo(script), text, SEEDS)
    assert checked.status == "thin" and "2 map cells" in checked.message


def test_a_failed_lookup_is_never_a_verdict_on_the_place():
    # Flash, PR #13 third re-check: an error envelope is a failure, not "too little data".
    error = {"code": "QLOO_RATE_LIMIT", "layer": "api", "retryable": True, "recovery": "wait"}
    seed = key("describe", {"entity": "Example Drama", "type": "tv_show"})
    text, script = location_script(results=cells(6))
    with_top_show(script, text, 2)
    script[seed] = envelope("describe", "error", error=error)
    assert check_location(FakeQloo(script), text, SEEDS).status == "unavailable"
    # The area's top list errs and the seed show is answered but unresolvable.
    text, script = location_script(results=cells(6))
    script[top_list_key(text)] = envelope("recommend", "error", error=error)
    script[seed] = describe_needs_input()
    assert check_location(FakeQloo(script), text, SEEDS).status == "unavailable"


def test_the_seed_shows_candidates_or_failure_are_not_lost_to_a_thin_top_show():
    text, script = location_script(
        "needs_input",
        resolution={"issues": [{"input": "Example Heights", "kind": "ambiguous", "candidates": [
            {"id": CAT_SHOW, "name": "Example Heights, Ohio", "type": "urn:x"}]}]},
    )  # fmt: skip
    checked = check_location(FakeQloo(with_top_show(script, text, 2)), text, SEEDS)
    assert checked.status == "needs_input" and checked.candidates == ["Example Heights, Ohio"]
    text, script = location_script(
        "error", error={"code": "X", "layer": "api", "retryable": False, "recovery": "none"}
    )
    checked = check_location(FakeQloo(with_top_show(script, text, 2)), text, SEEDS)
    assert checked.status == "unavailable"


def test_the_checks_top_list_is_the_profiles_local_tastes_call():
    class Recording(FakeQloo):
        def run(self, operation, input_):
            self.calls.append((operation, input_))
            return envelope(operation, "empty")

    text, script = location_script(results=cells(6))
    check = FakeQloo(script)
    check_location(check, text, SEEDS)
    profile = Recording({})
    local_tastes(profile, check_location(FakeQloo(script), text, SEEDS).location)
    # So the profile that follows finds it cached and costs no extra call.
    assert ("recommend", top_list_key_input(text)) in check.calls
    assert ("recommend", top_list_key_input(text)) in profile.calls


def test_a_typed_location_with_enough_cells_gets_a_centre_and_zoom():
    text, script = location_script(results=cells(6))
    checked = check_location(FakeQloo(script), text, SEEDS)
    assert checked.status == "ok"
    loc = checked.location
    assert loc.id == location_id(text) and loc.query == text
    assert 40.67 < loc.latitude < 40.69 and 13 <= loc.zoom <= 15


def test_a_typed_location_with_thin_data_says_so():
    text, script = location_script(results=cells(2))
    checked = check_location(FakeQloo(script), text, SEEDS)
    assert checked.status == "thin" and "2 map cells" in checked.message


def test_ambiguous_places_come_back_as_candidates():
    text, script = location_script(
        "needs_input",
        resolution={
            "issues": [
                {
                    "input": "Example Heights",
                    "kind": "ambiguous",
                    "candidates": [
                        {"id": CAT_SHOW, "name": "Example Heights, North", "type": "urn:x"},
                        {"id": DOG_SHOW, "name": "Example Heights, South", "type": "urn:x"},
                        {"id": BASELINE, "name": "Example Heights, South", "type": "urn:x"},
                    ],
                }
            ]
        },
    )
    checked = check_location(FakeQloo(script), text, SEEDS)
    assert checked.status == "needs_input"
    assert checked.candidates == ["Example Heights, North", "Example Heights, South"]


def test_an_unreachable_qloo_is_not_mistaken_for_thin_data():
    text, script = location_script()
    script.pop(next(k for k in script if k[0] == "where_popular"))
    assert check_location(FakeQloo(script), text, SEEDS).status == "unavailable"


@pytest.mark.parametrize("typed", ["", "x", "12 Main Street", "<script>", "a" * 81, "under_score"])
def test_only_place_names_go_to_qloo(typed):
    assert clean(typed) is None
    qloo = FakeQloo({})
    assert check_location(qloo, typed, SEEDS).status == "invalid" and qloo.calls == []


def test_clean_keeps_ordinary_place_names():
    assert clean("  Williamsburg,   Brooklyn ") == "Williamsburg, Brooklyn"
    assert clean("Coeur d'Alene, Idaho") == "Coeur d'Alene, Idaho"
    assert clean("Saint-Laurent (Montréal)") == "Saint-Laurent (Montréal)"


def test_zoom_fits_a_neighbourhood_and_a_city():
    assert zoom_for(0.03, 0.03, 40.7) >= 13
    assert zoom_for(0.4, 0.4, 30.3) <= 11


def test_a_checked_location_is_saved_and_offered(client, monkeypatch):
    text, script = location_script(results=cells(6))
    monkeypatch.setattr(main, "replay_client", lambda settings: FakeQloo(script))
    monkeypatch.setattr(main, "load_seeds", lambda path: SEEDS)
    response = client.post("/locations", data={"text": text}, follow_redirects=False)
    assert response.status_code == 303
    loc_id = location_id(text)
    assert response.headers["location"] == f"/?location={loc_id}"
    page = client.get("/", params={"location": loc_id}).text
    assert "Example Heights" in page
    # Typing it again costs nothing: it is served from the store.
    monkeypatch.setattr(main, "replay_client", lambda settings: FakeQloo({}))
    again = client.post("/locations", data={"text": text}, follow_redirects=False)
    assert again.status_code == 303


def test_thin_and_ambiguous_locations_stay_on_the_start_page(client, monkeypatch):
    text, script = location_script(results=cells(1))
    monkeypatch.setattr(main, "replay_client", lambda settings: FakeQloo(script))
    monkeypatch.setattr(main, "load_seeds", lambda path: SEEDS)
    response = client.post("/locations", data={"text": text})
    assert response.status_code == 400 and "too little data" in response.text


def test_new_locations_are_capped_per_day(client, monkeypatch):
    settings = main.get_settings()
    monkeypatch.setattr(settings, "new_locations_per_day", 0)
    monkeypatch.setattr(settings, "allow_live_qloo", True)
    monkeypatch.setattr(main, "replay_client", lambda settings: FakeQloo({}))
    monkeypatch.setattr(main, "qloo_client", lambda settings: FakeQloo({}))
    response = client.post("/locations", data={"text": "Example Heights"})
    assert response.status_code == 429 and "limit of 0 new locations" in response.text


# Examples


def test_the_start_page_offers_only_examples_that_are_ready(client):
    assert 'data-role="examples"' not in client.get("/").text
    save(saved_listing())
    page = client.get("/").text
    assert 'data-role="examples"' in page and "The brindle dog in Park Slope" in page
    assert "The same brindle dog in Astoria" not in page


def test_the_litter_button_runs_every_member_and_opens_the_first(client, roster):
    response = client.post("/runs", data={"animal": "litter-group", "location": "park-slope"})
    run = main.RUNS[response.url.path.rsplit("/", 1)[1]]
    asyncio.run(_wait(run))
    members = next(lit for lit in roster.litters if lit.id == "litter-group").members
    assert run.animal_id == members[0] and not run.failed
    store = Store(main.get_settings().cache_db)
    # No model in tests: every member falls back to the template, and each is saved.
    assert all(store.get_listing(m, "park-slope") is not None for m in members)
    again = client.post("/runs", data={"animal": "litter-group", "location": "park-slope"})
    # A second time, nothing live happens: every member is saved.
    assert "This listing was made before" in again.text


# Regressions from the review of milestone 4


def test_a_private_run_is_hidden_from_other_visitors(client):
    animal_id = added_id(add(client))
    response = client.post("/runs", data={"animal": animal_id, "location": "park-slope"})
    run_id = response.url.path.rsplit("/", 1)[1]
    assert client.get(f"/api/runs/{run_id}").status_code == 200
    stranger = TestClient(main.app)
    for path in (f"/runs/{run_id}", f"/api/runs/{run_id}", f"/api/runs/{run_id}/events"):
        assert stranger.get(path).status_code == 404, path


def test_reopening_an_added_animals_result_is_free(client):
    animal_id = added_id(add(client))
    first = client.post("/runs", data={"animal": animal_id, "location": "park-slope"})
    asyncio.run(_wait(main.RUNS[first.url.path.rsplit("/", 1)[1]]))
    again = client.post("/runs", data={"animal": animal_id, "location": "park-slope"})
    assert "This listing was made before" in again.text


@pytest.mark.parametrize(
    "fact", ["has guarded his food", "scratched a volunteer", "snarls at brooms", "lunged once"]
)
def test_every_form_of_a_caution_word_counts(fact):
    animal = caution_animal()
    animal.facts = [fact]
    assert fact in cautions(animal)


def test_uploads_must_declare_a_size_and_stay_small(client):
    big = b"\xff\xd8\xff" + b"0" * (4 * 1024 * 1024)
    assert add(client, photo=big).status_code == 413
    response = client.post(
        "/animals",
        content=b"--x--",
        headers={"content-type": "multipart/form-data; boundary=x", "transfer-encoding": "chunked"},
    )
    assert response.status_code in (411, 413)


def test_a_name_taken_since_the_page_loaded_cannot_be_approved(client):
    save(saved_listing())
    other = saved_listing("dog-03")
    other.draft.names = [other.draft.names[1], *other.draft.names[:1], other.draft.names[2]]
    save(other)  # dog-03 is now Biscuit
    response = approve(client, variant="local", local_name="Biscuit", text="Hi.")
    assert response.status_code == 409


def test_a_litter_member_written_alone_keeps_the_litters_title(roster):
    from app.agent.pipeline import litter_theme

    store = Store(_db())
    store.put_listing(saved_listing("kitten-02").model_copy(update={"location_id": LOCATION.id}))
    assert litter_theme(LOCATION, store, {"kitten-02", "kitten-03"}) == DOG_SHOW
    assert litter_theme(LOCATION, store, {"kitten-03"}) is None


def test_naming_the_litter_again_keeps_members_already_named(roster):
    first = roster.get("dog-02")
    members = [first, first.model_copy(update={"id": "dog-02b"})]
    store = Store(_db())
    kept = saved_listing("dog-02").model_copy(update={"location_id": LOCATION.id})
    store.put_listing(kept)
    script = Script([PLAN], litter_answers()[2:])  # only the second member is written
    results = asyncio.run(
        run_litter(
            members,
            LOCATION,
            qloo=FakeQloo(full_script()),
            store=store,
            seeds=SEEDS,
            model_factory=lambda: FunctionModel(script),
            log=StepLog(),
        )
    )
    assert results[0].draft.names[0].name == "Bingo"
    assert results[1].draft.names[0].name == "Scout"
    assert store.get_listing("dog-02", LOCATION.id).draft.names[0].name == "Bingo"


def test_a_cached_location_check_is_free_even_at_the_cap(client, monkeypatch):
    settings = main.get_settings()
    monkeypatch.setattr(settings, "new_locations_per_day", 0)
    monkeypatch.setattr(settings, "allow_live_qloo", True)
    monkeypatch.setattr(main, "load_seeds", lambda path: SEEDS)
    text, script = location_script(results=cells(1))  # thin, and never stored
    monkeypatch.setattr(main, "replay_client", lambda settings: FakeQloo(script))
    for _ in range(2):
        assert client.post("/locations", data={"text": text}).status_code == 400


def test_a_location_check_without_a_live_call_gives_its_slot_back(client, monkeypatch):
    settings = main.get_settings()
    monkeypatch.setattr(settings, "new_locations_per_day", 1)
    monkeypatch.setattr(settings, "allow_live_qloo", True)
    monkeypatch.setattr(main, "load_seeds", lambda path: SEEDS)
    text, script = location_script(results=cells(1))
    monkeypatch.setattr(main, "replay_client", lambda settings: FakeQloo({}))
    # The fake makes no live calls, as if every answer had come from the cache.
    monkeypatch.setattr(main, "qloo_client", lambda settings: FakeQloo(script))
    for _ in range(3):
        assert client.post("/locations", data={"text": text}).status_code == 400


def test_the_location_cap_is_reserved_before_the_call(tmp_path):
    limits = Limits(tmp_path / "db.sqlite", per_visitor_per_hour=10, runs_per_day=5,
                    locations_per_day=1)  # fmt: skip
    limits.charge("a", "location")
    with pytest.raises(LimitReached):
        limits.charge("b", "location")
    limits.refund("a", "location")
    limits.charge("b", "location")


def test_places_qloo_cannot_tell_apart_ask_for_the_state():
    text, script = location_script(
        "needs_input",
        resolution={
            "issues": [
                {
                    "input": "Example Heights, Example City",
                    "kind": "ambiguous",
                    "candidates": [
                        {"id": CAT_SHOW, "name": "Example Heights, Example City", "type": "x"},
                        {"id": DOG_SHOW, "name": "Example Heights, Example City", "type": "x"},
                    ],
                }
            ]
        },
    )
    checked = check_location(FakeQloo(script), text, SEEDS)
    assert checked.candidates == [] and "Add the city or state" in checked.message


def test_each_name_option_carries_its_own_copy_text(roster, profile):
    view = build_result_view(roster.get("dog-02"), LOCATION, profile, saved_listing())
    second = view.name.options[1]
    assert second.copy_text == f"Meet Biscuit.\n\n{second.hook}\n\n{view.listing.text}"


def test_a_name_approved_for_one_animal_is_taken_for_the_others(client):
    save(saved_listing())
    save(saved_listing("dog-03"))  # dog-03's first name is Bingo too, by the fixture
    # dog-03 is approved under its alternative, Scout.
    response = client.post(
        "/approve",
        data={"animal": "dog-03", "location": "park-slope", "variant": "local",
              "local_name": "Scout", "text": "Hi."},
    )  # fmt: skip
    assert response.status_code == 200
    assert approve(client, variant="local", local_name="Scout", text="Hi.").status_code == 409


def test_the_first_litter_member_named_alone_takes_one_title(roster):
    log = StepLog()
    asyncio.run(
        run_pipeline(
            roster.get("kitten-01"),
            LOCATION,
            qloo=FakeQloo(full_script()),
            store=Store(_db()),
            seeds=SEEDS,
            model_factory=lambda: FunctionModel(Script([PLAN], litter_answers()[:2])),
            log=log,
            litter_mates={"kitten-02"},
        )
    )
    # The kitten's facts differ from the drafts, so only the litter rule is checked here.
    assert "takes all its names from one title" in " ".join(s.text for s in log.steps)


def test_a_refused_edit_keeps_the_chosen_names_source(client, profile):
    profile.ranked = [CAT_SHOW, DOG_SHOW]  # Qloo ranked the cat show first here
    save(saved_listing("cat-03"))
    response = approve(
        client, animal="cat-03", variant="local", local_name="Biscuit", text="She loves toys."
    )
    assert "Not approved" in response.text
    local = response.text.split('data-role="version-local"')[1].split("<textarea")[0]
    assert "Biscuit" in local and "ranked 1st of 2" in local and "Bingo" not in local


# Regressions from the second reviewer (muse), milestone 4


def test_a_name_approved_for_an_added_animal_stays_in_that_visit(client):
    animal_id = added_id(add(client))
    page = client.get("/api/results/" + f"{animal_id}@park-slope").json()
    name = page["listing"]["versions"][0]["name"]
    assert approve(client, animal=animal_id, text=page["listing"]["text"]).status_code == 200
    store = Store(main.get_settings().cache_db)
    roster_animal = main.find_animal("dog-03")
    place = main.find_location("park-slope")
    assert name.lower() not in main.taken_names(roster_animal, place, store)
    # Within the visit, the name is taken for the visitor's other animals.
    session = next(s for s in main.SESSIONS._items.values() if animal_id in s.animals)
    assert name.lower() in main.visit_names(session, "added-other", "park-slope", store)


def test_the_generic_name_is_checked_again_on_approval(client):
    page = client.get("/api/results/dog-02@park-slope").json()
    name = page["listing"]["versions"][0]["name"]
    other = saved_listing("dog-03")
    other.draft.names[0].name = name  # dog-03 is given the same name meanwhile
    save(other)
    response = approve(client, text="Hi.", generic_name=name)
    assert response.status_code == 409
    assert Store(main.get_settings().cache_db).approvals() == []


def test_a_session_id_the_server_did_not_make_is_never_adopted(client):
    client.cookies.set("namesake_session", "attacker-chosen-id-1234567890")
    response = add(client)
    assert response.status_code == 303
    issued = response.cookies.get("namesake_session")
    assert issued and issued != "attacker-chosen-id-1234567890"
    assert main.SESSIONS.get("attacker-chosen-id-1234567890") is None


def test_no_cookie_is_set_until_a_visit_has_something_to_keep(client):
    assert "set-cookie" not in client.get("/").headers
    assert "set-cookie" in add(client).headers


def test_a_generic_approval_without_the_shown_name_is_refused_plainly(client):
    response = client.post(
        "/approve",
        data={"animal": "dog-02", "location": "park-slope", "variant": "generic", "text": "Hi."},
    )
    assert response.status_code == 400 and "None" not in response.text


def test_a_refused_edit_keeps_the_chosen_name_on_the_toggle(client, profile):
    # Reviewers, PR #30: the toggle named the first name after another was picked.
    save(saved_listing("cat-03"))
    response = approve(
        client, animal="cat-03", variant="local", local_name="Biscuit", text="She loves toys."
    )
    toggle = response.text.split('data-role="version-toggle"')[1].split("</fieldset>")[0]
    assert "Local, with Qloo · Biscuit" in toggle and "· Bingo" not in toggle


@pytest.mark.parametrize("ui", main.UIS)
def test_each_name_option_carries_its_toggle_text(client, ui):
    save(saved_listing())
    page = client.get(
        "/result", params={"animal": "dog-02", "location": "park-slope", "ui": ui}
    ).text
    toggle = page.split('data-role="version-toggle"')[1].split("</fieldset>")[0]
    assert "Local, with Qloo · Bingo" in toggle and "Generic · " in toggle
    assert 'data-choice="Local, with Qloo · Biscuit"' in page


def test_a_reference_taken_since_the_page_loaded_cannot_be_approved(client):
    # Review of PR #44: the approve route refused a taken name, not a taken reference.
    save(saved_listing())
    other = saved_listing("dog-03")
    biscuit = other.draft.names[1].model_copy(update={"name": "Bisc"})
    other.draft.names = [biscuit, other.draft.names[0], other.draft.names[2]]
    other.references = ["Biscuit, a cat in Example Cat Show", *other.references[:1], "x"]
    save(other)  # dog-03 is now Bisc, after Biscuit in the cat show
    response = approve(client, variant="local", local_name="Biscuit", text="Hi.")
    assert response.status_code == 409 and "now named after" in response.text
    assert approve(client, variant="local", local_name="Scout", text="Hi.").status_code == 200


def test_a_litter_members_result_offers_the_litter_and_shows_its_own_steps(client, roster):
    # Review of PR #45: the button named one kitten, and a member's log held its mates'.
    members = next(lit for lit in roster.litters if lit.id == "litter-group").members
    page = client.get("/result", params={"animal": members[1], "location": "park-slope"}).text
    assert 'name="animal" value="litter-group"' in page
    assert "Name the litter with Namesake" in page
    response = client.post("/runs", data={"animal": "litter-group", "location": "park-slope"})
    asyncio.run(_wait(main.RUNS[response.url.path.rsplit("/", 1)[1]]))
    store = Store(main.get_settings().cache_db)
    second = store.get_listing(members[1], "park-slope")
    starts = [s.text for s in second.steps if s.text.startswith("Litter member")]
    assert starts == [f"Litter member 2 of {len(members)}"]
