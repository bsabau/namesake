"""Plain-code checks on the agent's listing: the rules in AGENTS.md, made testable.

Each check returns a list of problems in words the model can act on. An empty
list means the draft passes.
"""

import re

from app.animals import Animal
from app.listing import MAX_WORDS

# Looks that mark a bully-type dog: these get the strictest name screen, because a
# measured adoption penalty fell on names perceived as Black for pit-bull-type dogs.
# Substrings of the look, so "pit bull mix" and "staffies" match; never a bare "pit",
# which "spitz" contains (the shorthand forms added after the 19 October audit).
BULLY_MARKERS = (
    "broad head", "blocky head", "boxy head", "pit bull", "pitbull", "pit mix", "pittie",
    "pitty", "bully", "bullies", "stafford", "staffy", "staffie", "amstaff", "bull terrier",
    "american bulldog", "bulldog mix",
)  # fmt: skip

# Whole words only, with their common forms: "Killer" is out, "Killian" and "Edward" are not.
NAME_BLOCKLIST = (
    "kill", "killer", "killa", "death", "deadly", "dead", "gun", "guns", "gunner", "knife",
    "war", "blood", "bloody", "devil", "demon", "satan", "murder", "bomb", "bomber", "slave",
    "nazi", "venom", "rage", "psycho", "villain", "toxic", "crack", "booze", "whiskey",
    "vodka", "joker", "riot", "chaos", "rifle", "pistol", "shotgun", "sword", "dagger",
    "blade", "axe", "grenade", "missile", "bullet", "cannon", "sniper", "spear", "taser",
    "weapon", "assassin", "hitman", "terror", "poison", "corpse", "skull",
)  # fmt: skip

# Words no adoption listing should call an animal (decided 18 October, after a rebuild
# offered "Garbage" and "Scat"): dirt, waste, pests and insults. Whole words, as above,
# so plurals and variants are listed. "Mutt" and "Runt" are everyday shelter words, and
# "Ratty" is the Water Rat of The Wind in the Willows: kept.
UNFLATTERING = (
    "garbage", "trash", "trashy", "rubbish", "junk", "junky", "junkie", "junkyard", "scat",
    "poop", "poopy", "poo", "dung", "stink", "stinky", "stinker", "stinkers", "smelly", "dirty",
    "filthy", "grubby", "ugly", "fatty", "fatso", "dumb", "dummy", "dummies", "stupid", "idiot",
    "idiots", "loser", "losers", "freak", "freaks", "freaky", "rat", "rats",
    "roach", "roaches", "cockroach", "maggot", "maggots", "pest", "pests", "vermin",
    "leech", "leeches", "mangy", "flea", "fleas", "fleabag", "fleabags",
)  # fmt: skip

# Words that keep a title's own name off an adoption listing, beyond the name screen's
# words (19 October audit: three kittens were introduced as "a cat in My Cat from Hell").
# The hook names the title, so its words reach the listing even when the name is fine.
TITLE_UNFIT = (
    "hell", "hellish", "nightmare", "nightmares", "worst", "evil", "horror", "horrors",
    "hate", "hates", "hated", "monstrous",
)  # fmt: skip

# Well-known villains and tragic animals: the model also declares each reference's role,
# but a code list catches the famous ones even when it gets that wrong.
FAMOUS_VILLAINS = (
    "scar", "shere khan", "cruella", "cujo", "jafar", "ursula", "maleficent", "voldemort",
    "thanos", "vader", "sauron", "pennywise", "chucky", "hannibal", "lecter", "gaston",
    "hades", "mojo jojo", "old yeller",
)  # fmt: skip
BAD_ROLES = ("villain", "tragic")
ANIMAL_ROLES = ("puppy", "dog", "cat", "kitten", "animal")

# Real people, as a code list for the famous ones. Names come only from the characters,
# objects and titles of the titles Qloo returned, so a real person reaches a name through
# a title about real people (caught by check_title) or a role the model declares as
# "person". The list cannot be complete; the volunteer still chooses.
FAMOUS_PEOPLE = (
    "oprah", "beyonce", "beyoncé", "rihanna", "adele", "shakira", "madonna", "cher",
    "kanye", "eminem", "lizzo", "zendaya", "taylor swift", "dolly parton", "kardashian",
    "elon musk", "musk", "bezos", "zuckerberg", "lebron", "messi", "ronaldo",
    "serena williams", "parton",
)  # fmt: skip
# Phrases in a title's name or description that mark it as about real people: a name
# from one must be an animal's own (Marley in "Marley & Me" is a dog; the author is not
# a name option).
REAL_PEOPLE_TITLES = (
    "talk show", "late-night talk", "late-night show", "news program", "news show",
    "news satire", "newsmagazine", "reality show", "reality series", "reality television",
    "reality tv", "reality competition", "documentary", "docuseries", "biographical",
    "biopic", "biography", "memoir", "autobiography", "game show", "stand-up",
    "variety show", "sketch comedy", "true story", "based on the life",
)  # fmt: skip
# References coded to a religion, a race or a political identity. The strictest screen
# for bully-type dogs is a rule on sources, not a list of human first names, which would
# itself be a stereotype.
# These are also searched in a title's description, which names its cast, so none is a
# name people commonly bear: "The Aristocats" stars Phil Harris, and Jesús, Mohammed
# and Jihad are common first names, while a cast member called Obama or Stalin is not.
# Plurals are listed, since matching is by whole word.
IDENTITY_TERMS = (
    "christ", "allah", "buddha", "messiah", "rabbi", "rabbis", "imam", "imams",
    "thug", "thugs", "ghetto", "gangsta", "gypsy", "gypsies", "eskimo", "redskin", "squaw",
    "trump", "biden", "obama", "putin", "maga",
    "democrat", "democrats", "republican", "republicans", "commie", "commies",
    "communist", "communists", "socialist", "socialists", "fascist", "fascists",
    "confederate", "confederacy", "hitler", "stalin", "lenin",
)  # fmt: skip
# In a name, its reference and a title's name only: these are people's names too.
IDENTITY_CODED = IDENTITY_TERMS + (
    "jesus", "jihad", "muhammad", "mohammed", "krishna", "shiva", "vishnu", "ganesh", "ganesha",
    "moses", "prophet", "pope", "lucifer", "crusade", "crusader", "crusaders", "savage",
    "clinton", "harris", "bernie", "dixie", "mao",
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
    # Hyphens as spaces, so "pit-bull mix" reads as "pit bull mix". "Bulldog mix" also
    # catches a French bulldog mix: a stricter screen than needed, never a looser one.
    look = animal.look.lower().replace("-", " ")
    return animal.species == "dog" and any(m in look for m in BULLY_MARKERS)


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
    role: str,
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
    # Like the identity screen, the message leaves the word out (the log is shown).
    if find_word(f"{name} {reference}", NAME_BLOCKLIST):
        problems.append(f"name {name!r} contains a weapon, violence or hate word")
    # The name alone: a character may be "Scat Cat", but the name is what the animal is
    # called. The message names the word, which is harmless to show.
    unflattering = find_word(name, UNFLATTERING)
    if unflattering:
        problems.append(f"name {name!r} is unflattering for an adoption listing ({unflattering!r})")
    villain = find_word(f"{name} {reference}", FAMOUS_VILLAINS)
    if villain:
        problems.append(f"name {name!r} refers to {villain!r}, a villain or tragic animal")
    if reference_role in BAD_ROLES:
        problems.append(f"name {name!r} refers to a {reference_role} character")
    person = find_word(f"{name} {reference}", FAMOUS_PEOPLE)
    if role == "person" or person:
        problems.append(f"name {name!r} refers to a real person; use a character or object")
    # The message names the category, not the word: the step log is shown to visitors.
    if find_word(f"{name} {reference}", IDENTITY_CODED):
        problems.append(f"name {name!r} is coded to a religion, race or political identity")
    # A lookalike title features an animal like this one, and its name must be that
    # animal's own (checked in the listing agent), so it is as safe as a pet title.
    if strict and source not in ("pet", "lookalike"):
        problems.append(
            f"name {name!r}: for this dog use only names drawn from the pet-themed or "
            "lookalike titles"
        )
    return problems


# For the area's comparison shows only (decision 18): everyday words a description uses
# for a religion, race or politics. Never a first name or surname (descriptions name the
# cast), so "Christian" and "Church" appear only inside phrases. Not used for names, whose
# screen (decision 19) stays as it was.
IDENTITY_CATEGORIES = (
    "muslim", "muslims", "islam", "islamic", "jewish", "judaism", "catholic", "catholics",
    "christians", "christianity", "christian faith", "christian family", "evangelical",
    "evangelicals", "hindu", "hinduism", "sikh", "mormon", "mormons", "religion",
    "religious", "the church", "a church", "gospel", "political", "politics", "politician",
    "politicians", "president", "presidential", "election", "elections", "senate",
    "congress", "congressional", "partisan", "liberal", "liberals", "conservative",
    "conservatives", "activist", "activism", "civil rights", "racism", "racist", "racial",
    "race relations", "christian community", "christian church",
)  # fmt: skip
# The same kind of words, safe in a show's name too (none is a first name or surname).
IDENTITY_CATEGORY_NAMES = (
    "political", "politics", "president", "presidential", "election", "elections",
    "senate", "congress", "religion", "religious", "gospel",
)  # fmt: skip


def mentions_identity(name: str, description: str | None) -> bool:
    """A show whose name or description mentions a religion, race or politics: the
    identity screen plus everyday category words. A word list, so the page says
    "mentions", not "is about"."""
    return (
        identity_coded(name, description)
        or bool(find_word(description or "", IDENTITY_CATEGORIES))
        or bool(find_word(name, IDENTITY_CATEGORY_NAMES))
    )


def identity_coded(name: str, description: str | None) -> bool:
    """A title coded to a religion, race or political identity: by its name, or by words in
    its description that are rarely anyone's name (descriptions name the cast)."""
    return bool(find_word(name, IDENTITY_CODED) or find_word(description or "", IDENTITY_TERMS))


def check_title(
    name: str, role: str, title: str, description: str | None, *, real_people: bool = False
) -> list[str]:
    """The title a name comes from, as Qloo returned it: about real people (by its
    description, or by the classifier when `real_people`), or coded to a religion, race or
    political identity."""
    problems = []
    text = f"{title} {description or ''}"
    phrase = find_word(text, REAL_PEOPLE_TITLES)
    if (phrase or real_people) and role not in ANIMAL_ROLES:
        why = f"its description says {phrase!r}" if phrase else "the classifier scores it so"
        problems.append(
            f"name {name!r}: {title} is about real people ({why}), so a name from it "
            "must be an animal's own"
        )
    if identity_coded(title, description):
        problems.append(
            f"name {name!r}: {title} is coded to a religion, race or political identity; "
            "use another title"
        )
    # The title's own name only: a description may well mention a villain.
    if find_word(title, NAME_BLOCKLIST + UNFLATTERING + TITLE_UNFIT):
        problems.append(
            f"name {name!r}: the title {title!r} would introduce the animal with a word that "
            "does not suit an adoption listing; use another title"
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
    "months", "male", "female", "dog", "cat", "one", "ones",
))  # fmt: skip
# "puppy" and "kitten" are not glue: they claim an age, so a bio or reason may use them
# only for an animal recorded as under a year old (app/listing.py, life_stage).


def stage_word(animal: Animal) -> set[str]:
    from app.listing import life_stage

    stage = life_stage(animal)
    return {_stem(stage)} if stage else set()


def _stem(word: str) -> str:
    for suffix in ("ing", "ed", "es", "ly", "s"):
        if word.endswith(suffix) and len(word) - len(suffix) >= 3:
            return word[: -len(suffix)]
    return word


def _content(text: str) -> set[str]:
    words = re.findall(r"[a-z]+", text.lower())
    return {_stem(w) for w in words if len(w) > 2 and w not in STOPWORDS and w not in GLUE}


def _normal(text: str) -> str:
    return " " + " ".join(re.findall(r"[a-z0-9']+", text.lower())) + " "


def _segments(fact: str) -> list[str]:
    """A fact's phrases: temperament and look are lists joined by ; , and :."""
    return [seg.strip() for seg in re.split(r"[;,:]", fact) if seg.strip()]


def fact_texts(animal: Animal) -> dict[str, str]:
    from app.listing import CHECK_SENTENCES, look_text

    texts = {
        "temperament": animal.temperament,
        # The same wording the agent is shown, so a faithful copy passes.
        "look": look_text(animal),
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
WHY_GLUE = (
    "suit", "suits", "fit", "fits", "name", "names", "named", "call", "calls", "echo", "echoes",
)  # fmt: skip
# The one reason that needs no look words: "short" alone could claim a short coat.
EASY_TO_SAY = re.compile(
    r"^\s*(a short name|(it is |it's )?short),? (and )?easy to say\.?\s*$", re.IGNORECASE
)


def agent_fact_keys(animal: Animal) -> list[str]:
    """What the agent's bio may cite: confirmed checks are added by code, not written."""
    return ["temperament", "look"] + [f"fact:{i}" for i in range(len(animal.facts))]


def _texts_for(animal: Animal, keys: list[str]) -> str:
    texts = fact_texts(animal)
    return " ".join(texts[k] for k in keys if k in texts)


def check_grounded(
    animal: Animal, text: str, keys: list[str], label: str, *, whole: bool = True
) -> list[str]:
    """Text must say what its cited facts say, whole, and nothing more.

    No content word the facts lack, every content word of each cited fact, each fact's
    negation kept and none added, and nothing about the shelter's checks unless the
    fact itself says it.
    """
    texts = fact_texts(animal)
    source = _texts_for(animal, keys)
    problems = []
    extra = sorted(_content(text) - _content(source) - stage_word(animal))
    if extra:
        problems.append(f"{label} says things its facts do not: {extra}; restate only the facts")
    negation = find_word(text, NEGATIONS)
    if negation and not find_word(source, NEGATIONS):
        problems.append(f"{label} adds a negation ({negation!r}) that its facts do not have")
    for key in keys if whole else []:
        fact = texts.get(key, "")
        missing = sorted(_content(fact) - _content(text))
        if missing:
            problems.append(f"{label} cites {key} but leaves out {missing}; restate it whole")
        dropped = find_word(fact, NEGATIONS)
        if dropped and not find_word(text, NEGATIONS):
            problems.append(f"{label} drops the {dropped!r} in {key}; keep its meaning")
        # Each phrase of the fact must appear word for word: reordering ("guards toys but
        # not food") or slipping words in ("but not when she has toys") can change it.
        changed = [seg for seg in _segments(fact) if _normal(seg) not in _normal(text)]
        if changed and not missing:
            problems.append(
                f"{label} changes the wording of {key}; keep these words exactly: {changed}"
            )
    return problems + _topics_and_tone(text, source, label)


def _topics_and_tone(text: str, source: str, label: str) -> list[str]:
    problems = []
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


def check_bio(
    animal: Animal, sentences: list[tuple[str, list[str]]], extra_words: int = 0
) -> list[str]:
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
    # `extra_words`: the confirmed-check sentences code appends count toward the limit.
    words = len(" ".join(s for s, _ in sentences).split()) + extra_words
    if words > MAX_WORDS:
        problems.append(
            f"bio is {words} words with the confirmed checks; keep it to {MAX_WORDS} or fewer"
        )
    return problems


def check_why(animal: Animal, why: str, name: str) -> list[str]:
    """A name's reason may only draw on the animal's recorded look (plus "suits", "fits",
    the name), or be "A short name, easy to say." or a near form: a reference must not imply
    temperament, so the hook's rule holds for the reasons too (decided 18 October)."""
    label = f"the reason for {name!r}"
    if EASY_TO_SAY.match(why):
        return []
    keys = ["look"]
    # A reason draws on some facts, so it need not restate any of them whole.
    grounded = check_grounded(animal, why, keys, label, whole=False)
    problems = [p for p in grounded if "says things" not in p]
    allowed = (
        _content(_texts_for(animal, keys))
        | _content(" ".join(WHY_GLUE))
        | _content(name)
        | stage_word(animal)
    )
    extra = sorted(_content(why) - allowed)
    if extra:
        problems.append(
            f"{label} says things the recorded look does not: {extra}; use the look's own "
            'words, never temperament or behaviour, or write "A short name, easy to say."'
        )
    return problems


NAME_JOINERS = ("in", "of", "the", "and", "de", "da", "von", "van", "le", "la")


# The reference names the character's kind, not its age: "Bluey, a puppy in Bluey" read
# as a claim about a 4-year-old dog (22 October, an outside read as a judge).
REFERENCE_KIND = {"puppy": "dog", "kitten": "cat"}


def reference_text(character: str, role: str, title: str) -> str:
    """What a name refers to, assembled by code from a name, a fixed role and Qloo's title."""
    if role == "title":
        return title
    if role in ("character", "object"):
        return f"{character} in {title}"
    kind = REFERENCE_KIND.get(role, role)
    article = "an" if kind[0] in "aeiou" else "a"
    return f"{character}, {article} {kind} in {title}"


def check_character(character: str, role: str) -> list[str]:
    """The character's or thing's own name: a few plain words, nothing descriptive. A name
    taken from the title itself is the model's choice too, so its words are screened."""
    problems = []
    if role == "title":
        for words, what in (
            (HOOK_TRAIT_WORDS, "temperament"),
            (HOOK_CLAIMS, "a claim about tastes"),
        ):
            found = find_word(character, words)
            if found:
                problems.append(f"name from the title {character!r} suggests {what} ({found!r})")
        return problems
    if not re.fullmatch(r"[A-Za-z][A-Za-z'. -]{0,30}", character) or len(character.split()) > 4:
        problems.append(f"character {character!r} must be a name of up to four words, nothing else")
    # A proper name: capitalised words, with only the small joining words names use
    # ("Puss in Boots"). "Bingo who enjoys cuddles" is a description, not a name.
    lower = [w for w in character.split() if not w[:1].isupper() and w not in NAME_JOINERS]
    if lower:
        problems.append(f"character {character!r} must be a proper name; {lower} are not")
    for words, what in (
        (HOOK_TRAIT_WORDS, "temperament"),
        (HOOK_CLAIMS, "a claim about tastes"),
        (tuple(w for ws in UNKNOWN_TOPICS.values() for w in ws), "a check topic"),
    ):
        hit = find_word(character, words)
        if hit:
            problems.append(f"character {character!r} contains {what} ({hit!r})")
    return problems


# A reason for choosing among Qloo's candidates names the work (year, kind, plot), never
# what people like: it is shown as our reading in the Why panel.
CHOICE_CLAIMS = HOOK_CLAIMS + (
    "popular", "local", "locals", "people", "audience", "neighbourhood", "neighborhood",
)  # fmt: skip


def check_choice_reason(reason: str, label: str) -> list[str]:
    problems = []
    claim = find_word(reason, CHOICE_CLAIMS)
    if claim:
        problems.append(
            f"{label} makes a claim about tastes ({claim!r}); say which work it is instead"
        )
    trait = find_word(reason, HOOK_TRAIT_WORDS)
    if trait:
        problems.append(f"{label} describes temperament ({trait!r}); say which work it is")
    return problems


def reference_key(entity_id: str, character: str) -> tuple[str, tuple[str, ...]]:
    """What a name refers to: the title, and the character's words."""
    return entity_id, tuple(re.findall(r"[a-z0-9]+", character.lower()))


def same_reference(a: tuple[str, tuple[str, ...]], b: tuple[str, tuple[str, ...]]) -> bool:
    """One title, and one character's words start the other's (19 October audit: "Scooby"
    and "Scooby-Doo" are one reference; "Mr Peanutbutter" and "Mr Pickles" are two)."""
    (title_a, words_a), (title_b, words_b) = a, b
    n = min(len(words_a), len(words_b))
    return title_a == title_b and n > 0 and words_a[:n] == words_b[:n]


def hook_text(reference: str) -> str:
    """The local version's one line. A title ending in "!" or "?" ends the sentence itself
    (19 October audit: "…Where Are You!.")."""
    return f"Named after {reference}" + ("" if reference.endswith(("!", "?", ".")) else ".")


def check_hook(hook: str, title: str = "") -> list[str]:
    """The hook's form, and no temperament or taste claim in what the model chose: the
    character and its role. Qloo's `title` is left out of the word screens (19 October
    audit: "The Call of the Wild" read as temperament), since the model did not write it."""
    problems = []
    if len(re.findall(r"[.!?](\s|$)", ABBREVIATIONS.sub(r"\1", hook.strip()))) > 1:
        problems.append("the hook must be one sentence")
    if len(hook.split()) > 25:
        problems.append("the hook must be 25 words or fewer")
    chosen = hook.replace(title, " ") if title else hook
    trait = find_word(chosen, HOOK_TRAIT_WORDS)
    if trait:
        problems.append(f"the hook describes temperament ({trait!r}); keep it to the name")
    claim = find_word(chosen, HOOK_CLAIMS)
    if claim:
        problems.append(f"the hook makes a claim about tastes ({claim!r})")
    return problems
