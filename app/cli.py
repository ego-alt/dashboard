"""Operator CLI: bootstrap admins, manage users, sweep sessions.

Run via ``uv run python -m app.cli <command>`` from the dashboard repo root.
Reads ``DATABASE_URL`` from env, same as the API.
"""

import argparse
import getpass
import sys

from app.auth import hash_password, purge_expired_sessions
from app.db import init_db, session_scope
from app.models import User


MIN_PASSWORD_LEN = 8


def _read_new_password() -> str:
    pw1 = getpass.getpass("password: ")
    pw2 = getpass.getpass("password (repeat): ")
    if pw1 != pw2:
        print("passwords do not match", file=sys.stderr)
        sys.exit(1)
    if len(pw1) < MIN_PASSWORD_LEN:
        print(f"password must be at least {MIN_PASSWORD_LEN} characters", file=sys.stderr)
        sys.exit(1)
    return pw1


def _resolve_password(explicit: str | None) -> str:
    if explicit is not None:
        if len(explicit) < MIN_PASSWORD_LEN:
            print(f"password must be at least {MIN_PASSWORD_LEN} characters", file=sys.stderr)
            sys.exit(1)
        return explicit
    return _read_new_password()


def _add_user(
    db,
    *,
    username: str,
    password: str,
    is_admin: bool,
    display_name: str | None = None,
) -> User:
    existing = db.query(User).filter(User.username == username).one_or_none()
    if existing is not None:
        print(f"user {username!r} already exists (id={existing.id})", file=sys.stderr)
        sys.exit(1)
    user = User(
        username=username,
        display_name=display_name or username,
        password_hash=hash_password(password),
        is_admin=is_admin,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _require_user(db, username: str) -> User:
    user = db.query(User).filter(User.username == username).one_or_none()
    if user is None:
        print(f"no such user: {username!r}", file=sys.stderr)
        sys.exit(1)
    return user


def cmd_create_admin(args) -> None:
    with session_scope() as db:
        user = _add_user(
            db,
            username=args.username,
            password=_resolve_password(args.password),
            is_admin=True,
            display_name=args.display_name,
        )
        print(f"created admin user {args.username!r} (id={user.id})")


def cmd_create_user(args) -> None:
    with session_scope() as db:
        user = _add_user(
            db,
            username=args.username,
            password=_resolve_password(args.password),
            is_admin=args.admin,
            display_name=args.display_name,
        )
        role = "admin" if user.is_admin else "user"
        print(f"created {role} {args.username!r} (id={user.id})")


def cmd_passwd(args) -> None:
    with session_scope() as db:
        user = _require_user(db, args.username)
        user.password_hash = hash_password(_read_new_password())
        db.commit()
        print(f"updated password for {args.username!r}")


def cmd_list_users(_args) -> None:
    with session_scope() as db:
        users = db.query(User).order_by(User.id).all()
        if not users:
            print("(no users)")
            return
        for u in users:
            tag = "admin" if u.is_admin else "user "
            last = u.last_login_at.isoformat() if u.last_login_at else "—"
            print(f"  {u.id:>3}  {u.username:<24}  [{tag}]  last_login={last}")


def cmd_purge_sessions(_args) -> None:
    with session_scope() as db:
        n = purge_expired_sessions(db)
        print(f"purged {n} expired session(s)")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="dashboard-cli")
    sub = p.add_subparsers(dest="cmd", required=True)

    p_create = sub.add_parser("create-admin", help="Create an admin user.")
    p_create.add_argument("username")
    p_create.add_argument("--display-name", default=None)
    p_create.add_argument(
        "--password",
        default=None,
        help="Non-interactive bootstrap (min 8 chars). Prefer env + getpass in normal use.",
    )
    p_create.set_defaults(func=cmd_create_admin)

    p_user = sub.add_parser("create-user", help="Create a non-admin user.")
    p_user.add_argument("username")
    p_user.add_argument("--display-name", default=None)
    p_user.add_argument(
        "--admin",
        action="store_true",
        help="Grant dashboard admin (library role is still separate).",
    )
    p_user.add_argument("--password", default=None)
    p_user.set_defaults(func=cmd_create_user)

    p_pwd = sub.add_parser("passwd", help="Change a user's password.")
    p_pwd.add_argument("username")
    p_pwd.set_defaults(func=cmd_passwd)

    p_ls = sub.add_parser("list-users", help="List all users.")
    p_ls.set_defaults(func=cmd_list_users)

    p_pg = sub.add_parser("purge-sessions", help="Delete expired sessions.")
    p_pg.set_defaults(func=cmd_purge_sessions)

    return p


def main(argv=None) -> None:
    init_db()
    args = build_parser().parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
