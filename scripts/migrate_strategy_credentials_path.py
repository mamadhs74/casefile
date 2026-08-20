"""One-off addition of strategy.credentials_path -- per-strategy YouTube
OAuth token file path (packages/publish/youtube.py), see docs/YOUTUBE_SETUP.md
and the task this was built under.

Not a migration framework (this project has none -- no Alembic, matching
the "no Redis/Celery until there's a reason" posture elsewhere). A single
script, run once by hand, operating on data/casefile.db directly.

Deliberately does not import packages.db.models or go through the
SQLModel engine, same reasoning as scripts/migrate_claim_section.py:
this script has to run *before* Strategy's model definition changes, and
reading/writing through an ORM model whose columns don't match the live
table yet is exactly the mismatch that would break. Raw sqlite3 only.

Nullable, no DEFAULT needed -- a strategy with no channel set up yet
(e.g. criminal-cases, which has no YouTube channel or publish template
either) legitimately has no credentials file, and NULL says that
honestly rather than an empty-string placeholder pretending to be a
real (missing) path.

Safety, same shape as scripts/migrate_claim_section.py:
1. Refuses to run unless data/casefile.db.bak already exists -- this
   script does not make its own backup.
2. Refuses to run twice: if strategy already has a credentials_path
   column, this is treated as an operator error and reported, not
   silently skipped.
3. Reports every table with a foreign key into strategy, and strategy's
   own row count, before touching anything.
4. The ALTER TABLE runs inside one transaction. PRAGMA foreign_key_check
   runs *inside* that transaction, before commit, and again after --
   belt-and-suspenders, matching precedent, even though a plain ADD
   COLUMN with no REFERENCES clause cannot itself create a foreign-key
   violation.
5. Prints the original and altered CREATE TABLE statements for strategy
   (from sqlite_master, not reconstructed) so the operator can diff them
   by eye.

Usage (module form -- `packages` isn't importable when this file is run as
a bare script path, since this project isn't installed as a package; see
docs/SCHEMA.md):
    uv run python -m scripts.migrate_strategy_credentials_path
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
    columns = {row[1] for row in conn.execute("PRAGMA table_info(strategy)")}
    if "credentials_path" in columns:
        raise MigrationAborted(
            "refusing to run: strategy already has a credentials_path column -- "
            "this migration has already been applied. Not re-running."
        )


def _report_referencing_tables(conn: sqlite3.Connection) -> None:
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND sql LIKE '%REFERENCES strategy%'"
    ).fetchall()
    if not rows:
        print("no tables reference strategy via a foreign key")
        return
    for (name,) in rows:
        count = conn.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0]
        print(f"table with FK into strategy: {name} ({count} rows)")


def _report_current_strategy_state(conn: sqlite3.Connection) -> None:
    total = conn.execute("SELECT COUNT(*) FROM strategy").fetchone()[0]
    print(f"strategy: {total} row(s) total -- all will get credentials_path=NULL")


def _print_strategy_ddl(conn: sqlite3.Connection, label: str) -> None:
    row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'strategy'"
    ).fetchone()
    print(f"--- {label} CREATE TABLE strategy ---")
    print(row[0] if row else "(no strategy table found)")
    print("--- end ---")


def _check_foreign_keys(conn: sqlite3.Connection, label: str) -> None:
    violations = conn.execute("PRAGMA foreign_key_check").fetchall()
    if violations:
        print(f"foreign_key_check ({label}) FAILED: {violations}")
        raise MigrationAborted(f"foreign_key_check violations after {label}: {violations}")
    print(f"foreign_key_check ({label}): clean")


def run_migration(conn: sqlite3.Connection) -> None:
    _print_strategy_ddl(conn, "original")

    conn.execute("BEGIN")
    try:
        conn.execute("ALTER TABLE strategy ADD COLUMN credentials_path VARCHAR")

        # Inside the open transaction, before commit: a violation here
        # still allows a real ROLLBACK, not a committed change that has
        # to be undone from the .bak file.
        _check_foreign_keys(conn, "pre-commit")

        conn.commit()
    except Exception:
        conn.rollback()
        raise

    # Belt-and-suspenders repeat, matching precedent: the pre-commit check
    # above is what actually guarantees safety; this one is a second,
    # independent confirmation that nothing changed between commit and
    # here.
    _check_foreign_keys(conn, "post-commit")

    _print_strategy_ddl(conn, "altered")


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
            _report_current_strategy_state(conn)
            run_migration(conn)
        finally:
            conn.close()

    except MigrationAborted as exc:
        print(f"ABORTED: {exc}", file=sys.stderr)
        return 1

    print("migration complete: strategy.credentials_path added, nullable, all rows NULL")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
