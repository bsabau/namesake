"""Plain-code checks on the agent's listing: the rules in AGENTS.md, made testable.

Each check returns a list of problems in words the model can act on. An empty
list means the draft passes.
"""

import re

from app.animals import Animal
from app.listing import MAX_WORDS

# Looks that mark a bully-type dog: these get the strictest name screen, because a
# measured adoption penalty fell on names perceived as Black for pit-bull-type dogs.
BULLY_MARKERS = ("broad head", "pit bull", "pitbull", "bully", "staffordshire", "amstaff")

# Whole words only, with their common forms: "Killer" is out, "Killian" and "Edward" are not.
NAME_BLOCKLIST = (
    "kill", "killer", "killa", "death", "deadly", "dead", "gun", "guns", "gunner", "knife",
    "war", "blood", "bloody", "devil", "demon", "satan", "murder", "bomb", "bomber", "slave",
    "nazi", "venom", "rage", "psycho", "villain", "toxic", "crack", "booze", "whiskey",
    "vodka", "joker", "riot", "chaos",
)  # fmt: skip

HOOK_TRAIT_WORDS = (
    "gentle", "calm", "playful", "friendly", "loyal", "energetic", "shy", "sweet", "loving",
    "affectionate", "brave", "bold", "cuddly", "clever", "smart", "independent", "curious",
    "sleepy", "active", "quiet", "vocal", "strong", "sassy", "fierce", "wild", "lazy",
    "goofy", "silly", "cheeky", "mischievous", "adventurous", "fearless", "timid", "anxious",
)  # fmt: skip
HOOK_CLAIMS = ("fan", "fans", "fans of", "perfect for", "love", "loves", "loved", "loving")

BACKSTORY = (
    "stray", "surrender", "abandon", "previous owner", "former owner", "rescued from",
    "in the shelter for", "months in", "years in the shelter", "waiting for",
    "could no longer care",
)  # fmt: skip
PITY_URGENCY = (
    "last chance", "urgent", "running out", "euthan", "death row", "desperate",
    "heartbroken", "forgotten", "overlooked", "sad ", "lonely",
)  # fmt: skip
# Words that would state a check the shelter has not confirmed.
UNKNOWN_TOPICS = {
    "good_with_children": (
        "child",
        "children",
        "kid",
        "kids",
        "toddler",
        "toddlers",
        "family",
        "families",
    ),
    "good_with_dogs": ("other dogs", "with dogs", "dog-friendly", "dog friendly"),
    "good_with_cats": ("other cats", "with cats", "cat-friendly", "cat friendly"),
    "house_trained": ("house-trained", "housetrained", "house trained", "potty", "litter-trained"),
    "bite_history": (
        "bite",
        "bites",
        "bit",
        "bitten",
        "biting",
        "nip",
        "nips",
        "nipped",
        "nipping",
    ),
}
FIRST_PERSON = re.compile(r"\b(I|I'm|I've|I'll|me|my|mine)\b")
ABBREVIATIONS = re.compile(r"\b(Mr|Mrs|Ms|Dr|St|Jr|Sr)\.")


def find_word(text: str, words: tuple[str, ...]) -> str | None:
    """The first of `words` (or phrases) that appears in `text` as a whole word."""
    for word in words:
        if re.search(rf"(?<![a-z]){re.escape(word)}(?![a-z])", text.lower()):
            return word
    return None


def is_bully_type(animal: Animal) -> bool:
    return animal.species == "dog" and any(m in animal.look.lower() for m in BULLY_MARKERS)


def syllables(word: str) -> int:
    """A rough count, good enough to keep names short."""
    groups = re.findall(r"[aeiouy]+", word.lower())
    count = len(groups)
    if word.lower().endswith("e") and count > 1 and not word.lower().endswith(("le", "ee")):
        count -= 1
    return max(1, count)


def fact_keys(animal: Animal) -> set[str]:
    keys = {"temperament", "look"} | {f"fact:{i}" for i in range(len(animal.facts))}
    keys |= {f"check:{k}" for k, v in animal.checks.model_dump().items() if v != "unknown"}
    return keys


def check_name(name: str, *, source: str, reference_kind: str, strict: bool) -> list[str]:
    problems = []
    if not re.fullmatch(r"[A-Za-z][A-Za-z' -]{0,13}", name):
        problems.append(f"name {name!r} must be letters only, at most 14 characters")
    total = sum(syllables(w) for w in re.split(r"[ -]", name) if w)
    if total > 3:
        problems.append(f"name {name!r} has {total} syllables; use one to three")
    hit = find_word(name, NAME_BLOCKLIST)
    if hit:
        problems.append(f"name {name!r} contains {hit!r}")
    if reference_kind == "person":
        problems.append(f"name {name!r} refers to a real person; use a character or object")
    if strict and source != "pet":
        problems.append(
            f"name {name!r}: for this dog use only names drawn from the pet-themed titles"
        )
    return problems


def check_bio(animal: Animal, sentences: list[tuple[str, list[str]]]) -> list[str]:
    problems = []
    allowed = fact_keys(animal)
    text = " ".join(s for s, _ in sentences)
    lowered = f" {text.lower()} "
    for i, (_sentence, facts) in enumerate(sentences, start=1):
        if not facts:
            problems.append(f"bio sentence {i} cites no fact")
        bad = [f for f in facts if f not in allowed]
        if bad:
            problems.append(f"bio sentence {i} cites facts that do not exist: {bad}")
    words = len(text.split())
    if words > MAX_WORDS:
        problems.append(f"bio is {words} words; keep it to {MAX_WORDS} or fewer")
    if FIRST_PERSON.search(text):
        problems.append("write the bio in the third person")
    for field, words_ in UNKNOWN_TOPICS.items():
        if getattr(animal.checks, field) == "unknown":
            hit = find_word(text, words_)
            if hit:
                problems.append(f"the bio mentions {hit!r}, which the shelter has not confirmed")
    if animal.checks.bite_history == "yes" and not find_word(text, UNKNOWN_TOPICS["bite_history"]):
        problems.append("the shelter recorded a bite; the bio must say so plainly")
    for phrase in BACKSTORY:
        if phrase in lowered:
            problems.append(f"leave out backstory ({phrase.strip()!r})")
    for phrase in PITY_URGENCY:
        if phrase in lowered:
            problems.append(f"leave out pity and urgency ({phrase.strip()!r})")
    return problems


def check_hook(hook: str) -> list[str]:
    problems = []
    if len(re.findall(r"[.!?](\s|$)", ABBREVIATIONS.sub(r"\1", hook.strip()))) > 1:
        problems.append("the hook must be one sentence")
    if len(hook.split()) > 25:
        problems.append("the hook must be 25 words or fewer")
    trait = find_word(hook, HOOK_TRAIT_WORDS)
    if trait:
        problems.append(f"the hook describes temperament ({trait!r}); keep it to the name")
    claim = find_word(hook, HOOK_CLAIMS)
    if claim:
        problems.append(f"the hook makes a claim about tastes ({claim!r})")
    return problems
