"""One-off addition of episode_claim.thesis_bearing -- see
docs/ARCHITECTURES.md sec 4, the schema this architecture's thesis
mechanism depends on.

Not a migration framework (this project has none -- no Alembic, matching
the "no Redis/Celery until there's a reason" posture elsewhere). A single
script, run once by hand, operating on data/casefile.db directly.

Deliberately does not import packages.db.models or go through the
SQLModel engine, same reasoning as scripts/migrate_entity_living.py: this
script has to run *before* EpisodeClaim's model definition changes, and
reading/writing through an ORM model whose columns don't match the live
table yet is exactly the mismatch that would break. Raw sqlite3 only.

Mechanically simpler than migrate_entity_living.py's rebuild: that
migration relaxed an existing NOT NULL constraint, which SQLite's
ALTER TABLE can't do directly, so it had to rebuild the whole table.
Adding a brand-new column has no such restriction -- a plain
ALTER TABLE ... ADD COLUMN is sufficient, no rebuild-and-swap, no
DROP TABLE. SQLite does require a DEFAULT for a NOT NULL column added
this way (its own ALTER TABLE documentation: a NOT NULL column added by
ADD COLUMN must have a default other than NULL, to backfill existing
rows) -- DEFAULT 0 here is that requirement, not a style choice, and is
the only reason this script's DDL has a DEFAULT clause where
migrate_entity_living.py's rebuilt schema didn't need one.

Safety, in order, same shape as migrate_entity_living.py:
1. Refuses to run unless data/casefile.db.bak already exists -- this
   script doesn't make its own backup, it trusts (and checks for) one
   made beforehand.
2. Refuses to run twice: if episode_claim already has a thesis_bearing
   column, this is treated as an operator error and reported, not
   silently skipped.
3. Reports every table with a foreign key into episode_claim, and
   episode_claim's own row count, before touching anything -- discovered
   live from sqlite_master, not hardcoded or assumed empty.
4. The ALTER TABLE runs inside one transaction. PRAGMA foreign_key_check
   runs *inside* that transaction, before commit, and again after --
   belt-and-suspenders, matching migrate_entity_living.py, even though a
   plain ADD COLUMN cannot itself create a foreign-key violation.
5. Prints the original and altered CREATE TABLE statements for
   episode_claim (from sqlite_master, not reconstructed) so the operator
   can diff them by eye.

Every existing episode_claim row gets thesis_bearing=0 via the column's
DEFAULT -- there is no prior state to preserve or reset, unlike
entity.living, since this column has never existed before.
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
    columns = {row[1] for row in conn.execute("PRAGMA table_info(episode_claim)")}
    if "thesis_bearing" in columns:
        raise MigrationAborted(
            "refusing to run: episode_claim already has a thesis_bearing "
            "column -- this migration has already been applied. Not re-running."
        )


def _report_referencing_tables(conn: sqlite3.Connection) -> None:
    rows = conn.execute(
        "SELECT name FROM sqlite_master "
        "WHERE type = 'table' AND sql LIKE '%REFERENCES episode_claim%'"
    ).fetchall()
    if not rows:
        print("no tables reference episode_claim via a foreign key")
        return
    for (name,) in rows:
        count = conn.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0]
        print(f"table with FK into episode_claim: {name} ({count} rows)")


def _report_current_episode_claim_state(conn: sqlite3.Connection) -> None:
    total = conn.execute("SELECT COUNT(*) FROM episode_claim").fetchone()[0]
    print(f"episode_claim: {total} row(s) total -- all will get thesis_bearing=0")


def _print_episode_claim_ddl(conn: sqlite3.Connection, label: str) -> None:
    row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'episode_claim'"
    ).fetchone()
    print(f"--- {label} CREATE TABLE episode_claim ---")
    print(row[0] if row else "(no episode_claim table found)")
    print("--- end ---")


def _check_foreign_keys(conn: sqlite3.Connection, label: str) -> None:
    violations = conn.execute("PRAGMA foreign_key_check").fetchall()
    if violations:
        print(f"foreign_key_check ({label}) FAILED: {violations}")
        raise MigrationAborted(f"foreign_key_check violations after {label}: {violations}")
    print(f"foreign_key_check ({label}): clean")


def run_migration(conn: sqlite3.Connection) -> None:
    _print_episode_claim_ddl(conn, "original")

    conn.execute("BEGIN")
    try:
        conn.execute(
            "ALTER TABLE episode_claim "
            "ADD COLUMN thesis_bearing BOOLEAN NOT NULL DEFAULT 0"
        )

        # Inside the open transaction, before commit: a violation here
        # still allows a real ROLLBACK, not a committed change that has
        # to be undone from the .bak file.
        _check_foreign_keys(conn, "pre-commit")

        conn.commit()
    except Exception:
        conn.rollback()
        raise

    # Belt-and-suspenders repeat, matching migrate_entity_living.py: the
    # pre-commit check above is what actually guarantees safety; this one
    # is a second, independent confirmation that nothing changed between
    # commit and here.
    _check_foreign_keys(conn, "post-commit")

    _print_episode_claim_ddl(conn, "altered")


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
            _report_current_episode_claim_state(conn)
            run_migration(conn)
        finally:
            conn.close()

    except MigrationAborted as exc:
        print(f"ABORTED: {exc}", file=sys.stderr)
        return 1

    print("migration complete: episode_claim.thesis_bearing added, default False")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
