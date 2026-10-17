"""deploy/prepare_var.py: the private cache folder, seeded at most once. Synthetic files."""

import getpass
import importlib.util
import sqlite3
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location(
    "prepare_var", Path(__file__).parent.parent / "deploy" / "prepare_var.py"
)
prepare_var = importlib.util.module_from_spec(spec)
spec.loader.exec_module(prepare_var)


def cache(path: Path, rows: int = 0) -> Path:
    with sqlite3.connect(path) as c:
        c.execute("CREATE TABLE agent_results (key TEXT, value_json TEXT, created_at TEXT)")
        c.execute("CREATE TABLE qloo_cache (key TEXT)")
        for i in range(rows):
            c.execute("INSERT INTO agent_results VALUES (?, '{}', '')", (f"k{i}",))
    return path


def test_a_seed_replaces_a_missing_or_freshly_created_cache(tmp_path):
    # Grok: the app creates an empty cache when it starts, which blocked a later --seed.
    var = tmp_path / "var"
    var.mkdir()
    upload = cache(tmp_path / "upload.sqlite", rows=3)
    prepare_var.seed(var, upload)
    assert prepare_var.saved_rows(var / "cache.sqlite") == 3

    (var / "cache.sqlite").unlink()
    cache(var / "cache.sqlite")  # what a first start leaves behind
    prepare_var.seed(var, upload)
    assert prepare_var.saved_rows(var / "cache.sqlite") == 3
    assert not (var / "cache.sqlite.seed").exists()


def test_a_seed_never_overwrites_saved_results(tmp_path):
    var = tmp_path / "var"
    var.mkdir()
    cache(var / "cache.sqlite", rows=1)
    with pytest.raises(prepare_var.Refused):
        prepare_var.seed(var, cache(tmp_path / "upload.sqlite", rows=5))
    assert prepare_var.saved_rows(var / "cache.sqlite") == 1


def test_the_folder_is_handed_over_private(tmp_path):
    var = tmp_path / "var"
    (var / "qloo-recordings").mkdir(parents=True)
    prepare_var.hand_over(var, getpass.getuser())
    assert var.stat().st_mode & 0o777 == 0o700


def test_any_saved_row_refuses_a_seed(tmp_path):
    # DeepSeek: approvals and the daily usage counters live in the same file.
    var = tmp_path / "var"
    var.mkdir()
    with sqlite3.connect(cache(var / "cache.sqlite")) as c:
        c.execute("CREATE TABLE usage (day TEXT, kind TEXT, count INTEGER)")
        c.execute("INSERT INTO usage VALUES ('2026-10-17', 'run', 3)")
    with pytest.raises(prepare_var.Refused):
        prepare_var.seed(var, cache(tmp_path / "upload.sqlite", rows=5))


def test_a_seed_drops_the_old_files_journal(tmp_path):
    # Flash: the app keeps SQLite's default rollback journal, cache.sqlite-journal.
    var = tmp_path / "var"
    var.mkdir()
    (var / "cache.sqlite-journal").write_bytes(b"old")
    prepare_var.seed(var, cache(tmp_path / "upload.sqlite", rows=1))
    assert not (var / "cache.sqlite-journal").exists()


def test_an_unseeded_folder_gets_an_empty_cache_to_check(tmp_path):
    # Codex, muse, DeepSeek: the write check opens the cache with mode=rw, which never
    # creates it, and /health does not either.
    var = tmp_path / "var"
    var.mkdir()
    prepare_var.ensure_cache(var)
    assert prepare_var.saved_rows(var / "cache.sqlite") == 0
    sqlite3.connect(f"file:{var / 'cache.sqlite'}?mode=rw", uri=True).close()
