"""A visitor's workspace: kept on disk for 7 days, opened by its link, edited and
emptied by its visitor only (decision 34). No test reaches Qloo or a model."""

import time

import pytest
from fastapi.testclient import TestClient

import app.main as main
from app.workspace import TTL, Workspaces
from tests.test_product import ADDED, add, added_id, client, profile  # noqa: F401

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
    response = other.get(link, follow_redirects=False)
    assert response.status_code == 303 and response.headers["location"] == "/"
    assert animal_id in other.get("/").text


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
    monkeypatch.setattr(time, "time", lambda: now + TTL + 60)
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
    response = client.post(
        "/animals/remove", data={"remove": animal_id, "location": "park-slope"},
        follow_redirects=False,
    )  # fmt: skip
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
    stranger.post("/animals/remove", data={"remove": animal_id, "location": "park-slope"})
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
    assert "Anyone with the link can open it." in page
