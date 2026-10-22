"""A visitor's workspace: kept on disk for 7 days, opened by its link, edited and
emptied by its visitor only (decision 34). No test reaches Qloo or a model."""

import time
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

import app.main as main
from app.session import Session, session_from, workspace_data
from app.workspace import RENEW, TTL, Workspaces
from tests.test_product import ADDED, add, added_id, client, profile, saved_listing  # noqa: F401

PHOTO = b"\xff\xd8\xff\xe0 a photo"


def forget_memory() -> None:
    """As after a restart: only the workspaces on disk are left."""
    main.SESSIONS._items.clear()


def workspace_id(client) -> str:  # noqa: F811
    return client.cookies.get("namesake_session")


def test_a_workspace_outlives_a_restart(client):  # noqa: F811
    animal_id = added_id(add(client, photo=PHOTO))
    forget_memory()
    page = client.get("/").text
    assert animal_id in page and 'data-role="your-animals"' in page
    assert client.get(f"/photos/{animal_id}").content == PHOTO


def test_the_cookie_lasts_as_long_as_the_workspace_and_each_visit_renews_it(client):  # noqa: F811
    response = add(client)
    assert f"Max-Age={TTL}" in response.headers["set-cookie"]
    assert f"Max-Age={TTL}" in client.get("/").headers["set-cookie"]


def test_the_link_opens_the_workspace_in_another_browser(client):  # noqa: F811
    animal_id = added_id(add(client))
    link = f"/workspace/{workspace_id(client)}"
    assert link in client.get("/").text
    forget_memory()
    other = TestClient(main.app)
    # The link asks first: on its own it never moves a browser into a workspace.
    asked = other.get(link, follow_redirects=False)
    assert asked.status_code == 200 and "Open this workspace?" in asked.text
    assert f'action="{link}"' in asked.text and animal_id not in other.get("/").text
    response = other.post(link, follow_redirects=False)
    assert response.status_code == 303 and response.headers["location"] == "/"
    assert animal_id in other.get("/").text


def test_a_link_from_another_site_cannot_open_a_workspace(client):  # noqa: F811
    add(client)
    link = f"/workspace/{workspace_id(client)}"
    other = TestClient(main.app)
    refused = other.post(link, headers={"sec-fetch-site": "cross-site"}, follow_redirects=False)
    assert refused.status_code == 403 and "set-cookie" not in refused.headers


def test_a_workspace_past_its_time_does_not_open(client, monkeypatch):  # noqa: F811
    add(client)
    link = f"/workspace/{workspace_id(client)}"
    forget_memory()
    now = time.time()
    monkeypatch.setattr(time, "time", lambda: now + TTL + RENEW + 60)
    assert TestClient(main.app).get(link).status_code == 404


def test_a_visit_that_only_reads_renews_the_workspace_on_disk(client, monkeypatch):  # noqa: F811
    add(client)
    session_id = workspace_id(client)
    db = Workspaces(main.get_settings().workspace_db)._connect()
    db.execute("UPDATE workspaces SET last_seen = last_seen - 86400")
    main.SESSIONS.get(session_id).disk_seen = 0
    client.get("/")
    seen = db.execute("SELECT last_seen FROM workspaces WHERE id = ?", (session_id,)).fetchone()
    assert seen[0] > time.time() - 60


@pytest.mark.parametrize("link", ["/workspace/not-made-by-the-server-12345", "/workspace/x"])
def test_a_workspace_the_server_does_not_keep_never_opens(client, link):  # noqa: F811
    response = client.get(link, follow_redirects=False)
    assert response.status_code == 404 and "set-cookie" not in response.headers


def test_a_workspace_ends_7_days_after_the_last_visit(tmp_path, monkeypatch):
    workspaces = Workspaces(tmp_path / "w.sqlite")
    workspaces.save("ws-1", {"animals": {}})
    now = time.time()
    monkeypatch.setattr(time, "time", lambda: now + TTL - 60)
    assert workspaces.load("ws-1") is not None
    monkeypatch.setattr(time, "time", lambda: now + TTL + RENEW + 60)
    assert workspaces.load("ws-1") is None
    # The next write anywhere deletes it, photo and all.
    workspaces.save("ws-2", {"animals": {}})
    db = workspaces._connect()
    assert db.execute("SELECT COUNT(*) FROM workspaces").fetchone()[0] == 1
    assert db.execute("SELECT COUNT(*) FROM workspace_photos").fetchone()[0] == 0


def test_an_edit_replaces_the_record_keeps_the_photo_and_drops_old_listings(client):  # noqa: F811
    animal_id = added_id(add(client, photo=PHOTO))
    session = main.SESSIONS.get(workspace_id(client))
    session.listings[f"{animal_id}@park-slope"] = object()  # any listing made before
    form = client.get("/animals/new", params={"location": "park-slope", "edit": animal_id})
    assert form.status_code == 200 and 'value="short black coat"' in form.text
    assert f'name="edit" value="{animal_id}"' in form.text
    response = client.post(
        "/animals", data={**ADDED, "look": "short brindle coat", "edit": animal_id},
        follow_redirects=False,
    )  # fmt: skip
    assert response.status_code == 303 and added_id(response) == animal_id
    session = main.SESSIONS.get(workspace_id(client))
    assert session.animals[animal_id].look == "short brindle coat"
    assert not session.listings and client.get(f"/photos/{animal_id}").content == PHOTO
    forget_memory()
    assert "short brindle coat" in client.get("/").text


def test_removing_an_animal_takes_its_photo_and_listings_off_disk(client):  # noqa: F811
    animal_id = added_id(add(client, photo=PHOTO))
    asked = client.post("/animals/remove", data={"remove": animal_id, "location": "park-slope"})
    assert "Remove this animal?" in asked.text and 'value="yes"' in asked.text
    assert animal_id in main.SESSIONS.get(workspace_id(client)).animals
    response = client.post(
        "/animals/remove",
        data={"remove": animal_id, "location": "park-slope", "confirm": "yes"},
        follow_redirects=False,
    )
    assert response.status_code == 303 and response.headers["location"].startswith("/?location=")
    forget_memory()
    assert animal_id not in client.get("/").text
    assert client.get(f"/photos/{animal_id}").status_code == 404
    db = Workspaces(main.get_settings().workspace_db)._connect()
    assert db.execute("SELECT COUNT(*) FROM workspace_photos").fetchone()[0] == 0


def test_only_its_visitor_edits_or_removes_an_animal(client):  # noqa: F811
    animal_id = added_id(add(client))
    stranger = TestClient(main.app)
    assert stranger.get("/animals/new", params={"edit": animal_id}).status_code == 404
    edited = stranger.post("/animals", data={**ADDED, "edit": animal_id}, follow_redirects=False)
    assert edited.status_code == 404
    stranger.post("/animals/remove", data={"remove": animal_id, "confirm": "yes"})
    cross = {"sec-fetch-site": "cross-site"}
    refused = client.post("/animals/remove", data={"remove": animal_id, "confirm": "yes"},
                          headers=cross)  # fmt: skip
    assert refused.status_code == 403
    assert animal_id in main.SESSIONS.get(workspace_id(client)).animals


def test_the_map_pin_is_never_written_to_disk(client):  # noqa: F811
    add(client)
    session = main.SESSIONS.get(workspace_id(client))
    session.pins["park-slope"] = (40.67, -73.98)
    main.SESSIONS.save(session)
    raw = Workspaces(main.get_settings().workspace_db).load(session.id)[0]
    assert "pins" not in raw and "40.67" not in str(raw)


def test_the_photo_budget_counts_every_workspace_on_disk(client, monkeypatch):  # noqa: F811
    monkeypatch.setattr(main, "PHOTO_BUDGET", len(PHOTO) + 4)
    assert add(client, photo=PHOTO).status_code == 303
    forget_memory()
    other = TestClient(main.app)
    refused = add(other, photo=PHOTO)
    assert refused.status_code == 400 and "too many photos" in refused.text


def test_the_start_page_puts_your_animals_and_workspace_before_the_samples(client):  # noqa: F811
    page = client.get("/").text
    assert "Add your own animal" in page and 'data-role="workspace"' not in page
    animal_id = added_id(add(client))
    page = client.get("/").text
    marks = ['data-role="your-animals"', f'id="{animal_id}"', 'name="edit"', 'name="remove"',
             'data-role="workspace"', "Or try a sample animal", 'id="dog-02"']  # fmt: skip
    positions = [page.index(m) for m in marks]
    assert positions == sorted(positions)
    assert "anyone with the link can open it." in page


def test_a_listing_outlives_a_restart_and_one_from_older_checks_runs_again(client):  # noqa: F811
    animal_id = added_id(add(client))
    session = main.SESSIONS.get(workspace_id(client))
    listing = saved_listing(animal_id)
    session.listings[f"{animal_id}@park-slope"] = listing
    session.listings[f"{animal_id}@astoria"] = listing.model_copy(update={"checks_version": 1})
    session.requests[f"{animal_id}@astoria"] = "less childish"
    session.requests[f"{animal_id}@park-slope"] = "shorter names"
    main.SESSIONS.save(session)
    forget_memory()
    kept = main.SESSIONS.get(session.id)
    assert list(kept.listings) == [f"{animal_id}@park-slope"]
    assert kept.requests == {f"{animal_id}@park-slope": "shorter names"}
    assert kept.listings[f"{animal_id}@park-slope"] == listing


def test_a_listing_for_an_animal_no_longer_kept_is_dropped_on_load():
    data = workspace_data(Session(id="ws"))
    data["listings"] = {
        "added-gone@park-slope": saved_listing("added-gone").model_dump(mode="json")
    }
    assert not session_from("ws", data, {}).listings


def test_an_unreadable_workspace_row_starts_afresh(tmp_path):
    workspaces = Workspaces(tmp_path / "w.sqlite")
    workspaces.save("ws-1", {"animals": {}})
    workspaces._connect().execute("UPDATE workspaces SET data_json = 'not json'")
    assert workspaces.load("ws-1") is None


def test_an_edit_takes_no_add_allowance(client, monkeypatch):  # noqa: F811
    from app.places import Allowance

    animal_id = added_id(add(client))
    monkeypatch.setattr(main, "ADD_ALLOWANCE", Allowance(per_minute=0))
    edited = client.post("/animals", data={**ADDED, "edit": animal_id}, follow_redirects=False)
    assert edited.status_code == 303


def test_photos_have_an_hourly_allowance_per_visitor(client, monkeypatch):  # noqa: F811
    from app.places import Allowance

    monkeypatch.setattr(main, "PHOTO_ALLOWANCE", Allowance(per_minute=1, window=3600))
    assert add(client, photo=PHOTO).status_code == 303
    refused = add(client, photo=PHOTO)
    assert refused.status_code == 429 and "last hour" in refused.text
    # The animal itself may still be added, without a photo.
    assert add(client).status_code == 303


def test_a_refused_photo_leaves_no_animal_behind(client, monkeypatch):  # noqa: F811
    monkeypatch.setattr(main, "PHOTO_BUDGET", 1)
    assert add(client, photo=PHOTO).status_code == 400
    session = main.SESSIONS.get(workspace_id(client))
    assert session is None or not session.animals
    forget_memory()
    assert 'id="added-' not in client.get("/").text


def test_a_run_for_an_edited_or_removed_animal_keeps_nothing(client, monkeypatch):  # noqa: F811
    from app import runs

    animal_id = added_id(add(client))
    session = main.SESSIONS.get(workspace_id(client))
    animal = session.animals[animal_id]
    kept = []
    monkeypatch.setattr(runs, "run_pipeline", lambda *a, save, **k: kept.append(save))
    run = SimpleNamespace(log=None)  # the pipeline is replaced, so nothing logs
    runs._listing_work(animal, main.find_location("park-slope"), main.get_settings(), run, session)
    session.animals[animal_id] = animal.model_copy(update={"look": "short brindle coat"})
    kept[0](saved_listing(animal_id))
    assert not session.listings


def test_crawlers_stay_off_workspace_links(client):  # noqa: F811
    assert "Disallow: /workspace/" in client.get("/robots.txt").text


def test_asking_about_a_link_does_not_renew_it_and_opening_keeps_the_ui(client):  # noqa: F811
    add(client)
    session_id = workspace_id(client)
    link = f"/workspace/{session_id}"
    db = Workspaces(main.get_settings().workspace_db)._connect()
    db.execute("UPDATE workspaces SET last_seen = last_seen - 86400")
    forget_memory()
    other = TestClient(main.app)
    asked = other.get(link, params={"ui": "warm"})
    assert 'name="ui" value="warm"' in asked.text
    seen = db.execute("SELECT last_seen FROM workspaces").fetchone()[0]
    assert seen < time.time() - 86000
    opened = other.post(link, data={"ui": "warm"}, follow_redirects=False)
    assert opened.headers["location"] == "/?ui=warm"


def test_a_workspace_is_kept_past_its_last_hourly_renewal(tmp_path, monkeypatch):
    workspaces = Workspaces(tmp_path / "w.sqlite")
    workspaces.save("ws-1", {"animals": {}})
    now = time.time()
    monkeypatch.setattr(time, "time", lambda: now + TTL + RENEW - 60)
    assert workspaces.load("ws-1") is not None


def test_asking_about_a_link_keeps_nothing_alive(client, monkeypatch):  # noqa: F811
    add(client)
    link = f"/workspace/{workspace_id(client)}"
    forget_memory()
    other = TestClient(main.app)
    assert other.get(link).status_code == 200
    assert not main.SESSIONS._items
    now = time.time()
    monkeypatch.setattr(time, "time", lambda: now + TTL + RENEW + 60)
    assert other.post(link, follow_redirects=False).status_code == 404
