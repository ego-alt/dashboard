#!/usr/bin/env python3
"""One-time household SQL pass: backups, library cleanup, calendar seed, dashboard users.

Run from the dashboard repo root:

    uv run python scripts/household_sql_pass.py

Optional env (recommended for non-interactive runs):

    DASHBOARD_ADMIN_PASSWORD=...
    DASHBOARD_NATALIE_PASSWORD=...

If passwords are omitted, random ones are generated and written to
``.bootstrap-credentials`` (gitignored).
"""

from __future__ import annotations

import argparse
import secrets
import shutil
import sqlite3
import string
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
PROJECTS_ROOT = REPO_ROOT.parent

# Allow `from app ...` when invoked as `python scripts/household_sql_pass.py`.
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
DATA_DIR = REPO_ROOT / "data"
LIBRARY_DB = PROJECTS_ROOT / "library" / "instance" / "library.db"
CALENDAR_DB = PROJECTS_ROOT / "calendar" / "instance" / "events.db"
DASHBOARD_DB = DATA_DIR / "dashboard.db"
LEGACY_DASHBOARD_DB = REPO_ROOT / "dashboard.db"
CREDENTIALS_FILE = REPO_ROOT / ".bootstrap-credentials"

HOUSEHOLD_USERNAMES = ("admin", "natalieha")


def _timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _ensure_dashboard_db_path() -> None:
    """Use data/dashboard.db (compose bind-mount). Move legacy repo-root file once."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if LEGACY_DASHBOARD_DB.exists() and not DASHBOARD_DB.exists():
        shutil.move(LEGACY_DASHBOARD_DB, DASHBOARD_DB)
        print(f"  moved {LEGACY_DASHBOARD_DB} -> {DASHBOARD_DB}")


def backup_file(path: Path, stamp: str) -> Path:
    dest = path.with_name(f"{path.name}.bak-{stamp}")
    if not path.exists():
        print(f"  skip backup (missing): {path}")
        return dest
    shutil.copy2(path, dest)
    print(f"  backed up: {path} -> {dest}")
    return dest


def library_cleanup(conn: sqlite3.Connection, *, dry_run: bool) -> int:
    orphans = conn.execute(
        """
        SELECT u.id, u.username,
               (SELECT COUNT(*) FROM bookmarks b WHERE b.user_id = u.id) AS bookmarks,
               (SELECT COUNT(*) FROM tags t WHERE t.user_id = u.id) AS tags,
               (SELECT COUNT(*) FROM book_tags bt WHERE bt.user_id = u.id) AS book_tags
        FROM users u
        WHERE u.username NOT IN ('admin', 'natalieha')
        """
    ).fetchall()

    to_delete = [
        row for row in orphans if row[2] == 0 and row[3] == 0 and row[4] == 0
    ]
    blocked = [row for row in orphans if row not in to_delete]

    if orphans:
        print("  library users outside household:")
        for row in orphans:
            print(f"    id={row[0]} username={row[1]!r} bookmarks={row[2]} tags={row[3]} book_tags={row[4]}")
    else:
        print("  library: no non-household users")

    if blocked:
        print("  library: NOT deleting (has data):")
        for row in blocked:
            print(f"    id={row[0]} username={row[1]!r}")

    if not to_delete:
        return 0

    if dry_run:
        print(f"  library: would delete {len(to_delete)} orphan user(s)")
        return 0

    for row in to_delete:
        conn.execute("DELETE FROM users WHERE id = ?", (row[0],))
    conn.commit()
    print(f"  library: deleted {len(to_delete)} orphan user(s)")
    return len(to_delete)


def calendar_seed_natalie(conn: sqlite3.Connection, *, dry_run: bool) -> None:
    row = conn.execute(
        "SELECT id FROM users WHERE username = 'natalieha'"
    ).fetchone()
    if row:
        print(f"  calendar: natalieha already exists (id={row[0]})")
        return
    if dry_run:
        print("  calendar: would insert natalieha")
        return
    conn.execute(
        """
        INSERT INTO users (username, password_hash, created_at)
        VALUES ('natalieha', NULL, datetime('now'))
        """
    )
    conn.commit()
    print("  calendar: inserted natalieha (id", conn.execute("SELECT last_insert_rowid()").fetchone()[0], ")")


def _random_password() -> str:
    alphabet = string.ascii_letters + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(16))


def bootstrap_dashboard(*, dry_run: bool) -> None:
    import os

    os.chdir(REPO_ROOT)
    os.environ.setdefault("DATABASE_URL", f"sqlite:///{DASHBOARD_DB}")

    admin_pw = os.environ.get("DASHBOARD_ADMIN_PASSWORD") or _random_password()
    natalie_pw = os.environ.get("DASHBOARD_NATALIE_PASSWORD") or _random_password()
    generated = not os.environ.get("DASHBOARD_ADMIN_PASSWORD") or not os.environ.get(
        "DASHBOARD_NATALIE_PASSWORD"
    )

    if dry_run:
        print("  dashboard: would init_db and ensure users admin + natalieha")
        return

    from app.cli import _add_user, init_db
    from app.db import session_scope
    from app.models import User

    init_db()
    created = []
    with session_scope() as db:
        for username, password, is_admin in (
            ("admin", admin_pw, True),
            ("natalieha", natalie_pw, False),
        ):
            existing = db.query(User).filter_by(username=username).one_or_none()
            if existing:
                print(f"  dashboard: {username!r} already exists (id={existing.id})")
                continue
            user = _add_user(
                db,
                username=username,
                password=password,
                is_admin=is_admin,
            )
            created.append(username)
            print(f"  dashboard: created {username!r} (id={user.id}, admin={is_admin})")

    if generated and created:
        CREDENTIALS_FILE.write_text(
            "\n".join(
                [
                    "# Generated by scripts/household_sql_pass.py — store safely, then delete.",
                    f"admin={admin_pw}",
                    f"natalieha={natalie_pw}",
                    "",
                ]
            ),
            encoding="utf-8",
        )
        print(f"  dashboard: wrote passwords to {CREDENTIALS_FILE}")


def verify() -> None:
    print("\n=== verification ===")
    for label, path in (
        ("library", LIBRARY_DB),
        ("calendar", CALENDAR_DB),
        ("dashboard", DASHBOARD_DB),
    ):
        if not path.exists():
            print(f"  {label}: MISSING {path}")
            continue
        con = sqlite3.connect(path)
        rows = con.execute("SELECT id, username FROM users ORDER BY id").fetchall()
        con.close()
        print(f"  {label}: {rows}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print actions without writing",
    )
    parser.add_argument(
        "--skip-dashboard",
        action="store_true",
        help="Only run library/calendar SQL",
    )
    args = parser.parse_args()
    stamp = _timestamp()

    print("Household SQL pass")
    if args.dry_run:
        print("(dry run — no writes)\n")

    print("\n1. Backups")
    if not args.dry_run:
        backup_file(LIBRARY_DB, stamp)
        backup_file(CALENDAR_DB, stamp)
        if DASHBOARD_DB.exists():
            backup_file(DASHBOARD_DB, stamp)

    print("\n2. Library orphan cleanup")
    if LIBRARY_DB.exists():
        con = sqlite3.connect(LIBRARY_DB)
        library_cleanup(con, dry_run=args.dry_run)
        con.close()
    else:
        print(f"  missing {LIBRARY_DB}")

    print("\n3. Dashboard household users")
    _ensure_dashboard_db_path()
    if args.skip_dashboard:
        print("  skipped")
    else:
        bootstrap_dashboard(dry_run=args.dry_run)

    print("\n4. Sync shadow users (library + calendar)")
    if args.dry_run:
        print("  (skipped in dry-run; run sync_household_users.py after)")
    elif LIBRARY_DB.exists() and CALENDAR_DB.exists() and DASHBOARD_DB.exists():
        import subprocess

        subprocess.run(
            [sys.executable, str(REPO_ROOT / "scripts" / "sync_household_users.py")],
            check=True,
        )
    else:
        print("  skipped (missing DB)")

    verify()
    print("\nDone.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
