"""Prepare the private cache folder before the app starts; run by deploy.sh as root in a
one-off container, so it works whatever user ssh logs in as.

    python prepare_var.py /app/var [--seed /upload/cache.sqlite] [--owner namesake]

With --seed, installs the uploaded cache only when the server's cache is missing or holds
no saved results or Qloo answers yet (the app creates an empty one when it first starts),
and refuses otherwise. Then hands the folder to the app's user, mode 700.
"""

import argparse
import os
import pwd
import shutil
import sqlite3
import sys
from pathlib import Path

DATA_TABLES = ("agent_results", "qloo_cache")


class Refused(Exception):
    pass


def saved_rows(db: Path) -> int:
    """Rows of real data in a cache file; 0 for a missing or freshly created one."""
    if not db.exists() or db.stat().st_size == 0:
        return 0
    with sqlite3.connect(f"file:{db}?mode=ro", uri=True) as c:
        tables = {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        return sum(
            c.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]  # noqa: S608 - fixed names
            for t in DATA_TABLES
            if t in tables
        )


def seed(var: Path, upload: Path) -> None:
    db = var / "cache.sqlite"
    if saved_rows(db):
        raise Refused("the server's cache already holds saved results; not overwriting")
    tmp = var / "cache.sqlite.seed"
    shutil.copyfile(upload, tmp)
    # A rename within one folder is atomic: the app sees the old file or the whole new one.
    os.replace(tmp, db)
    for leftover in ("cache.sqlite-wal", "cache.sqlite-shm"):
        (var / leftover).unlink(missing_ok=True)


def hand_over(var: Path, owner: str) -> None:
    user = pwd.getpwnam(owner)
    for path in [var, *var.rglob("*")]:
        os.chown(path, user.pw_uid, user.pw_gid)
    var.chmod(0o700)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("var", type=Path)
    parser.add_argument("--seed", type=Path)
    parser.add_argument("--owner", default="namesake")
    args = parser.parse_args()
    args.var.mkdir(parents=True, exist_ok=True)
    try:
        if args.seed is not None:
            seed(args.var, args.seed)
            print("seeded the cache")
    except Refused as exc:
        print(f"✗ {exc}", file=sys.stderr)
        return 1
    hand_over(args.var, args.owner)
    return 0


if __name__ == "__main__":
    sys.exit(main())
