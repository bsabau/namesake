"""The templated listing: plain sentences built only from an animal's recorded facts.

It is the generic version of every listing and the fallback when the agent's
text fails its checks. Each sentence records where it came from, so a check can
prove nothing was invented. Backstory (`Animal.history`) is never used.
"""

import re

from pydantic import BaseModel

from app.animals import Animal, Checks

# Third-person verbs that start some facts ("knows basic commands"); adjectives
# ending in "s" are listed so they take "is" instead.
ADJECTIVES_ENDING_IN_S = {"fearless", "nervous", "anxious", "curious", "gorgeous", "famous"}

CHECK_SENTENCES: dict[str, dict[str, str]] = {
    "good_with_children": {
        "yes": "{they} {is} good with children.",
        "no": "{they} {is} not a match for a home with children.",
    },
    "good_with_dogs": {
        "yes": "{they} {gets} on with dogs.",
        "no": "{they} would do best in a home without other dogs.",
    },
    "good_with_cats": {
        "yes": "{they} {gets} on with cats.",
        "no": "{they} would do best in a home without cats.",
    },
    "house_trained": {
        "yes": "{they} {is} house-trained.",
        "no": "{they} {is} not house-trained yet.",
    },
    "bite_history": {
        "yes": "{they} {has} a bite on record; ask the shelter for the details.",
        "no": "{they} {has} no bite on record.",
    },
}


# Words that place a fact in the animal's past or plead for it. The listing describes the
# animal as it is now, so a recorded fact with one of them is set aside: neither the
# template nor Namesake's AI restates it, and the page names it (decision 36). Matched
# with a space either side, so "sad " is a word, not the start of "saddle".
BACKSTORY = (
    "stray", "surrender", "abandon", "previous owner", "former owner", "rescued from",
    "in the shelter for", "months in", "years in the shelter", "waiting for",
    "could no longer care",
)  # fmt: skip
PITY_URGENCY = (
    "last chance", "urgent", "running out", "euthan", "death row", "desperate",
    "heartbroken", "forgotten", "overlooked", "sad ", "lonely",
)  # fmt: skip


class Sentence(BaseModel):
    text: str
    # What the sentence restates: "temperament", "look", "fact:<n>" or "check:<field>".
    source: str


# The length a bio should reach. The template never pads: when the recorded facts
# fall short, the listing stays short and says so.
MIN_WORDS = 75
MAX_WORDS = 150


class Listing(BaseModel):
    sentences: list[Sentence]

    @property
    def too_short(self) -> bool:
        return self.word_count < MIN_WORDS

    @property
    def text(self) -> str:
        return " ".join(s.text for s in self.sentences)

    @property
    def word_count(self) -> int:
        return len(self.text.split())


def pronouns(sex: str | None) -> dict[str, str]:
    if sex == "female":
        return {"they": "she", "is": "is", "gets": "gets", "has": "has"}
    if sex == "male":
        return {"they": "he", "is": "is", "gets": "gets", "has": "has"}
    return {"they": "they", "is": "are", "gets": "get", "has": "have"}


def _capitalise(text: str) -> str:
    return text[:1].upper() + text[1:]


def age_phrase(age: str) -> str:
    """'4 years' -> '4-year-old'."""
    match = re.fullmatch(r"(\d+)\s+(year|month|week)s?", age.strip())
    if not match:
        return age
    return f"{match.group(1)}-{match.group(2)}-old"


YOUNG = {"dog": "puppy", "cat": "kitten"}
UNDER_A_YEAR = {"week": 52, "month": 12}


def stage_for(species: str, age: str) -> str | None:
    """'puppy' or 'kitten' when the recorded age is under a year ("10 weeks", "4 months"),
    else None. One rule for the start page's grouping and for the listing checks."""
    match = re.fullmatch(r"(\d+)\s+(year|month|week)s?", age.strip().lower())
    if match is None or match.group(2) == "year":
        return None
    if int(match.group(1)) >= UNDER_A_YEAR[match.group(2)]:
        return None
    return YOUNG.get(species)


def life_stage(animal: Animal) -> str | None:
    return stage_for(animal.species, animal.age)


def look_text(animal: Animal) -> str:
    """The animal's recorded look as the agent sees it and the checks compare against."""
    return f"{age_phrase(animal.age)} {animal.sex} {animal.species}: {animal.look}"


def fact_sentence(fact: str, they: str, is_: str) -> str:
    first = fact.split()[0].lower()
    starts_with_verb = first == "already" or (
        first.endswith("s") and first not in ADJECTIVES_ENDING_IN_S
    )
    body = f"{they} {fact}" if starts_with_verb else f"{they} {is_} {fact}"
    return _capitalise(body.rstrip(".")) + "."


def check_sentences(checks: Checks, p: dict[str, str]) -> list[Sentence]:
    out = []
    for field, answers in CHECK_SENTENCES.items():
        answer = getattr(checks, field)
        if answer in answers:
            out.append(
                Sentence(text=_capitalise(answers[answer].format(**p)), source=f"check:{field}")
            )
    return out


def templated_listing(animal: Animal) -> Listing:
    p = pronouns(animal.sex)
    they = p["they"]
    sentences = [
        # Behaviour toward people first, in the shelter's own words.
        Sentence(
            text=f"Staff describe {('her' if they == 'she' else 'him' if they == 'he' else 'them')}"
            f" as {animal.temperament.rstrip('.')}.",
            source="temperament",
        ),
        Sentence(
            text=_capitalise(
                f"{they} {p['is']} a {age_phrase(animal.age)} {animal.sex or ''} "
                f"{animal.species}: {animal.look}."
            ).replace("  ", " "),
            source="look",
        ),
    ]
    left_out = set_aside(animal)
    sentences += [
        Sentence(text=fact_sentence(fact, they, p["is"]), source=f"fact:{i}")
        for i, fact in enumerate(animal.facts)
        if f"fact:{i}" not in left_out
    ]
    sentences += check_sentences(animal.checks, p)
    return Listing(sentences=sentences)


# The generic version's name: a common pet name from this fixed list, never from Qloo,
# so the generic and local versions differ only in what Qloo adds (decisions.md #8).
# None reads as a human first name, which keeps the list safe for every dog.
GENERIC_NAMES = (
    "Biscuit", "Pepper", "Peanut", "Maple", "Mochi", "Waffles", "Pickles", "Noodle",
    "Clover", "Pumpkin", "Nugget", "Pretzel", "Sprout", "Acorn", "Toffee", "Bean",
    "Button", "Sesame", "Cocoa", "Juniper",
)  # fmt: skip


def generic_name(seed: int, taken: set[str] | frozenset[str] = frozenset()) -> str | None:
    """A name from GENERIC_NAMES, starting at `seed` and skipping names already taken;
    None when every one is taken, rather than a name another animal has."""
    for i in range(len(GENERIC_NAMES)):
        name = GENERIC_NAMES[(seed + i) % len(GENERIC_NAMES)]
        if name.lower() not in taken:
            return name
    return None


# Recorded words that warn an adopter: a volunteer's edit may reword the rest, never drop these.
# Stems, so every form counts: "guarded", "scratching", "lunges".
CAUTION_WORDS = re.compile(
    r"\b(bit|bit(e|es|ten|ing)|nip\w*|guard\w*|growl\w*|snap\w*|snarl\w*|scratch\w*|"
    r"swat\w*|lung(e|es|ed|ing)|aggress\w*|resource)\b",
    re.IGNORECASE,
)


def _plain(text: str) -> str:
    return " ".join(text.lower().replace("’", "'").split()).rstrip(".")


def cautions(animal: Animal) -> list[str]:
    """What every version of this animal's listing must still say, word for word.

    The shelter's confirmed "no" answers and a bite on record, as the fixed sentences,
    plus any recorded phrase about biting, guarding, growling, snapping or scratching.
    """
    required = [
        s.text
        for s in check_sentences(animal.checks, pronouns(animal.sex))
        if getattr(animal.checks, s.source.removeprefix("check:"))
        == ("yes" if s.source == "check:bite_history" else "no")
    ]
    for phrase in [animal.temperament, *animal.facts]:
        for part in re.split(r"[,;:]", phrase):
            if CAUTION_WORDS.search(part):
                required.append(part.strip())
    return required


def missing_cautions(animal: Animal, text: str) -> list[str]:
    """The cautions an edited listing dropped or reworded."""
    plain = _plain(text)
    return [c for c in cautions(animal) if _plain(c) not in plain]


def past_or_pity(text: str) -> list[str]:
    """The backstory and pity phrases in `text`."""
    lowered = f" {text.lower()} "
    return [phrase.strip() for phrase in BACKSTORY + PITY_URGENCY if phrase in lowered]


def set_aside(animal: Animal) -> dict[str, str]:
    """The recorded facts no listing restates, by key ("fact:<n>"): backstory or pity.

    A fact that is also a caution stays, since a caution is stated every time."""
    return {
        f"fact:{i}": fact
        for i, fact in enumerate(animal.facts)
        if past_or_pity(fact) and not CAUTION_WORDS.search(fact)
    }
