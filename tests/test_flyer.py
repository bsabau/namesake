"""The printable flyer and checklist (decision 35): built only from the result's own
view, one version at a time. No test reaches Qloo or a model."""

import app.main as main
from app.views.build import build_flyer_view
from tests.test_product import client, profile, save, saved_listing  # noqa: F401

PARAMS = {"animal": "dog-02", "location": "park-slope"}


def result():
    return main.result_view("dog-02", "park-slope", None)


def test_without_a_listing_the_flyer_is_the_generic_version(client):  # noqa: F811
    view = build_flyer_view(result(), "local")
    generic = result().listing.versions[0]
    assert view.title == f"Meet {generic.name}" and view.version_label == generic.label
    assert view.other_version is None
    # The "Meet <name>." line is the heading, not a paragraph again.
    assert not view.paragraphs[0].startswith("Meet ")
    assert " ".join(view.paragraphs) in generic.copy_text


def test_the_flyer_takes_the_version_asked_for_and_links_the_other(client):  # noqa: F811
    save(saved_listing())
    shown = result()
    local = next(v for v in shown.listing.versions if v.variant == "local")
    view = build_flyer_view(shown, "local", "&ui=warm")
    assert view.name == local.name and view.version_label == local.label
    assert view.other_version.url.endswith("variant=generic&ui=warm")
    assert view.back_url == "/result?animal=dog-02&location=park-slope&ui=warm"


def test_the_checklist_is_the_results_places_and_other_ways_to_help(client):  # noqa: F811
    shown = result()
    view = build_flyer_view(shown, None)
    assert [p.name for p in view.places] == [v.name for v in shown.venues]
    assert view.places and all(p.number for p in view.places)
    assert view.other == [i.text for i in shown.plan if i.basis != "Qloo"]


def test_the_result_page_links_a_flyer_for_each_version(client):  # noqa: F811
    page = client.get("/result", params=PARAMS).text
    assert "/flyer?animal=dog-02&amp;location=park-slope&amp;variant=generic" in page
    assert "variant=local" not in page
    save(saved_listing())
    page = client.get("/result", params=PARAMS).text
    assert 'class="flyer-link local-only"' in page and 'class="flyer-link version-generic"' in page


def test_the_flyer_page_prints_both_sheets_with_the_credits(client):  # noqa: F811
    response = client.get("/flyer", params={**PARAMS, "variant": "generic"})
    assert response.status_code == 200
    html = response.text
    assert html.index('data-role="flyer"') < html.index('data-role="flyer-checklist"')
    assert "/static/flyer.css" in html and "Taste data from the Qloo API" in html


def test_a_flyer_for_an_animal_not_kept_is_a_404(client):  # noqa: F811
    assert client.get("/flyer", params={"animal": "added-gone"}).status_code == 404
