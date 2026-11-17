"""Hand the single-user `local` projects to one AIGCDO user. Dry run unless --apply.

    uv run python scripts/aigcdo_migrate_local_projects.py --gateway-user-id 123 [--apply]

Run with the API stopped and the deployment's NOVELVIDEO_* / AIGCDO_STATE_DIR environment.
Project ids and directories are kept; only the owner changes. The target must have logged
in once, so the stable local identity for that gateway user id already exists; pass
--create-identity to pre-create it for a user who has not logged in here yet.
"""

from __future__ import annotations

import argparse
import os
import shutil
import sqlite3
import time
from pathlib import Path


def migrate(
    projects_db: Path, sessions_db: Path, gateway_user_id: int, *, apply: bool,
    create_identity: bool = False,
) -> list[str]:
    if create_identity and apply:
        # The store's own table and id scheme; the first real login adopts this row by gateway id.
        from ulid import ULID

        sessions_db.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.close(os.open(sessions_db, os.O_CREAT | os.O_RDWR, 0o600))
        user_id = str(ULID())
        with sqlite3.connect(sessions_db) as identities:
            identities.execute("""CREATE TABLE IF NOT EXISTS identities (
                id TEXT PRIMARY KEY, gateway_id INTEGER NOT NULL UNIQUE,
                username TEXT NOT NULL UNIQUE, role TEXT NOT NULL, status TEXT NOT NULL)""")
            identities.execute(
                "INSERT OR IGNORE INTO identities VALUES (?, ?, ?, 'user', 'active')",
                (user_id, gateway_user_id, f"aigcdo_{user_id.lower()}"),
            )
    row = None
    if sessions_db.exists():
        with sqlite3.connect(f"file:{sessions_db}?mode=ro", uri=True) as identities:
            row = identities.execute(
                "SELECT id, username, status FROM identities WHERE gateway_id=?", (gateway_user_id,),
            ).fetchone()
    if row is None and create_identity and not apply:
        row = ("(new)", "(new)", "active")  # dry run: nothing is written
    if row is None or row[2] != "active":
        raise SystemExit(
            "target gateway user has no active local identity; log in once first or pass --create-identity"
        )
    user_id, username, _ = row
    db = sqlite3.connect(projects_db)
    try:
        names = [name for (name,) in db.execute(
            "SELECT name FROM projects WHERE owner_type='user' AND owner_id='local' ORDER BY name")]
        clashes = [name for (name,) in db.execute(
            """SELECT name FROM projects WHERE owner_type='user' AND owner_id=? AND name IN
               (SELECT name FROM projects WHERE owner_type='user' AND owner_id='local')""", (user_id,))]
        if clashes:
            raise SystemExit("target already owns projects named: " + ", ".join(clashes))
        if apply and names:
            backup = projects_db.with_name(f"{projects_db.name}.before-aigcdo-{int(time.time())}")
            shutil.copy2(projects_db, backup)
            print(f"backup: {backup}")
            with db:
                db.execute(
                    "UPDATE projects SET owner_id=?, owner_username=? WHERE owner_type='user' AND owner_id='local'",
                    (user_id, username),
                )
        return names
    finally:
        db.close()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--gateway-user-id", type=int, required=True)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument(
        "--create-identity", action="store_true",
        help="pre-create the local identity for a gateway user who has not logged in here yet",
    )
    args = parser.parse_args()
    from novelvideo import config

    names = migrate(
        Path(config.STATE_DIR) / "local" / "projects.db",
        Path(os.environ["AIGCDO_STATE_DIR"]) / "sessions.db",
        args.gateway_user_id, apply=args.apply, create_identity=args.create_identity,
    )
    print(("migrated" if args.apply else "would migrate") + f" {len(names)} projects: " + ", ".join(names))


if __name__ == "__main__":
    main()
