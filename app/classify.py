"""Sorting titles into pet-themed or not, with TypeSafe's Jev (decision 20).

Jev answers typed yes/no questions with a probability each. It reads one title at a
time: its name, kind and Qloo's description, never anything about a visitor. Answers
are cached in SQLite by the title, its description, the questions and the model, so a
title is classified once.

Without a key the classifier is off and Namesake's AI judges every title from its
description instead.
"""

import hashlib
import json
import math
import sqlite3
import urllib.request
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from app.profile import Entity, PetVerdict

# Raised whenever a question changes, so cached answers to the old wording are not reused.
QUESTIONS_VERSION = 1
QUESTIONS: dict[str, dict[str, Any]] = {
    "pets": {
        "type": "noul",
        "instructions": "Are pet animals central to this title?",
        "criteria": {
            "true": "It is mainly about dogs, cats or other companion animals, or a pet is a "
            "main character",
            "false": "Animals are absent, wild, fantasy creatures, or only in the background",
        },
    },
    "dogs": {"type": "noul", "instructions": "Is a dog a main character or the main subject?"},
    "cats": {"type": "noul", "instructions": "Is a cat a main character or the main subject?"},
    "family": {
        "type": "noul",
        "instructions": "Is this title suitable for a family audience, including children?",
    },
    "real_people": {
        "type": "noul",
        "instructions": "Is this title about real people (a talk show, reality show, "
        "documentary, biopic or memoir)?",
    },
}
# Code keeps a title only when the classifier is sure; between the bounds, Namesake's AI
# decides from the description; below, the title is dropped.
KEEP_PETS = 0.8
DROP_PETS = 0.3
KEEP_FAMILY = 0.6
# Above this, a title counts as about real people, so only animals' names come from it.
REAL_PEOPLE = 0.8
# Per request; a run stops asking after the first failure (app/agent/profile_agent.py).
TIMEOUT = 10

Bucket = Literal["kept", "unsure", "dropped"]
Post = Callable[[str, dict[str, str], bytes], dict[str, Any]]

# Keyed by what the answer depends on: the title as Qloo described it, the questions and
# the model, so a new description, wording or model asks again.
SCHEMA = """
CREATE TABLE IF NOT EXISTS classifier_answers (
    key TEXT PRIMARY KEY,
    entity_id TEXT NOT NULL,
    verdict_json TEXT NOT NULL,
    created_at TEXT NOT NULL
)
"""


def bucket(verdict: PetVerdict | None) -> Bucket:
    """Where a title goes. No verdict (classifier off or failed) leaves it to the AI."""
    if verdict is None:
        return "unsure"
    if verdict.pets <= DROP_PETS:
        return "dropped"
    if verdict.pets >= KEEP_PETS and verdict.family >= KEEP_FAMILY:
        return "kept"
    return "unsure"


def http_post(url: str, headers: dict[str, str], body: bytes) -> dict[str, Any]:
    request = urllib.request.Request(url, data=body, headers=headers, method="POST")
    # classifier_from accepts only an https:// base URL.
    with urllib.request.urlopen(request, timeout=TIMEOUT) as response:  # noqa: S310
        return json.load(response)


def probability(value: Any) -> float:
    """A probability from Jev, or ValueError: NaN, infinity or out of range is refused."""
    number = float(value)
    if not math.isfinite(number) or not 0.0 <= number <= 1.0:
        raise ValueError(f"not a probability: {value!r}")
    return number


class JevClassifier:
    def __init__(
        self,
        api_key: str,
        cache_db: Path,
        *,
        base_url: str = "https://api.typesafe.ai/v1",
        model: str = "jev-latest",
        post: Post = http_post,
    ):
        self._key = api_key
        self.url = f"{base_url.rstrip('/')}/systemone"
        self.model = model
        self.post = post
        self.db = cache_db
        # Set when a call to Jev fails: from then on only saved answers are used, so a slow
        # or broken Jev costs one timeout. A classifier lives for one run (app/runs.py).
        self.down = False
        try:
            cache_db.parent.mkdir(parents=True, exist_ok=True)
            with sqlite3.connect(self.db) as conn:
                conn.execute(SCHEMA)
                # The first version's table, keyed too loosely; never read.
                conn.execute("DROP TABLE IF EXISTS classifier_cache")
        except (OSError, sqlite3.Error):
            pass  # classify reports the failure per title

    def classify(self, entity: Entity) -> PetVerdict | None:
        """The verdict for one title, from the cache or Jev. None when anything fails,
        Jev or the cache: the classifier is optional, so it never stops a run."""
        try:
            return self._classify(entity)
        except Exception:  # noqa: BLE001 - any failure leaves the title to the AI
            return None

    def _classify(self, entity: Entity) -> PetVerdict | None:
        state = {
            "title": entity.name,
            "type": entity.type.removeprefix("urn:entity:"),
            "description": entity.description or "",
        }
        key = hashlib.sha256(
            json.dumps([QUESTIONS_VERSION, QUESTIONS, self.model, state], sort_keys=True).encode()
        ).hexdigest()
        with sqlite3.connect(self.db) as conn:
            row = conn.execute(
                "SELECT verdict_json FROM classifier_answers WHERE key = ?", (key,)
            ).fetchone()
        if row:
            return PetVerdict.model_validate_json(row[0])
        if self.down:
            return None
        body = json.dumps({"model": self.model, "state": state, "questions": QUESTIONS})
        headers = {"Authorization": f"Bearer {self._key}", "Content-Type": "application/json"}
        # A failure raises before anything is cached, so the title is asked again later.
        try:
            out = self.post(self.url, headers, body.encode())
            answers = {q: probability(out["answers"][q]["noul"]) for q in QUESTIONS}
        except Exception:
            self.down = True
            raise
        verdict = PetVerdict(**answers, model=str(out.get("model", "")))
        with sqlite3.connect(self.db) as conn:
            conn.execute(
                "INSERT OR REPLACE INTO classifier_answers VALUES (?, ?, ?, ?)",
                (key, entity.id, verdict.model_dump_json(), datetime.now(UTC).isoformat()),
            )
        return verdict


def classifier_from(settings) -> JevClassifier | None:
    """Jev when a key and an https:// base URL are configured, else None (Namesake's AI
    judges the titles)."""
    key = settings.typesafe_api_key
    if key is None or not key.get_secret_value().strip():
        return None
    if not settings.typesafe_base_url.startswith("https://"):
        return None
    return JevClassifier(
        key.get_secret_value(),
        settings.cache_db,
        base_url=settings.typesafe_base_url,
        model=settings.typesafe_model,
    )
