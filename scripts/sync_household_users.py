#!/usr/bin/env python3
"""Keep library/calendar shadow users aligned with dashboard (canonical roster).

Dashboard owns passwords and sessions. This script ensures every dashboard
``users.username`` exists in library and calendar with ``password_hash`` NULL
(proxy shadows). It does not copy passwords or merge app data.

Run after adding a user in dashboard:

    uv run python scripts/sync_household_users.py

Use ``--dry-run`` to preview. Use ``--prune-library`` to delete library users
that are not in dashboard and have no bookmarks/tags (same rules as sql-pass).
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
PROJECTS_ROOT = REPO_ROOT.parent
DATA_DIR = REPO_ROOT / "data"
DASHBOARD_DB = DATA_DIR / "dashboard.db"
LIBRARY_DB = PROJECTS_ROOT / "library" / "instance" / "library.db"
CALENDAR_DB = PROJECTS_ROOT / "calendar" / "instance" / "events.db"


def _dashboard_users(con: sqlite3.Connection) -> list[tuple[str, bool]]:
    rows = con.execute(
        "SELECT username, is_admin FROM users ORDER BY username"
    ).fetchall()
    if not rows:
        raise SystemExit(f"no users in dashboard DB: {DASHBOARD_DB}")
    return [(r[0], bool(r[1])) for r in rows]


def _ensure_library(
    con: sqlite3.Connection,
    username: str,
    is_admin: bool,
    *,
    dry_run: bool,
) -> str:
    row = con.execute(
        "SELECT id, role FROM users WHERE username = ?", (username,)
    ).fetchone()
    if row:
        return f"  library: {username!r} exists (id={row[0]}, role={row[1]})"
    role = "ADMIN" if is_admin else "STANDARD"
    if dry_run:
        return f"  library: would insert {username!r} role={role}"
    con.execute(
        """
        INSERT INTO users (username, password_hash, role, created_at)
        VALUES (?, NULL, ?, datetime('now'))
        """,
        (username, role),
    )
    uid = con.execute("SELECT last_insert_rowid()").fetchone()[0]
    return f"  library: inserted {username!r} (id={uid}, role={role})"


def _ensure_calendar(
    con: sqlite3.Connection, username: str, *, dry_run: bool
) -> str:
    row = con.execute(
        "SELECT id FROM users WHERE username = ?", (username,)
    ).fetchone()
    if row:
        return f"  calendar: {username!r} exists (id={row[0]})"
    if dry_run:
        return f"  calendar: would insert {username!r}"
    con.execute(
        """
        INSERT INTO users (username, password_hash, created_at)
        VALUES (?, NULL, datetime('now'))
        """,
        (username,),
    )
    uid = con.execute("SELECT last_insert_rowid()").fetchone()[0]
    return f"  calendar: inserted {username!r} (id={uid})"


def _prune_library_orphans(
    con: sqlite3.Connection, canonical: set[str], *, dry_run: bool
) -> list[str]:
    lines: list[str] = []
    rows = con.execute(
        """
        SELECT u.id, u.username,
               (SELECT COUNT(*) FROM bookmarks b WHERE b.user_id = u.id),
               (SELECT COUNT(*) FROM tags t WHERE t.user_id = u.id),
               (SELECT COUNT(*) FROM book_tags bt WHERE bt.user_id = u.id)
        FROM users u
        WHERE u.username NOT IN ({})
        """.format(",".join("?" * len(canonical))),
        tuple(canonical),
    ).fetchall()
    for uid, username, bm, tags, bt in rows:
        if bm or tags or bt:
            lines.append(
                f"  library: keep {username!r} (id={uid}) — has app data, not in dashboard"
            )
            continue
        if dry_run:
            lines.append(f"  library: would delete orphan {username!r} (id={uid})")
        else:
            con.execute("DELETE FROM users WHERE id = ?", (uid,))
            lines.append(f"  library: deleted orphan {username!r} (id={uid})")
    if not dry_run and lines:
        con.commit()
    return lines


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--prune-library",
        action="store_true",
        help="Remove library users absent from dashboard with no bookmarks/tags",
    )
    args = parser.parse_args()

    if not DASHBOARD_DB.exists():
        raise SystemExit(
            f"dashboard DB missing: {DASHBOARD_DB}\n"
            "  create the DB first: docker compose exec dashboard python -m app.cli create-admin <user>"
        )
    if not LIBRARY_DB.exists():
        raise SystemExit(f"library DB missing: {LIBRARY_DB}")
    if not CALENDAR_DB.exists():
        raise SystemExit(f"calendar DB missing: {CALENDAR_DB}")

    dash = sqlite3.connect(DASHBOARD_DB)
    roster = _dashboard_users(dash)
    dash.close()
    canonical = {u for u, _ in roster}

    print(f"Dashboard roster ({DASHBOARD_DB}):")
    for username, is_admin in roster:
        print(f"  - {username!r}  admin={is_admin}")

    lib = sqlite3.connect(LIBRARY_DB)
    cal = sqlite3.connect(CALENDAR_DB)
    try:
        print("\nSync:")
        for username, is_admin in roster:
            print(_ensure_library(lib, username, is_admin, dry_run=args.dry_run))
            print(_ensure_calendar(cal, username, dry_run=args.dry_run))
        if not args.dry_run:
            lib.commit()
            cal.commit()

        if args.prune_library:
            print("\nPrune library:")
            for line in _prune_library_orphans(
                lib, canonical, dry_run=args.dry_run
            ):
                print(line)
    finally:
        lib.close()
        cal.close()

    print("\nDone.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
