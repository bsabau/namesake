"""Sorting titles into pet-themed or not, with TypeSafe's Jev (decision 20).

Jev answers typed yes/no questions with a probability each. It reads one title at a
time: its name, kind and Qloo's description, never anything about a visitor. Answers
are cached in SQLite by entity and question version, so a title is classified once.

Without a key the classifier is off and Namesake's AI judges every title from its
description instead.
"""

import json
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
TIMEOUT = 30

Bucket = Literal["kept", "unsure", "dropped"]
Post = Callable[[str, dict[str, str], bytes], dict[str, Any]]

SCHEMA = """
CREATE TABLE IF NOT EXISTS classifier_cache (
    entity_id TEXT NOT NULL,
    version INTEGER NOT NULL,
    verdict_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (entity_id, version)
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
    with urllib.request.urlopen(request, timeout=TIMEOUT) as response:  # noqa: S310 - https only
        return json.load(response)


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
        cache_db.parent.mkdir(parents=True, exist_ok=True)
        self.db = cache_db
        with sqlite3.connect(self.db) as conn:
            conn.execute(SCHEMA)

    def classify(self, entity: Entity) -> PetVerdict | None:
        """The verdict for one title, from the cache or Jev; None when Jev fails."""
        with sqlite3.connect(self.db) as conn:
            row = conn.execute(
                "SELECT verdict_json FROM classifier_cache WHERE entity_id = ? AND version = ?",
                (entity.id, QUESTIONS_VERSION),
            ).fetchone()
        if row:
            return PetVerdict.model_validate_json(row[0])
        state = {
            "title": entity.name,
            "type": entity.type.removeprefix("urn:entity:"),
            "description": entity.description or "",
        }
        body = json.dumps({"model": self.model, "state": state, "questions": QUESTIONS})
        headers = {"Authorization": f"Bearer {self._key}", "Content-Type": "application/json"}
        try:
            out = self.post(self.url, headers, body.encode())
            answers = {q: float(out["answers"][q]["noul"]) for q in QUESTIONS}
        except (OSError, ValueError, KeyError, TypeError):
            # A failed call is not cached: the title goes to the AI and is asked again later.
            return None
        verdict = PetVerdict(**answers, model=str(out.get("model", "")))
        with sqlite3.connect(self.db) as conn:
            conn.execute(
                "INSERT OR REPLACE INTO classifier_cache VALUES (?, ?, ?, ?)",
                (
                    entity.id,
                    QUESTIONS_VERSION,
                    verdict.model_dump_json(),
                    datetime.now(UTC).isoformat(),
                ),
            )
        return verdict


def classifier_from(settings) -> JevClassifier | None:
    """Jev when a key is configured, else None (Namesake's AI judges the titles)."""
    key = settings.typesafe_api_key
    if key is None or not key.get_secret_value().strip():
        return None
    return JevClassifier(
        key.get_secret_value(),
        settings.cache_db,
        base_url=settings.typesafe_base_url,
        model=settings.typesafe_model,
    )
