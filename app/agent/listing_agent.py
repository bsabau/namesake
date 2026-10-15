"""The listing agent: name options, a bio from the facts, and one hook line.

It makes no Qloo calls: it works from the location profile's titles. Plain
code (`app/agent/checks.py`) checks every draft; a failed check goes back to
the model once, then the pipeline falls back to the templated listing.
"""

from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, Field
from pydantic_ai import Agent, ModelRetry, NativeOutput, PromptedOutput, RunContext, ToolOutput
from pydantic_ai.models import Model

from app.agent import checks
from app.agent.steps import StepLog
from app.animals import Animal
from app.listing import pronouns
from app.profile import Entity

Source = Literal["pet", "local"]


@dataclass
class ListingDeps:
    animal: Animal
    # Titles the names may draw on, by Qloo ID, with their source.
    titles: dict[str, tuple[Entity, Source]]
    log: StepLog

    @property
    def strict(self) -> bool:
        return checks.is_bully_type(self.animal)


class NameOption(BaseModel):
    name: str
    source: Source = Field(description='"pet" for a pet-themed title, "local" for a local taste.')
    entity_id: str = Field(description="The Qloo ID of the title the name comes from.")
    reference: str = Field(description='What the name refers to, e.g. "Bingo, a dog in Bluey".')
    reference_kind: Literal["character", "title", "place", "object", "word", "person"]
    reference_role: Literal["hero", "friend", "neutral", "villain", "tragic"] = Field(
        description="The character's role in the story; villains and tragic figures are refused."
    )
    why: str = Field(description="One sentence on why it suits this animal's look or facts.")


class BioSentence(BaseModel):
    text: str
    facts: list[str] = Field(description="The fact keys this sentence restates.")


class Hook(BaseModel):
    text: str = Field(description="One sentence tying the first name to its title.")
    entity_id: str


class ListingDraft(BaseModel):
    names: list[NameOption] = Field(min_length=3, max_length=5)
    bio: list[BioSentence] = Field(min_length=1)
    hook: Hook


INSTRUCTIONS = """\
You write an adoption listing for a fictional shelter animal, for a volunteer to edit.

Rules:
- The bio restates only the facts listed below, each sentence tagged with the keys it uses.
  Do not add anything else: no backstory, no time in the shelter, no pity or urgency,
  nothing about children, other animals, house-training or bites unless listed.
- Third person, plain words, behaviour toward people first, up to 150 words. If the facts
  are few, the bio is short; never pad it.
- Offer 3 to 5 name options. Each comes from one of the titles below (a character, the
  title, or an object in it), with that title's entity_id and source. Short and easy to
  say: one to three syllables. No villains, violent or tragic characters, weapons, real
  people, or names coded to a race, religion or political identity.
- The hook is one sentence linking the first name to its title. It says nothing about the
  animal's temperament or tastes, and nothing about what people like.
{strict}
The animal ({they}):
{facts}

Titles:
{titles}
"""

STRICT = (
    "- This dog gets the strictest name screen: use only names from the pet-themed titles,\n"
    "  and avoid anything that reads as a human first name.\n"
)


def facts_block(animal: Animal) -> str:
    lines = [
        f'- temperament: "{animal.temperament}"',
        f'- look: "{animal.age} {animal.sex} {animal.species}: {animal.look}"',
    ]
    lines += [f'- fact:{i}: "{f}"' for i, f in enumerate(animal.facts)]
    lines += [f"- check:{k}: {v}" for k, v in animal.checks.model_dump().items() if v != "unknown"]
    return "\n".join(lines)


def titles_block(titles: dict[str, tuple[Entity, Source]]) -> str:
    return "\n".join(
        f"- {e.id} ({source}): {e.name}. {(e.description or '')[:160]}"
        for e, source in titles.values()
    )


def check_draft(ctx: RunContext[ListingDeps], draft: ListingDraft) -> ListingDraft:
    deps = ctx.deps
    problems: list[str] = []
    seen_names = set()
    for option in draft.names:
        if option.entity_id not in deps.titles:
            problems.append(f"name {option.name!r} cites a title that was not offered")
        elif deps.titles[option.entity_id][1] != option.source:
            problems.append(f"name {option.name!r} has the wrong source")
        if option.name.lower() in seen_names:
            problems.append(f"name {option.name!r} is offered twice")
        seen_names.add(option.name.lower())
        problems += checks.check_name(
            option.name,
            source=option.source,
            reference_kind=option.reference_kind,
            strict=deps.strict,
            reference=option.reference,
            reference_role=option.reference_role,
        )
    problems += checks.check_bio(deps.animal, [(s.text, s.facts) for s in draft.bio])
    if draft.hook.entity_id not in {o.entity_id for o in draft.names}:
        problems.append("the hook must refer to the title of one of the names")
    problems += checks.check_hook(draft.hook.text)
    if problems:
        deps.log.add("check", "Sent back for a fix: " + "; ".join(problems))
        raise ModelRetry("Fix these and answer again: " + "; ".join(problems))
    deps.log.add("check", "Listing checked: facts trace, names and hook pass the screen")
    return draft


def output_spec(mode: str):
    if mode == "prompted":
        return PromptedOutput(ListingDraft)
    if mode == "tool":
        return ToolOutput(ListingDraft)
    return NativeOutput(ListingDraft)


def build_listing_agent(
    model: Model, output_mode: str = "native"
) -> Agent[ListingDeps, ListingDraft]:
    agent = Agent(model, deps_type=ListingDeps, output_type=output_spec(output_mode), retries=1)

    @agent.instructions
    def instructions(ctx: RunContext[ListingDeps]) -> str:
        a = ctx.deps.animal
        return INSTRUCTIONS.format(
            strict=STRICT if ctx.deps.strict else "",
            they=pronouns(a.sex)["they"],
            facts=facts_block(a),
            titles=titles_block(ctx.deps.titles),
        )

    agent.output_validator(check_draft)
    return agent
