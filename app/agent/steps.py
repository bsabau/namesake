"""The live step log: what the agent is doing, for the Working screen.

Tools run in worker threads while the web server streams on its event loop.
A lock makes "snapshot the steps and start listening" atomic with respect to
`add` and `finish`, so a follower sees every step exactly once and never stops
before the last one.
"""

import asyncio
import re
import threading
import time
from collections.abc import AsyncIterator
from typing import Literal

from pydantic import BaseModel, model_validator

StepKind = Literal["start", "qloo", "decision", "check", "note", "done", "error"]
# Who did a step: Qloo (its calls and its answers: Qloo's part of the work), Namesake's AI
# (a decision of the model), the classifier (TypeSafe's Jev sorting titles), or the run's
# own code (its start and end, its notes, its checks, an error).
Actor = Literal["qloo", "ai", "classifier", "code"]
ACTOR_BY_KIND: dict[str, str] = {"qloo": "qloo", "decision": "ai"}


# The tool and field names a fix request may use, in the words a volunteer reads in the log.
# The model is asked in the original words; only the log is reworded.
PLAIN_WORDS = [
    ("give choice_reason", "say which one you meant, and why"),
    ("the choice_reason for", "the reason given for"),
    ("choice_reason", "the reason for the choice"),
    ("your latest find_venues results", "the places Qloo returned last"),
    ("not returned by find_venues", "not among the places Qloo returned"),
    ("call find_venues before answering", "ask Qloo for places before answering"),
    ("call find_venues again", "ask for places again"),
    ("find_venues", "the search for places"),
    ("(look_up_title or find_local_titles)", "(from a lookup or a search)"),
    ("look_up_lookalike", "a lookup"),
    ("look_up_title", "a lookup"),
    ("find_local_titles", "a search of Qloo's lists"),
    ("rank_titles", "the ranking"),
    ("add each to rejected_venues with its reason", "set each aside with a reason"),
    ("rejected_venues", "the places set aside"),
    ("entity_ids", "Qloo IDs"),
    ("entity_id", "Qloo ID"),
]
QLOO_ID = re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b")
# A Python list of strings, as some problems print one: ['a', 'b'].
# Python quotes an item holding an apostrophe with double quotes: ["cat's eyes"].
QUOTED_LIST = re.compile(r"""\[((?:(?:'[^']*'|"[^"]*")(?:, )?)+)\]""")
LIST_ITEM = re.compile(r"'([^']*)'" + r'|"([^"]*)"')


def and_words(items: list[str]) -> str:
    """ "A", "A and B", "A, B and C"; nothing for no items."""
    if len(items) <= 1:
        return "".join(items)
    return ", ".join(items[:-1]) + " and " + items[-1]


def fix_request(problems: list[str], names: dict[str, str] | None = None) -> str:
    """The step for a draft sent back to Namesake's AI, in plain words, quoting what it was
    asked: tool and field names reworded, a list printed as words, a Qloo ID after its own
    name dropped, any other shown as the title or place it stands for, or said to be one this
    run's results do not name."""
    text = "; ".join(problems)
    for word, plain in PLAIN_WORDS:
        text = text.replace(word, plain)
    text = QUOTED_LIST.sub(lambda m: and_words([a or b for a, b in LIST_ITEM.findall(m[1])]), text)
    text = re.sub(r" \(" + QLOO_ID.pattern + r"\)", "", text)
    known = names or {}
    # Single quotes inside the line's own double quotes, so the nesting reads.
    text = QLOO_ID.sub(
        lambda m: (
            f"‘{known[m[0]]}’" if m[0] in known else "with an ID this run's results do not name"
        ),
        text,
    )
    return f"Code sent the answer back to Namesake's AI, asking: “{text}”"


def actor_for(kind: str) -> str:
    """The actor a kind implies when the logging site gives none: code, unless the kind
    is Qloo's or the AI's. An unknown kind is code's."""
    return ACTOR_BY_KIND.get(kind, "code")


class Step(BaseModel):
    at: float
    kind: StepKind
    text: str
    actor: Actor = "code"

    @model_validator(mode="before")
    @classmethod
    def _actor_from_kind(cls, data):
        """A step saved before steps carried an actor gets the one its kind implies, so a
        saved run's log never shows Qloo's calls or the AI's decisions as code's."""
        if isinstance(data, dict) and not data.get("actor"):
            data = {**data, "actor": actor_for(str(data.get("kind", "")))}
        return data


class StepLog:
    def __init__(self, loop: asyncio.AbstractEventLoop | None = None):
        self.steps: list[Step] = []
        self.finished = False
        # When the run finished (time.monotonic), for how long a finished run is kept.
        self.finished_at: float | None = None
        self._loop = loop
        self._lock = threading.Lock()
        self._listeners: list[asyncio.Queue[Step | None]] = []

    def add(self, kind: StepKind, text: str, actor: Actor | None = None) -> Step:
        step = Step(at=time.time(), kind=kind, text=text, actor=actor or actor_for(kind))
        with self._lock:
            self.steps.append(step)
            self._notify(step)
        return step

    def finish(self) -> None:
        with self._lock:
            if self.finished:
                return
            self.finished = True
            self.finished_at = time.monotonic()
            self._notify(None)

    def _notify(self, item: Step | None) -> None:
        # Called with the lock held. call_soon_threadsafe keeps items in order.
        for queue in self._listeners:
            if self._loop is not None and self._loop.is_running():
                self._loop.call_soon_threadsafe(queue.put_nowait, item)
            else:
                queue.put_nowait(item)

    async def follow(self) -> AsyncIterator[Step]:
        """Every step so far, then each new one until the log finishes."""
        queue: asyncio.Queue[Step | None] = asyncio.Queue()
        with self._lock:
            replayed = list(self.steps)
            done = self.finished
            if not done:
                self._listeners.append(queue)
        try:
            for step in replayed:
                yield step
            if done:
                return
            # Everything after the snapshot arrives through the queue, ending with None.
            while (item := await queue.get()) is not None:
                yield item
        finally:
            with self._lock:
                if queue in self._listeners:
                    self._listeners.remove(queue)
