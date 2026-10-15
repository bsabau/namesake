"""The live step log: what the agent is doing, for the Working screen.

Tools run in worker threads while the web server streams on its event loop, so
`add` hands each step to the loop thread-safely.
"""

import asyncio
import time
from collections.abc import AsyncIterator
from typing import Literal

from pydantic import BaseModel

StepKind = Literal["start", "qloo", "decision", "check", "note", "done", "error"]


class Step(BaseModel):
    at: float
    kind: StepKind
    text: str


class StepLog:
    def __init__(self, loop: asyncio.AbstractEventLoop | None = None):
        self.steps: list[Step] = []
        self.finished = False
        self._loop = loop
        self._listeners: list[asyncio.Queue[Step | None]] = []

    def add(self, kind: StepKind, text: str) -> Step:
        step = Step(at=time.time(), kind=kind, text=text)
        self.steps.append(step)
        self._notify(step)
        return step

    def finish(self) -> None:
        self.finished = True
        self._notify(None)

    def _notify(self, item: Step | None) -> None:
        for queue in list(self._listeners):
            if self._loop is not None and self._loop.is_running():
                self._loop.call_soon_threadsafe(queue.put_nowait, item)
            else:
                queue.put_nowait(item)

    async def follow(self) -> AsyncIterator[Step]:
        """Every step so far, then each new one until the log finishes."""
        queue: asyncio.Queue[Step | None] = asyncio.Queue()
        self._listeners.append(queue)
        try:
            replayed = list(self.steps)
            for step in replayed:
                yield step
            if self.finished:
                return
            # A step added while listening began can be in both the replay and the queue.
            already = {id(step) for step in replayed}
            while (item := await queue.get()) is not None:
                if id(item) not in already:
                    yield item
        finally:
            self._listeners.remove(queue)
