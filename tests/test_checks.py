"""Unit tests for the plain-code checks on the agent's listing."""

import pytest

from app.agent.checks import (
    check_bio,
    check_character,
    check_hook,
    check_name,
    check_title,
    check_why,
    fact_keys,
    is_bully_type,
    reference_text,
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


def name(name: str, *, source="pet", role="character", strict=False) -> list[str]:
    return check_name(name, source=source, role=role, strict=strict)


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
    assert name("Bingo", role="person") == [
        "name 'Bingo' refers to a real person; use a character or object"
    ]


@pytest.mark.parametrize("bad", ["Oprah", "Adele"])
def test_a_famous_person_fails_by_name(bad):
    assert name(bad) == [f"name {bad!r} refers to a real person; use a character or object"]


def test_a_famous_person_in_the_reference_fails():
    problems = check_name(
        "Tay", source="local", role="character", strict=False, reference="Taylor Swift"
    )
    assert any("real person" in p for p in problems)


@pytest.mark.parametrize(
    ("bad", "reference", "word"),
    [
        ("Moses", "Moses", "moses"),
        ("Biscuit", "Biscuit the Thug", "thug"),
        ("Duke", "MAGA Duke", "maga"),
    ],
)
def test_an_identity_coded_name_or_reference_fails(bad, reference, word):
    problems = check_name(bad, source="local", role="character", strict=False, reference=reference)
    # The message leaves the word out: the step log is shown to visitors.
    assert problems == [f"name {bad!r} is coded to a religion, race or political identity"]


def test_identity_words_match_whole_words_only():
    # "Christopher" is not "christ", "Mason" not "moses".
    assert name("Christopher") == []
    assert check_name("Mao", source="pet", role="cat", strict=False, reference="Mao") != []
    assert name("Mason") == []


# check_title


def test_a_character_from_a_title_about_real_people_fails():
    problems = check_title("Kelly", "character", "Example Morning", "A daytime talk show.")
    assert problems == [
        "name 'Kelly': Example Morning is about real people ('talk show'), so a name from "
        "it must be an animal's own"
    ]


@pytest.mark.parametrize("role", ["title", "object", "person"])
def test_only_an_animal_role_may_come_from_a_title_about_real_people(role):
    assert check_title("Max", role, "Example Dog Life", "A documentary about a dog.") != []


def test_an_animal_from_a_title_about_real_people_passes():
    assert check_title("Marley", "dog", "Example Memoir", "A memoir about a family dog.") == []


def test_a_fiction_title_passes():
    assert check_title("Bingo", "character", "Example Dog Show", "An animated series.") == []
    assert check_title("Bingo", "character", "Example Dog Show", None) == []


def test_a_cast_name_in_the_description_passes():
    # The dry run on saved listings: a voice actor named Harris coded a cartoon about cats.
    described = "An animated film with the voices of Example Harris and Example Pope."
    assert check_title("Marie", "kitten", "Example Cats", described) == []
    assert check_title("Marie", "kitten", "Harris and the Cats", None) != []
    # Codex: first names too.
    voiced = "With the voices of Mohammed Example, Jesús Example and Shiva Example."
    assert check_title("Rex", "dog", "Example Dogs", voiced) == []


def test_a_plural_political_word_fails():
    # Codex: whole-word matching let "Republicans" through.
    assert check_title("Rex", "dog", "Republicans and Their Dogs", None) != []
    assert check_title("Rex", "dog", "Example", "A satire about communists.") != []


def test_a_title_coded_to_an_identity_fails_for_every_role():
    problems = check_title("Rex", "dog", "Example Film", "A dog in the life of Christ.")
    assert problems == [
        "name 'Rex': Example Film is coded to a religion, race or political identity; "
        "use another title"
    ]


def test_the_strict_screen_rejects_a_non_pet_source():
    assert name("Bingo", source="show", strict=True) == [
        "name 'Bingo': for this dog use only names drawn from the pet-themed or lookalike titles"
    ]


def test_the_non_strict_screen_allows_a_non_pet_source():
    assert name("Bingo", source="show") == []


# check_bio: every sentence grounded in the facts it cites, every fact used

FACTS = [("She knows basic commands.", ["fact:0"]), ("She is fine with calm adults.", ["fact:1"])]
TEMPERAMENT = ("She is strong but gentle.", ["temperament"])


def clean_bio():
    return [TEMPERAMENT, *FACTS]


def test_a_clean_bio_passes():
    assert check_bio(animal(), clean_bio()) == []


def test_a_sentence_citing_no_fact_fails():
    assert "bio sentence 1 cites no fact" in check_bio(animal(), [("She is here.", []), *FACTS])


def test_check_keys_are_not_the_agents_to_cite():
    problems = check_bio(
        animal(checks={"bite_history": "yes"}), [*clean_bio(), ("x", ["check:bite_history"])]
    )
    assert any("cites keys it may not use" in p for p in problems)


def test_a_missing_fact_fails():
    problems = check_bio(animal(), [TEMPERAMENT, FACTS[0]])
    assert any("leaves out fact:1" in p for p in problems)


def test_a_bio_over_one_hundred_and_fifty_words_fails():
    long = ("She knows basic commands. " * 40, ["fact:0"])
    problems = check_bio(animal(), [TEMPERAMENT, long, FACTS[1]])
    assert any("keep it to 150 or fewer" in p for p in problems)


def test_first_person_fails():
    problems = check_bio(animal(), [("I know basic commands.", ["fact:0"]), TEMPERAMENT, FACTS[1]])
    assert any("third person" in p for p in problems)


@pytest.mark.parametrize(
    ("sentence", "word"),
    [
        ("She is good with children.", "children"),
        ("She is house-trained.", "house-trained"),
        ("She has never bitten.", "bitten"),
    ],
)
def test_check_topics_are_left_to_the_confirmed_checks(sentence, word):
    problems = check_bio(animal(), [(sentence, ["temperament"]), *FACTS])
    assert any(f"mentions {word!r}" in p for p in problems)


def test_a_check_topic_is_fine_when_the_fact_itself_says_it():
    pet = animal(facts=["knows basic commands", "fine with calm adults", "good with children"])
    bio = [*clean_bio(), ("She is good with children.", ["fact:2"])]
    assert check_bio(pet, bio) == []


def test_backstory_fails():
    problems = check_bio(animal(), [("She came in as a stray.", ["fact:0"]), TEMPERAMENT, FACTS[1]])
    assert any("leave out backstory ('stray')" in p for p in problems)


def test_pity_and_urgency_fails():
    problems = check_bio(animal(), [("Her last chance.", ["fact:0"]), TEMPERAMENT, FACTS[1]])
    assert any("leave out pity and urgency ('last chance')" in p for p in problems)


def test_an_added_negation_fails():
    problems = check_bio(animal(), [("She is not gentle.", ["temperament"]), *FACTS])
    assert any("adds a negation" in p for p in problems)


def test_a_contradicting_word_fails():
    problems = check_bio(animal(), [("She is aggressive.", ["temperament"]), *FACTS])
    assert any("says things its facts do not: ['aggressive']" in p for p in problems)


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
    assert check_name(name, source="pet", role="character", strict=False) == []


def test_a_word_containing_nip_is_not_a_bite():
    pet = animal(facts=["likes turnip-shaped toys"])
    bio = [TEMPERAMENT, ("She likes turnip-shaped toys.", ["fact:0"])]
    assert check_bio(pet, bio) == []


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
        role="character",
        strict=False,
        reference="Rex",
        reference_role=role,
    )
    assert problems == [f"name 'Rex' refers to a {role} character"]


def test_a_famous_villain_in_the_reference_fails():
    problems = check_name(
        "Kitty", source="pet", role="character", strict=False, reference="Cruella's cat"
    )
    assert any("'cruella'" in p for p in problems)


def test_a_restatement_passes_and_an_invention_fails():
    pet = animal()
    assert check_bio(pet, clean_bio()) == []
    surfs = ("She knows basic commands and surfs at weekends.", ["fact:0"])
    problems = check_bio(pet, [TEMPERAMENT, surfs, FACTS[1]])
    assert any("says things its facts do not" in p for p in problems)


def test_a_reason_may_only_restate_the_facts():
    assert check_why(animal(), "It suits a dog who knows basic commands.", "Bingo") == []
    problems = check_why(animal(), "She adores toddlers.", "Bingo")
    assert any("toddlers" in p for p in problems)


def test_a_weapon_in_the_reference_fails_even_for_an_object_name():
    problems = check_name(
        "Rifle",
        source="pet",
        role="object",
        strict=True,
        reference="a rifle in Example Dog Show",
    )
    assert problems == ["name 'Rifle' contains 'rifle'"]


def test_a_character_is_a_plain_name():
    assert check_character("Thomas O'Malley", "cat") == []
    assert check_character("Mr. Peanutbutter", "dog") == []
    assert check_character("ignored for a title", "title") == []
    assert any("claim about tastes" in p for p in check_character("a dog who loves", "dog"))


def test_references_are_written_by_code():
    assert reference_text("Bingo", "puppy", "Bluey") == "Bingo, a puppy in Bluey"
    assert reference_text("Rubble", "character", "PAW Patrol") == "Rubble in PAW Patrol"
    assert reference_text("x", "title", "Lassie") == "Lassie"


def test_reordered_words_that_reverse_a_fact_fail():
    pet = animal(facts=["guards food but not toys", "fine with calm adults"])
    bio = [
        ("She is strong but gentle.", ["temperament"]),
        ("She guards toys but not food.", ["fact:0"]),
        ("She is fine with calm adults.", ["fact:1"]),
    ]
    assert any("changes the wording of fact:0" in p for p in check_bio(pet, bio))
    bio[1] = ("She guards food but not toys.", ["fact:0"])
    assert check_bio(pet, bio) == []


def test_words_slipped_into_a_fact_fail():
    # Regression (Codex, milestone 3): "but not when she has toys" softened a guarding fact.
    pet = animal(facts=["guards food but not toys", "fine with calm adults"])
    bio = [
        ("She is strong but gentle.", ["temperament"]),
        ("She guards food but not when she has toys.", ["fact:0"]),
        ("She is fine with calm adults.", ["fact:1"]),
    ]
    assert any("changes the wording of fact:0" in p for p in check_bio(pet, bio))


def test_a_description_is_not_a_character_name():
    # Regression (Codex, milestone 3): "Bingo who enjoys cuddles" reached the hook.
    problems = check_character("Bingo who enjoys cuddles", "dog")
    assert any("must be a proper name" in p for p in problems)
    assert check_character("Puss in Boots", "cat") == []


def test_reference_text_uses_an_before_a_vowel():
    from app.agent.checks import reference_text

    assert reference_text("Roquefort", "animal", "Example Film") == (
        "Roquefort, an animal in Example Film"
    )
    assert reference_text("Bingo", "dog", "Example Show") == "Bingo, a dog in Example Show"


def test_puppy_or_kitten_only_when_the_recorded_age_says_so(roster):
    # Codex: "She is a puppy" passed for the 4-year-old lead dog.
    from app.agent.checks import check_bio, check_grounded
    from app.listing import life_stage, stage_for

    adult = roster.get("dog-02")
    problems = check_bio(
        adult,
        [
            (
                "She is a puppy: strong but gentle and leans on people for attention.",
                ["temperament"],
            ),
            ("She needs an owner comfortable with a big dog.", ["fact:0"]),
            ("She knows basic commands.", ["fact:1"]),
        ],
        extra_words=0,
    )
    assert any("puppy" in p for p in problems)
    assert life_stage(adult) is None

    # Allowed, never required, for a young animal (Flash: the label had become mandatory).
    kitten = roster.get("kitten-01")
    look = "She is a 10-week-old female cat: grey tabby."
    with_word = "She is a 10-week-old female cat, a kitten: grey tabby."
    if kitten.sex == "male":
        look, with_word = (
            t.replace("She", "He").replace("female", "male") for t in (look, with_word)
        )
    assert check_grounded(kitten, look, ["look"], "x") == []
    assert check_grounded(kitten, with_word, ["look"], "x") == []

    # Under a year in weeks or months, never a year or more (DeepSeek, muse, Grok: 52 weeks).
    assert [stage_for("dog", a) for a in ("10 weeks", "51 weeks", "52 weeks", "100 weeks")] == [
        "puppy", "puppy", None, None,
    ]  # fmt: skip
    assert [stage_for("cat", a) for a in ("4 months", "11 months", "12 months", "2 years")] == [
        "kitten", "kitten", None, None,
    ]  # fmt: skip
