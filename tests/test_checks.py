"""Unit tests for the plain-code checks on the agent's listing."""

import pytest

from app.agent.checks import (
    check_bio,
    check_hook,
    check_name,
    fact_keys,
    is_bully_type,
    syllables,
)
from app.animals import Animal


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
        "image": "test-01.jpg",
    }
    return Animal.model_validate({**data, **overrides})


def name(name: str, *, source="pet", reference_kind="character", strict=False) -> list[str]:
    return check_name(name, source=source, reference_kind=reference_kind, strict=strict)


# syllables


def test_syllables_counts_the_obvious_cases():
    assert syllables("Max") == 1
    assert syllables("Bingo") == 2
    assert syllables("Clementine") == 3


def test_syllables_never_returns_zero():
    assert syllables("Mr") == 1
    assert syllables("Dr") == 1


# is_bully_type


def test_a_broad_headed_dog_is_bully_type():
    assert is_bully_type(animal(look="stocky, broad head, short coat"))


def test_a_cat_with_the_same_look_is_not_bully_type():
    assert not is_bully_type(animal(species="cat", look="stocky, broad head, short coat"))


def test_a_plain_terrier_is_not_bully_type():
    assert not is_bully_type(animal(look="small terrier, wiry coat"))


def test_a_staffordshire_is_bully_type():
    assert is_bully_type(animal(look="Staffordshire Bull Terrier"))


# fact_keys


def test_fact_keys_covers_temperament_look_and_each_fact():
    assert fact_keys(animal()) == {"temperament", "look", "fact:0", "fact:1"}


def test_fact_keys_adds_only_checks_that_are_not_unknown():
    keys = fact_keys(animal(checks={"good_with_children": "yes", "good_with_dogs": "no"}))
    assert "check:good_with_children" in keys
    assert "check:good_with_dogs" in keys
    assert "check:house_trained" not in keys
    assert not any(k.startswith("check:") for k in fact_keys(animal()))


# check_name


def test_a_clean_short_name_passes():
    assert name("Bingo") == []


def test_a_pet_title_name_still_passes_the_strict_screen():
    assert name("Bingo", source="pet", strict=True) == []


@pytest.mark.parametrize("bad", ["Killer", "KILLER", "killer"])
def test_a_blocklisted_word_fails_case_insensitively(bad):
    problems = name(bad)
    assert problems == [f"name {bad!r} contains 'killer'"]


def test_more_than_three_syllables_fails():
    assert syllables("Evangeline") == 4
    assert name("Evangeline") == ["name 'Evangeline' has 4 syllables; use one to three"]


def test_non_letters_fail():
    assert name("Bingo7") == ["name 'Bingo7' must be letters only, at most 14 characters"]


def test_more_than_fourteen_characters_fails():
    problems = name("Bartholomewjones")
    assert any("letters only" in p for p in problems)


def test_a_person_reference_fails():
    assert name("Bingo", reference_kind="person") == [
        "name 'Bingo' refers to a real person; use a character or object"
    ]


def test_the_strict_screen_rejects_a_non_pet_source():
    assert name("Bingo", source="show", strict=True) == [
        "name 'Bingo': for this dog use only names drawn from the pet-themed titles"
    ]


def test_the_non_strict_screen_allows_a_non_pet_source():
    assert name("Bingo", source="show") == []


# check_bio


def test_a_clean_bio_passes():
    assert check_bio(animal(), [("Bingo knows basic commands.", ["fact:0"])]) == []


def test_a_sentence_citing_no_fact_fails():
    assert check_bio(animal(), [("Bingo is a dog.", [])]) == ["bio sentence 1 cites no fact"]


def test_a_sentence_citing_an_unknown_fact_fails():
    problems = check_bio(animal(), [("Bingo knows basic commands.", ["fact:9"])])
    assert problems == ["bio sentence 1 cites facts that do not exist: ['fact:9']"]


def test_a_bio_over_one_hundred_and_fifty_words_fails():
    long_text = " ".join(["word"] * 155)
    assert check_bio(animal(), [(long_text, ["fact:0"])]) == [
        "bio is 155 words; keep it to 150 or fewer"
    ]


def test_first_person_fails():
    problems = check_bio(animal(), [("I would like my own bed.", ["fact:0"])])
    assert "write the bio in the third person" in problems


def test_mentioning_children_when_the_check_is_unknown_fails():
    problems = check_bio(animal(), [("Bingo is good with children.", ["fact:0"])])
    assert "the bio mentions 'children', which the shelter has not confirmed" in problems


def test_mentioning_house_training_when_the_check_is_unknown_fails():
    problems = check_bio(animal(), [("Bingo is house-trained.", ["fact:0"])])
    assert "the bio mentions 'house-trained', which the shelter has not confirmed" in problems


def test_mentioning_a_bite_when_the_check_is_unknown_fails():
    problems = check_bio(animal(), [("Bingo has a bite on record.", ["fact:0"])])
    assert "the bio mentions 'bite', which the shelter has not confirmed" in problems


def test_backstory_fails():
    problems = check_bio(animal(), [("Bingo came in as a stray.", ["fact:0"])])
    assert "leave out backstory ('stray')" in problems


def test_pity_and_urgency_fails():
    problems = check_bio(animal(), [("Bingo deserves a last chance.", ["fact:0"])])
    assert "leave out pity and urgency ('last chance')" in problems


def test_a_recorded_bite_must_be_stated():
    a = animal(checks={"bite_history": "yes"})
    assert check_bio(a, [("Bingo knows basic commands.", ["fact:0"])]) == [
        "the shelter recorded a bite; the bio must say so plainly"
    ]


def test_a_topic_is_allowed_once_its_check_is_yes():
    a = animal(checks={"good_with_children": "yes"})
    sentence = ("She is good with children.", ["check:good_with_children"])
    assert check_bio(a, [sentence]) == []


# check_hook


def test_a_clean_hook_passes():
    assert check_hook("Bingo is a dog in Example Dog Show.") == []


def test_a_hook_with_two_sentences_fails():
    assert check_hook("Bingo is a dog. He lives in Example Dog Show.") == [
        "the hook must be one sentence"
    ]


def test_a_hook_over_twenty_five_words_fails():
    hook = " ".join(["Bingo", *["in"] * 25])
    assert check_hook(hook) == ["the hook must be 25 words or fewer"]


def test_a_trait_word_fails():
    assert check_hook("Bingo is a playful dog in Example Dog Show.") == [
        "the hook describes temperament ('playful'); keep it to the name"
    ]


def test_a_taste_claim_fails():
    assert check_hook("Bingo is a dog for fans of Example Dog Show.") == [
        "the hook makes a claim about tastes ('fans')"
    ]


def test_a_loves_claim_fails():
    problems = check_hook("Bingo loves Example Dog Show.")
    assert any("tastes" in p for p in problems)


# Regression: whole-word matching, after OpenCode found substring false positives.
@pytest.mark.parametrize("name", ["Edward", "Warren", "Killian", "Deadwood"])
def test_innocent_names_containing_a_blocked_word_pass(name):
    assert check_name(name, source="pet", reference_kind="character", strict=False) == []


def test_a_word_containing_nip_is_not_a_bite():
    pet = animal(facts=["likes turnip-shaped toys"])
    assert check_bio(pet, [("She likes turnip-shaped toys.", ["fact:0"])]) == []


def test_an_abbreviation_does_not_split_the_hook():
    assert check_hook("Named after Mr. Bean, the character.") == []


@pytest.mark.parametrize("word", ["loved", "loving"])
def test_other_forms_of_love_are_taste_claims(word):
    assert any("claim about tastes" in p for p in check_hook(f"Max is {word} in the films."))


@pytest.mark.parametrize("role", ["villain", "tragic"])
def test_a_villain_or_tragic_role_fails(role):
    problems = check_name(
        "Rex",
        source="pet",
        reference_kind="character",
        strict=False,
        reference="Rex",
        reference_role=role,
    )
    assert problems == [f"name 'Rex' refers to a {role} character"]


def test_a_famous_villain_in_the_reference_fails():
    problems = check_name(
        "Kitty", source="pet", reference_kind="character", strict=False, reference="Cruella's cat"
    )
    assert any("'cruella'" in p for p in problems)


def test_a_restatement_passes_and_an_invention_fails():
    pet = animal()
    assert check_bio(pet, [("She knows basic commands.", ["fact:0"])]) == []
    problems = check_bio(pet, [("She knows basic commands and surfs at weekends.", ["fact:0"])])
    assert any("says things its facts do not" in p for p in problems)
