"""One-off addition of episode.cold_open_claim_id -- see
docs/ARCHITECTURES.md sec 3.1, the cold-open selection mechanism this
architecture depends on.

Not a migration framework (this project has none -- no Alembic, matching
the "no Redis/Celery until there's a reason" posture elsewhere). A single
script, run once by hand, operating on data/casefile.db directly.

Deliberately does not import packages.db.models or go through the
SQLModel engine, same reasoning as every other migration script here:
this has to run *before* Episode's model definition changes, and
reading/writing through an ORM model whose columns don't match the live
table yet is exactly the mismatch that would break. Raw sqlite3 only.

Unlike claim.section and episode_claim.thesis_bearing, this column
carries a real REFERENCES clause -- confirmed empirically against a
scratch database before writing this script, not assumed from SQLite's
documentation: ALTER TABLE ... ADD COLUMN ... REFERENCES claim(id) is
valid DDL, produces a real entry PRAGMA foreign_key_check inspects, and
a dangling value written through it while PRAGMA foreign_keys is at
SQLite's default (OFF) is silently accepted at write time and only
caught by an explicit foreign_key_check afterward -- confirmed that
exact sequence directly, including that turning PRAGMA foreign_keys ON
rejects the same write immediately instead. packages/db/session.py never
sets PRAGMA foreign_keys = ON anywhere (grepped, confirmed), so this
column's REFERENCES clause is declarative only at runtime for this
codebase's actual running connections -- it documents intent and is
checkable on demand, it does not enforce anything by itself. This is why
generate_script (future work, not this script) has to validate at
generation time that cold_open_claim_id: (a) refers to a claim that
actually exists, (b) belongs to the episode's own claim set, and (c) is
thesis-bearing -- none of the three are guaranteed by this column alone.

Safety, in order, same shape as every migration script here:
1. Refuses to run unless data/casefile.db.bak already exists.
2. Refuses to run twice: if episode already has a cold_open_claim_id
   column, this is treated as an operator error and reported, not
   silently skipped.
3. Reports every table with a foreign key into episode, and episode's
   own row count, before touching anything -- discovered live from
   sqlite_master, not hardcoded.
4. The ALTER TABLE runs inside one transaction. PRAGMA foreign_key_check
   runs *inside* that transaction, before commit, and again after.
   Unlike claim.section's migration, this check is not just belt-and-
   suspenders here -- this column really can carry a violation, even
   though none exists yet (every episode row's new column starts NULL,
   and NULL never violates a foreign key).
5. Prints the original and altered CREATE TABLE statements for episode
   (from sqlite_master, not reconstructed) so the operator can diff them
   by eye.

Every existing episode row gets cold_open_claim_id=NULL -- there is no
prior state to preserve, since this column has never existed before.
"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

DB_PATH = Path("data/casefile.db")
BACKUP_PATH = Path("data/casefile.db.bak")


class MigrationAborted(Exception):
    """Raised for any condition that should stop the script before or
    during the change. Caught once, at the bottom, to print a clean
    message and exit non-zero -- no partial state is ever left committed
    (see the pre-commit foreign_key_check in run_migration)."""


def _require_backup() -> None:
    if not BACKUP_PATH.exists():
        raise MigrationAborted(
            f"refusing to run: {BACKUP_PATH} does not exist. "
            f"This script does not make its own backup -- copy "
            f"{DB_PATH} to {BACKUP_PATH} first."
        )
    print(f"backup present: {BACKUP_PATH} ({BACKUP_PATH.stat().st_size} bytes)")


def _refuse_if_already_migrated(conn: sqlite3.Connection) -> None:
    columns = {row[1] for row in conn.execute("PRAGMA table_info(episode)")}
    if "cold_open_claim_id" in columns:
        raise MigrationAborted(
            "refusing to run: episode already has a cold_open_claim_id column -- "
            "this migration has already been applied. Not re-running."
        )


def _report_referencing_tables(conn: sqlite3.Connection) -> None:
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND sql LIKE '%REFERENCES episode%'"
    ).fetchall()
    if not rows:
        print("no tables reference episode via a foreign key")
        return
    for (name,) in rows:
        count = conn.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0]
        print(f"table with FK into episode: {name} ({count} rows)")


def _report_current_episode_state(conn: sqlite3.Connection) -> None:
    total = conn.execute("SELECT COUNT(*) FROM episode").fetchone()[0]
    print(f"episode: {total} row(s) total -- all will get cold_open_claim_id=NULL")


def _print_episode_ddl(conn: sqlite3.Connection, label: str) -> None:
    row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'episode'"
    ).fetchone()
    print(f"--- {label} CREATE TABLE episode ---")
    print(row[0] if row else "(no episode table found)")
    print("--- end ---")


def _check_foreign_keys(conn: sqlite3.Connection, label: str) -> None:
    violations = conn.execute("PRAGMA foreign_key_check").fetchall()
    if violations:
        print(f"foreign_key_check ({label}) FAILED: {violations}")
        raise MigrationAborted(f"foreign_key_check violations after {label}: {violations}")
    print(f"foreign_key_check ({label}): clean")


def run_migration(conn: sqlite3.Connection) -> None:
    _print_episode_ddl(conn, "original")

    conn.execute("BEGIN")
    try:
        conn.execute(
            "ALTER TABLE episode ADD COLUMN cold_open_claim_id INTEGER REFERENCES claim(id)"
        )

        # Inside the open transaction, before commit: a violation here
        # still allows a real ROLLBACK, not a committed change that has
        # to be undone from the .bak file. Every row's new column is
        # NULL at this point, which cannot violate the FK, but this
        # still runs -- it's the same check the running app will never
        # perform on its own, since packages/db/session.py never sets
        # PRAGMA foreign_keys = ON.
        _check_foreign_keys(conn, "pre-commit")

        conn.commit()
    except Exception:
        conn.rollback()
        raise

    # Belt-and-suspenders repeat, matching precedent.
    _check_foreign_keys(conn, "post-commit")

    _print_episode_ddl(conn, "altered")


def main() -> int:
    try:
        _require_backup()

        conn = sqlite3.connect(DB_PATH)
        # Manual transaction control only -- sqlite3's default
        # isolation_level auto-wraps DML in its own implicit transaction,
        # which would conflict with the explicit BEGIN/COMMIT/ROLLBACK
        # run_migration depends on for the pre-commit foreign_key_check.
        conn.isolation_level = None
        try:
            _refuse_if_already_migrated(conn)
            _report_referencing_tables(conn)
            _report_current_episode_state(conn)
            run_migration(conn)
        finally:
            conn.close()

    except MigrationAborted as exc:
        print(f"ABORTED: {exc}", file=sys.stderr)
        return 1

    print("migration complete: episode.cold_open_claim_id added, nullable FK to claim.id")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
