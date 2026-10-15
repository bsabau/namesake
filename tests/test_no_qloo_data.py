"""Qloo's hackathon guide forbids publishing Qloo response data in a public repo.

Real recordings live in the git-ignored `var/`; tests use the hand-written
envelopes in `tests/fixtures/qloo/synthetic/`. The first three checks need
nothing private, so they hold on a fresh clone; the last also compares against
the local recordings when they are present.
"""

import json
import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
RECORDINGS = ROOT / "var" / "qloo-recordings"
SYNTHETIC = ROOT / "tests" / "fixtures" / "qloo" / "synthetic"
SKIP_DIRS = {".git", ".venv", "var", "node_modules", ".pytest_cache", ".ruff_cache", "__pycache__"}
TEXT_SUFFIXES = {".py", ".json", ".md", ".html", ".js", ".css", ".toml", ".txt", ".yml", ".yaml"}

UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.I)
SYNTHETIC_UUID = re.compile(r"00000000-0000-4000-8000-[0-9a-f]{12}", re.I)
CORRELATION_ID = re.compile(r"exec-" + UUID.pattern, re.I)
# A URL ends at whitespace or at the quote, bracket or parenthesis around it.
URL = re.compile(r"""https?://[^\s"'<>()\[\]]+""")


def publishable_files(root: Path = ROOT) -> list[Path]:
    """Tracked files plus new files git would pick up; everything on disk outside git."""
    try:
        out = subprocess.run(
            ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
            cwd=root,
            capture_output=True,
            check=True,
        ).stdout
        return [root / name for name in out.decode("utf-8").split("\0") if name]
    except (OSError, subprocess.CalledProcessError):
        return [p for p in root.rglob("*") if p.relative_to(root).parts[0] not in SKIP_DIRS]


def non_synthetic_ids(text: str) -> list[str]:
    # An ID inside a URL (a cited article, say) is not Qloo data.
    ids = [u for u in UUID.findall(URL.sub("", text)) if not SYNTHETIC_UUID.fullmatch(u)]
    return ids + CORRELATION_ID.findall(text)


def repo_text_files():
    for path in publishable_files():
        if path.is_file() and path.suffix in TEXT_SUFFIXES:
            yield path


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="ignore")


def test_only_synthetic_ids_in_the_repo():
    found = [
        f"{path.relative_to(ROOT)}: {token}"
        for path in repo_text_files()
        for token in non_synthetic_ids(read(path))
    ]
    assert not found, "IDs that look like real Qloo data:\n" + "\n".join(found)


def test_a_url_does_not_hide_the_id_next_to_it():
    # Built from parts so this file doesn't trip the repo-wide check itself.
    real = "-".join(["AAAAAAAA", "BBBB", "4CCC", "8DDD", "EEEEEEEEEEEE"])
    assert non_synthetic_ids(f'{{"url":"https://example.invalid","entity_id":"{real}"}}') == [real]
    assert non_synthetic_ids(f"[a](https://example.invalid/{real.lower()}) and {real}") == [real]
    assert non_synthetic_ids(f"see https://example.invalid/{real.lower()}") == []


def test_unusual_filenames_are_scanned(tmp_path):
    try:
        subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    except (OSError, subprocess.CalledProcessError):
        pytest.skip("git is not available")
    for name in ["café.md", 'quote".json', "tab\there.sqlite"]:
        (tmp_path / name).write_text("x", encoding="utf-8")
    names = {p.name for p in publishable_files(tmp_path)}
    assert names == {"café.md", 'quote".json', "tab\there.sqlite"}


def test_envelopes_only_in_the_synthetic_folder():
    stray = []
    for path in repo_text_files():
        if path.suffix != ".json" or path.parent == SYNTHETIC:
            continue
        try:
            data = json.loads(read(path))
        except ValueError:
            continue
        if isinstance(data, dict) and {"schema_version", "operation"} <= data.keys():
            stray.append(str(path.relative_to(ROOT)))
    assert not stray, "Qloo envelopes outside the synthetic folder:\n" + "\n".join(stray)


def test_no_database_is_publishable():
    databases = [
        str(p.relative_to(ROOT))
        for p in publishable_files()
        if p.suffix in {".sqlite", ".sqlite3", ".db"}
    ]
    assert not databases, f"databases may hold cached Qloo data: {databases}"


def test_synthetic_fixtures_parse():
    files = sorted(SYNTHETIC.glob("*.json"))
    assert files, "expected synthetic fixtures"
    for path in files:
        json.loads(read(path))


def test_no_recorded_identifier_is_in_the_repo():
    if not RECORDINGS.is_dir():
        pytest.skip("no local recordings to compare against")
    recorded = set()
    for path in RECORDINGS.glob("*.json"):
        text = read(path)
        recorded |= {t.lower() for t in UUID.findall(text) + CORRELATION_ID.findall(text)}
    leaks = [
        f"{path.relative_to(ROOT)}: {token}"
        for path in repo_text_files()
        for token in sorted(recorded & {t.lower() for t in UUID.findall(read(path))})
    ]
    assert not leaks, "Qloo response data outside var/:\n" + "\n".join(leaks)
