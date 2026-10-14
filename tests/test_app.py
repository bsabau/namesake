from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_start_page_shows_all_twelve_animals(roster):
    html = client.get("/").text
    assert len(roster.animals) == 12
    for animal in roster.animals:
        assert f'id="{animal.id}"' in html
        assert f"/static/animals/{animal.image}" in html


def test_start_page_shows_the_litter(roster):
    html = client.get("/").text
    assert 'id="litter-group"' in html


def test_photos_are_served():
    response = client.get("/static/animals/cat-01.jpg")
    assert response.status_code == 200
    assert response.headers["content-type"] == "image/jpeg"
