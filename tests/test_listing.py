import pytest

from app.animals import Animal, Checks
from app.listing import cautions, fact_sentence, set_aside, templated_listing


def animal(**overrides) -> Animal:
    data = {
        "id": "test-01",
        "species": "dog",
        "group": "adult dog",
        "sex": "female",
        "age": "4 years",
        "look": "large mixed breed, short brindle coat",
        "temperament": "strong but gentle",
        "facts": ["knows basic commands", "fine with calm adults"],
        "history": ["in the shelter for eight months", "came in as a stray"],
        "image": "test-01.jpg",
    }
    return Animal.model_validate({**data, **overrides})


def test_every_sentence_traces_to_a_recorded_fact(roster):
    for a in roster.animals:
        listing = templated_listing(a)
        sources = {s.source for s in listing.sentences}
        allowed = {"temperament", "look"} | {f"fact:{i}" for i in range(len(a.facts))}
        allowed |= {f"check:{k}" for k, v in a.checks.model_dump().items() if v != "unknown"}
        assert sources <= allowed, a.id
        assert {f"fact:{i}" for i in range(len(a.facts))} <= sources, a.id


def test_behaviour_toward_people_comes_first():
    assert templated_listing(animal()).sentences[0].source == "temperament"


def test_backstory_is_never_printed(roster):
    for a in roster.animals + [animal()]:
        text = templated_listing(a).text.lower()
        for line in a.history:
            assert line.lower() not in text


def test_unknown_checks_are_not_mentioned():
    text = templated_listing(animal()).text.lower()
    for word in ["children", "cats", "house-trained", "bite"]:
        assert word not in text


def test_a_bite_on_record_is_stated_plainly():
    text = templated_listing(animal(checks=Checks(bite_history="yes"))).text
    assert "She has a bite on record; ask the shelter for the details." in text
    assert (
        "She has no bite on record."
        in templated_listing(animal(checks=Checks(bite_history="no"))).text
    )


def test_third_person_pronouns_follow_sex():
    assert templated_listing(animal(sex="male")).text.startswith("Staff describe him")
    unknown = templated_listing(animal(sex="unknown", checks=Checks(house_trained="yes"))).text
    assert "They are house-trained." in unknown and "Staff describe them" in unknown


@pytest.mark.parametrize(
    ("fact", "expected"),
    [
        ("knows basic commands", "She knows basic commands."),
        ("fine with calm adults", "She is fine with calm adults."),
        ("fearless with new people", "She is fearless with new people."),
        ("already walks well on a lead", "She already walks well on a lead."),
        (
            "not suited to being left alone all day",
            "She is not suited to being left alone all day.",
        ),
    ],
)
def test_fact_sentences(fact, expected):
    assert fact_sentence(fact, "she", "is") == expected


def test_ages_read_naturally():
    assert "a 10-week-old female dog" in templated_listing(animal(age="10 weeks")).text


def test_a_recorded_backstory_fact_is_set_aside_from_the_template():
    # 22 October walkthrough: a typed "was brought in as a stray" reached the listing.
    pet = animal(
        facts=["chases feather toys", "was brought in as a stray", "feels lonely at night"]
    )
    assert set_aside(pet) == {
        "fact:1": "was brought in as a stray",
        "fact:2": "feels lonely at night",
    }
    listing = templated_listing(pet)
    assert "stray" not in listing.text and "lonely" not in listing.text
    assert "chases feather toys" in listing.text


def test_a_caution_is_never_set_aside_even_with_a_past():
    pet = animal(facts=["bit a previous owner when startled"])
    assert set_aside(pet) == {}
    assert "bit a previous owner when startled" in templated_listing(pet).text
    assert "bit a previous owner when startled" in cautions(pet)
