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
    "vodka", "joker", "riot", "chaos", "rifle", "pistol", "shotgun", "sword", "dagger",
    "blade", "axe", "grenade", "missile", "bullet", "cannon", "sniper", "spear", "taser",
    "weapon", "assassin", "hitman", "terror", "poison", "corpse", "skull",
)  # fmt: skip

# Well-known villains and tragic animals: the model also declares each reference's role,
# but a code list catches the famous ones even when it gets that wrong.
FAMOUS_VILLAINS = (
    "scar", "shere khan", "cruella", "cujo", "jafar", "ursula", "maleficent", "voldemort",
    "thanos", "vader", "sauron", "pennywise", "chucky", "hannibal", "lecter", "gaston",
    "hades", "mojo jojo", "old yeller",
)  # fmt: skip
BAD_ROLES = ("villain", "tragic")

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


def check_name(
    name: str,
    *,
    source: str,
    reference_kind: str,
    strict: bool,
    reference: str = "",
    reference_role: str = "neutral",
) -> list[str]:
    problems = []
    if not re.fullmatch(r"[A-Za-z][A-Za-z' -]{0,13}", name):
        problems.append(f"name {name!r} must be letters only, at most 14 characters")
    total = sum(syllables(w) for w in re.split(r"[ -]", name) if w)
    if total > 3:
        problems.append(f"name {name!r} has {total} syllables; use one to three")
    hit = find_word(f"{name} {reference}", NAME_BLOCKLIST)
    if hit:
        problems.append(f"name {name!r} contains {hit!r}")
    villain = find_word(f"{name} {reference}", FAMOUS_VILLAINS)
    if villain:
        problems.append(f"name {name!r} refers to {villain!r}, a villain or tragic animal")
    if reference_role in BAD_ROLES:
        problems.append(f"name {name!r} refers to a {reference_role} character")
    if reference_kind == "person":
        problems.append(f"name {name!r} refers to a real person; use a character or object")
    if strict and source != "pet":
        problems.append(
            f"name {name!r}: for this dog use only names drawn from the pet-themed titles"
        )
    return problems


STOPWORDS = frozenset((
    "a", "an", "and", "are", "as", "at", "be", "been", "but", "by", "for", "from", "has",
    "have", "he", "her", "him", "his", "in", "is", "it", "its", "of", "on", "or", "she", "so",
    "than", "that", "the", "their", "them", "they", "this", "to", "was", "were", "with", "who",
    "will", "would", "can", "also", "very", "much", "more", "most", "just", "well", "when",
    "while", "into", "about", "after", "before", "over", "under",
))  # fmt: skip
# Words a plain restatement may add without changing what a fact says.
GLUE = frozenset((
    "always", "often", "usually", "likes", "enjoys", "seems", "tends", "quite", "really",
    "little", "bit", "both", "each", "every", "old", "year", "years", "week", "weeks", "month",
    "months", "male", "female", "dog", "cat", "kitten", "puppy", "one", "ones",
))  # fmt: skip


def _stem(word: str) -> str:
    for suffix in ("ing", "ed", "es", "ly", "s"):
        if word.endswith(suffix) and len(word) - len(suffix) >= 3:
            return word[: -len(suffix)]
    return word


def _content(text: str) -> set[str]:
    words = re.findall(r"[a-z]+", text.lower())
    return {_stem(w) for w in words if len(w) > 2 and w not in STOPWORDS and w not in GLUE}


def fact_texts(animal: Animal) -> dict[str, str]:
    from app.listing import CHECK_SENTENCES

    texts = {
        "temperament": animal.temperament,
        "look": f"{animal.age} {animal.sex} {animal.species} {animal.look}",
    }
    texts |= {f"fact:{i}": f for i, f in enumerate(animal.facts)}
    for field, answers in CHECK_SENTENCES.items():
        answer = getattr(animal.checks, field)
        if answer in answers:
            texts[f"check:{field}"] = answers[answer]
    return texts


def unsupported_words(animal: Animal, sentence: str, keys: list[str]) -> list[str]:
    """Content words in `sentence` that none of its cited facts contains."""
    texts = fact_texts(animal)
    source = set().union(*(_content(texts[k]) for k in keys if k in texts))
    return sorted(_content(sentence) - source)


NEGATIONS = ("not", "no", "never", "nor", "without", "isn't", "doesn't", "won't", "can't")
# Words a name's "why" may use on top of the facts.
WHY_GLUE = ("suit", "suits", "fit", "fits", "name", "names", "named", "call", "calls")


def agent_fact_keys(animal: Animal) -> list[str]:
    """What the agent's bio may cite: confirmed checks are added by code, not written."""
    return ["temperament", "look"] + [f"fact:{i}" for i in range(len(animal.facts))]


def _texts_for(animal: Animal, keys: list[str]) -> str:
    texts = fact_texts(animal)
    return " ".join(texts[k] for k in keys if k in texts)


def check_grounded(animal: Animal, text: str, keys: list[str], label: str) -> list[str]:
    """Text must say only what the cited facts say: no new words, no new negation,
    and nothing about the shelter's checks unless the fact itself does."""
    problems = []
    source = _texts_for(animal, keys)
    extra = sorted(_content(text) - _content(source))
    if extra:
        problems.append(f"{label} says things its facts do not: {extra}; restate only the facts")
    negation = find_word(text, NEGATIONS)
    if negation and not find_word(source, NEGATIONS):
        problems.append(f"{label} adds a negation ({negation!r}) that its facts do not have")
    for words in UNKNOWN_TOPICS.values():
        hit = find_word(text, words)
        if hit and not find_word(source, words):
            problems.append(
                f"{label} mentions {hit!r}; children, other animals, house-training and bites "
                "come only from the shelter's confirmed checks, which are added separately"
            )
    lowered = f" {text.lower()} "
    for phrase in BACKSTORY:
        if phrase in lowered:
            problems.append(f"{label}: leave out backstory ({phrase.strip()!r})")
    for phrase in PITY_URGENCY:
        if phrase in lowered:
            problems.append(f"{label}: leave out pity and urgency ({phrase.strip()!r})")
    if FIRST_PERSON.search(text):
        problems.append(f"{label}: write in the third person")
    return problems


def check_bio(animal: Animal, sentences: list[tuple[str, list[str]]]) -> list[str]:
    """The agent's bio: every sentence grounded in the facts it cites, every fact used."""
    problems = []
    allowed = agent_fact_keys(animal)
    texts = fact_texts(animal)
    cited: set[str] = set()
    for i, (sentence, facts) in enumerate(sentences, start=1):
        label = f"bio sentence {i}"
        if not facts:
            problems.append(f"{label} cites no fact")
            continue
        bad = [f for f in facts if f not in allowed]
        if bad:
            problems.append(f"{label} cites keys it may not use: {bad}; use {allowed}")
            continue
        cited |= set(facts)
        problems += check_grounded(animal, sentence, facts, label)
    missing = [k for k in allowed if k != "look" and k not in cited]
    if missing:
        listed = "; ".join(f"{k} ({texts[k]!r})" for k in missing)
        problems.append(f"the bio leaves out {listed}; include every recorded fact")
    words = len(" ".join(s for s, _ in sentences).split())
    if words > MAX_WORDS:
        problems.append(f"bio is {words} words; keep it to {MAX_WORDS} or fewer")
    return problems


def check_why(animal: Animal, why: str, name: str) -> list[str]:
    """A name's reason may only restate the animal's facts (plus "suits", "fits", the name)."""
    label = f"the reason for {name!r}"
    keys = agent_fact_keys(animal)
    problems = [p for p in check_grounded(animal, why, keys, label) if "says things" not in p]
    allowed = _content(_texts_for(animal, keys)) | _content(" ".join(WHY_GLUE)) | _content(name)
    extra = sorted(_content(why) - allowed)
    if extra:
        problems.append(f"{label} says things the facts do not: {extra}")
    return problems


def check_reference(reference: str, title: str) -> list[str]:
    """What a name refers to must name its title and stay a plain description."""
    problems = []
    if len(reference.split()) > 14:
        problems.append(
            f"reference {reference!r} is too long; keep it to who or what, and the title"
        )
    title_words = _content(title)
    if title_words and not (title_words & _content(reference)):
        problems.append(f"reference {reference!r} must name its title, {title!r}")
    for words in UNKNOWN_TOPICS.values():
        hit = find_word(reference, words)
        if hit:
            problems.append(f"reference {reference!r} mentions {hit!r}")
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
