"""One-off addition of entity_match.match_rationale -- see docs/SCHEMA.md's
EntityMatch section and packages/research/entity_provider.py's
ProposedEntity docstring.

Not a migration framework (this project has none -- see
migrate_entity_living.py's own docstring). A single script, run once by
hand, operating on data/casefile.db directly.

Unlike migrate_entity_living.py, this is not a rebuild-and-swap: adding one
nullable column with no default to a table holding zero rows is exactly
what SQLite's own ALTER TABLE ADD COLUMN supports directly, no CREATE-
TABLE-new/copy/DROP/RENAME dance required. Deliberately does not import
packages.db.models, same reasoning as migrate_entity_living.py -- this
script has to run before EntityMatch's model definition changes to add the
field, and reading/writing through an ORM model whose columns don't match
the live table yet is exactly the mismatch that would break. Raw sqlite3
only.

Safety, in order:
1. Refuses to run unless data/casefile.db.bak already exists -- this
   script doesn't make its own backup, it trusts (and checks for) one made
   beforehand.
2. Refuses to run twice: if entity_match already has a match_rationale
   column, this is treated as an operator error and reported, not
   silently skipped.
3. Reports the current entity_match row count before touching anything --
   expected to be zero (nothing has used this table yet), but reported
   rather than assumed, since the ADD COLUMN itself is safe either way for
   a nullable column with no default.
4. Runs inside one transaction. PRAGMA foreign_key_check runs *inside*
   that transaction, before commit, and again after -- belt-and-suspenders,
   matching migrate_entity_living.py's own habit, even though a plain ADD
   COLUMN can't itself introduce a foreign-key violation.
5. Prints the original and rebuilt CREATE TABLE statements for
   entity_match (from sqlite_master, not reconstructed) so the operator
   can diff them by eye rather than trust this script's own description.
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
    columns = {row[1] for row in conn.execute("PRAGMA table_info(entity_match)")}
    if "match_rationale" in columns:
        raise MigrationAborted(
            "refusing to run: entity_match already has a match_rationale "
            "column -- this migration has already been applied. Not re-running."
        )


def _report_current_entity_match_state(conn: sqlite3.Connection) -> None:
    total = conn.execute("SELECT COUNT(*) FROM entity_match").fetchone()[0]
    print(f"entity_match: {total} rows total")


def _print_entity_match_ddl(conn: sqlite3.Connection, label: str) -> None:
    row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'entity_match'"
    ).fetchone()
    print(f"--- {label} CREATE TABLE entity_match ---")
    print(row[0] if row else "(no entity_match table found)")
    print("--- end ---")


def _check_foreign_keys(conn: sqlite3.Connection, label: str) -> None:
    violations = conn.execute("PRAGMA foreign_key_check").fetchall()
    if violations:
        print(f"foreign_key_check ({label}) FAILED: {violations}")
        raise MigrationAborted(f"foreign_key_check violations after {label}: {violations}")
    print(f"foreign_key_check ({label}): clean")


def run_migration(conn: sqlite3.Connection) -> None:
    _print_entity_match_ddl(conn, "original")

    conn.execute("BEGIN")
    try:
        conn.execute("ALTER TABLE entity_match ADD COLUMN match_rationale VARCHAR")

        # Inside the open transaction, before commit: a violation here
        # still allows a real ROLLBACK, not a committed change that has
        # to be undone from the .bak file. Nothing about ADD COLUMN
        # touches foreign keys, but this mirrors migrate_entity_living.py's
        # own habit of checking anyway.
        _check_foreign_keys(conn, "pre-commit")

        conn.commit()
    except Exception:
        conn.rollback()
        raise

    # Belt-and-suspenders repeat, same posture as migrate_entity_living.py:
    # the pre-commit check above is what actually guarantees safety; this
    # one is a second, independent confirmation that nothing changed
    # between commit and here.
    _check_foreign_keys(conn, "post-commit")

    _print_entity_match_ddl(conn, "rebuilt")


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
            _report_current_entity_match_state(conn)
            run_migration(conn)
        finally:
            conn.close()

    except MigrationAborted as exc:
        print(f"ABORTED: {exc}", file=sys.stderr)
        return 1

    print("migration complete: entity_match.match_rationale added, nullable")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
