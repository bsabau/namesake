"""Qloo's hackathon guide forbids publishing Qloo response data in a public repo.

Real recordings live in the git-ignored `var/`; tests use the hand-written
envelopes in `tests/fixtures/qloo/synthetic/`.
"""

import json
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
RECORDINGS = ROOT / "var" / "qloo-recordings"
SYNTHETIC = ROOT / "tests" / "fixtures" / "qloo" / "synthetic"
SKIP_DIRS = {".git", ".venv", "var", "node_modules", ".pytest_cache", ".ruff_cache", "__pycache__"}
TEXT_SUFFIXES = {".py", ".json", ".md", ".html", ".js", ".css", ".toml", ".txt", ".yml", ".yaml"}

UUID = re.compile(r"[0-9A-F]{8}-[0-9A-F]{4}-[0-9A-F]{4}-[0-9A-F]{4}-[0-9A-F]{12}")
CORRELATION_ID = re.compile(r"exec-[0-9a-f]{8}-[0-9a-f-]{27}")


def repo_text_files():
    for path in ROOT.rglob("*"):
        rel = path.relative_to(ROOT)
        if rel.parts[0] in SKIP_DIRS or not path.is_file() or path.suffix not in TEXT_SUFFIXES:
            continue
        yield path


def test_synthetic_fixtures_are_synthetic():
    files = sorted(SYNTHETIC.glob("*.json"))
    assert files, "expected synthetic fixtures"
    for path in files:
        text = path.read_text(encoding="utf-8")
        json.loads(text)
        assert not CORRELATION_ID.search(text), f"{path.name} has a real correlation id"
        for uuid in UUID.findall(text):
            assert uuid.startswith("00000000-0000-4000-8000-"), f"{path.name} has a real entity id"


def test_no_recorded_identifier_is_in_the_repo():
    if not RECORDINGS.is_dir():
        pytest.skip("no local recordings to compare against")
    recorded = set()
    for path in RECORDINGS.glob("*.json"):
        text = path.read_text(encoding="utf-8")
        recorded |= set(UUID.findall(text)) | set(CORRELATION_ID.findall(text))
    leaks = [
        f"{path.relative_to(ROOT)}: {token}"
        for path in repo_text_files()
        for token in recorded
        if token in path.read_text(encoding="utf-8", errors="ignore")
    ]
    assert not leaks, "Qloo response data outside var/:\n" + "\n".join(leaks)
