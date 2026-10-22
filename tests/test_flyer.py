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


def test_the_flyer_prints_the_name_chosen_on_the_page(client):  # noqa: F811
    save(saved_listing())
    shown = main.result_view("dog-02", "park-slope", None)
    second = shown.name.options[1]
    view = build_flyer_view(shown, "local", name=second.name)
    assert view.title == f"Meet {second.name}"
    assert "\n\n".join(view.paragraphs) in second.copy_text
    # A name that is not an option is ignored: the version's own name prints.
    assert build_flyer_view(shown, "local", name="Rex").name == shown.name.options[0].name
    page = client.get("/result", params=PARAMS).text
    assert f'data-flyer="{second.flyer_url.replace("&", "&amp;")}' in page
    flyer = client.get("/flyer", params={**PARAMS, "variant": "local", "name": second.name})
    assert f"Meet {second.name}" in flyer.text


def test_the_flyer_keeps_every_caution_the_listing_carries(client):  # noqa: F811
    save(saved_listing())
    shown = main.result_view("dog-02", "park-slope", None)
    for variant in ("generic", "local"):
        text = " ".join(build_flyer_view(shown, variant).paragraphs)
        assert all(phrase in text for phrase in shown.listing.must_keep)


def test_with_no_places_the_checklist_gives_the_results_own_reason(client):  # noqa: F811
    shown = result().model_copy(update={"venues": [], "venues_empty": "None suits this dog."})
    view = build_flyer_view(shown, None)
    assert view.checklist_note == "None suits this dog." and not view.places


def test_each_place_carries_namesakes_comparison(client):  # noqa: F811
    shown = result()
    view = build_flyer_view(shown, None)
    assert [p.badge for p in view.places] == [v.badge for v in shown.venues]
    page = client.get("/flyer", params=PARAMS).text
    assert f"Namesake: {shown.venues[0].badge}" in page


def test_a_result_with_no_version_to_print_has_no_flyer(client):  # noqa: F811
    shown = result()
    versions = [v.model_copy(update={"available": False}) for v in shown.listing.versions]
    empty = shown.model_copy(
        update={"listing": shown.listing.model_copy(update={"versions": versions})}
    )
    assert build_flyer_view(empty, "generic") is None


def test_page_one_says_the_animal_is_a_sample(client):  # noqa: F811
    html = client.get("/flyer", params=PARAMS).text
    sheet = html[html.index('data-role="flyer"') : html.index('data-role="flyer-checklist"')]
    assert result().credits.photos in sheet


def test_the_checklist_points_to_nothing_the_flyer_lacks(client):  # noqa: F811
    empty = "Every place Qloo listed here was screened out; the Why panel names them."
    shown = result().model_copy(update={"venues": [], "venues_empty": empty})
    assert build_flyer_view(shown, None).checklist_note == (
        "Every place Qloo listed here was screened out."
    )


def test_without_a_version_to_print_the_route_is_a_404(client, monkeypatch):  # noqa: F811
    shown = result()
    versions = [v.model_copy(update={"available": False}) for v in shown.listing.versions]
    empty = shown.model_copy(
        update={"listing": shown.listing.model_copy(update={"versions": versions})}
    )
    monkeypatch.setattr(main, "result_view", lambda *a: empty)
    assert client.get("/flyer", params=PARAMS).status_code == 404
