"""The live step log: what the agent is doing, for the Working screen.

Tools run in worker threads while the web server streams on its event loop.
A lock makes "snapshot the steps and start listening" atomic with respect to
`add` and `finish`, so a follower sees every step exactly once and never stops
before the last one.
"""

import asyncio
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
