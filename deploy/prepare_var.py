"""Prepare the private cache folder before the app starts; run by deploy.sh as root in a
one-off container, so it works whatever user ssh logs in as.

    python prepare_var.py /app/var [--seed /upload/cache.sqlite] [--owner namesake]

With --seed, installs the uploaded cache only when the server's cache is missing or holds
no rows yet (the app creates an empty one when it first starts), and refuses otherwise.
Then makes sure a cache file exists, for the deploy's write check, and hands the folder to
the app's user, mode 700.
"""

import argparse
import os
import pwd
import shutil
import sqlite3
import sys
from pathlib import Path


class Refused(Exception):
    pass


def saved_rows(db: Path) -> int:
    """Rows in a cache file, in any table: saved results, Qloo answers, approvals and the
    daily usage counters all count. 0 for a missing or freshly created one."""
    if not db.exists() or db.stat().st_size == 0:
        return 0
    with sqlite3.connect(f"file:{db}?mode=ro", uri=True) as c:
        tables = [
            r[0]
            for r in c.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            )
        ]
        return sum(
            c.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0]  # noqa: S608 - from the db
            for t in tables
        )


def seed(var: Path, upload: Path) -> None:
    db = var / "cache.sqlite"
    if saved_rows(db):
        raise Refused("the server's cache already holds saved results; not overwriting")
    tmp = var / "cache.sqlite.seed"
    shutil.copyfile(upload, tmp)
    # A rename within one folder is atomic: the app sees the old file or the whole new one.
    os.replace(tmp, db)
    # The old file's journal (rollback by default, or WAL) must not meet the new file.
    for leftover in ("cache.sqlite-journal", "cache.sqlite-wal", "cache.sqlite-shm"):
        (var / leftover).unlink(missing_ok=True)


def ensure_cache(var: Path) -> None:
    """An empty cache file when there is none, so the deploy's write check can open it
    without creating it; the app adds its tables when it starts."""
    sqlite3.connect(var / "cache.sqlite").close()


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
    ensure_cache(args.var)
    hand_over(args.var, args.owner)
    return 0


if __name__ == "__main__":
    sys.exit(main())
