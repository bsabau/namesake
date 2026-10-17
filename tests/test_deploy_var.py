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
