"""One-off rebuild of the entity table: living becomes nullable, plus four
new living_evidence* columns -- see docs/SCHEMA.md's Entity section.

Not a migration framework (this project has none -- no Alembic, matching
the "no Redis/Celery until there's a reason" posture elsewhere). A single
script, run once by hand, operating on data/casefile.db directly.

Deliberately does not import packages.db.models or go through the
SQLModel engine: this script has to run *before* Entity's model
definition changes (see docs/SCHEMA.md), and reading/writing through an
ORM model whose columns don't match the live table yet is exactly the
mismatch that would break. Raw sqlite3 only.

Safety, in order:
1. Refuses to run unless data/casefile.db.bak already exists -- this
   script doesn't make its own backup, it trusts (and checks for) one
   made beforehand.
2. Refuses to run twice: if entity already has a living_evidence column,
   this is treated as an operator error and reported, not silently
   skipped.
3. Reports every table with a foreign key into entity, and its row
   count, before touching anything -- discovered live from
   sqlite_master, not hardcoded, in case something changes later.
4. The rebuild runs inside one transaction. PRAGMA foreign_key_check runs
   *inside* that transaction, before commit -- a violation triggers a
   real ROLLBACK, not a committed change that has to be undone from the
   .bak file. It also runs again after commit, belt-and-suspenders,
   matching this codebase's habit of a second, independent check where
   the first one already ought to be enough.
5. Prints the original and rebuilt CREATE TABLE statements for entity
   (from sqlite_master, not reconstructed) so the operator can diff them
   by eye rather than trust this script's own description of the change.

Every existing entity row's living (and the four new living_evidence*
columns) is reset to NULL unconditionally, regardless of its current
value. This is not "reset if unreviewed" -- the current schema cannot
distinguish a reviewed False from an unreviewed one, which is the
defect this whole change exists to fix, so there is no value in the
current living column worth preserving.
"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

DB_PATH = Path("data/casefile.db")
BACKUP_PATH = Path("data/casefile.db.bak")

# Explicit target schema for the rebuilt table. Every column and
# constraint from the original is accounted for here by hand (verified
# against sqlite_master before writing this script -- the original has
# nothing beyond PRIMARY KEY(id) and FOREIGN KEY(subject_id) REFERENCES
# subject(id), no UNIQUE or CHECK constraints), plus the new nullable
# columns docs/SCHEMA.md specifies.
ENTITY_NEW_SCHEMA = """
CREATE TABLE entity_new (
    id INTEGER NOT NULL,
    created_at DATETIME NOT NULL,
    updated_at DATETIME NOT NULL,
    subject_id INTEGER NOT NULL,
    name VARCHAR NOT NULL,
    role VARCHAR(12) NOT NULL,
    living BOOLEAN,
    living_evidence_source_id INTEGER,
    living_evidence VARCHAR,
    living_evidence_span_start INTEGER,
    living_evidence_span_end INTEGER,
    adjudicated BOOLEAN NOT NULL,
    image_rights VARCHAR(13) NOT NULL,
    PRIMARY KEY (id),
    FOREIGN KEY(subject_id) REFERENCES subject (id),
    FOREIGN KEY(living_evidence_source_id) REFERENCES source (id)
)
"""

_ENTITY_COLUMNS = (
    "id",
    "created_at",
    "updated_at",
    "subject_id",
    "name",
    "role",
    "adjudicated",
    "image_rights",
)


class MigrationAborted(Exception):
    """Raised for any condition that should stop the script before or
    during the rebuild. Caught once, at the bottom, to print a clean
    message and exit non-zero -- no partial state is ever left committed
    (see the pre-commit foreign_key_check in run_rebuild)."""


def _require_backup() -> None:
    if not BACKUP_PATH.exists():
        raise MigrationAborted(
            f"refusing to run: {BACKUP_PATH} does not exist. "
            f"This script does not make its own backup -- copy "
            f"{DB_PATH} to {BACKUP_PATH} first."
        )
    print(f"backup present: {BACKUP_PATH} ({BACKUP_PATH.stat().st_size} bytes)")


def _refuse_if_already_migrated(conn: sqlite3.Connection) -> None:
    columns = {row[1] for row in conn.execute("PRAGMA table_info(entity)")}
    if "living_evidence" in columns:
        raise MigrationAborted(
            "refusing to run: entity already has a living_evidence column "
            "-- this migration has already been applied. Not re-running."
        )


def _report_referencing_tables(conn: sqlite3.Connection) -> None:
    rows = conn.execute(
        "SELECT name, sql FROM sqlite_master "
        "WHERE type = 'table' AND sql LIKE '%REFERENCES entity%'"
    ).fetchall()
    if not rows:
        print("no tables reference entity via a foreign key")
        return
    for name, _sql in rows:
        count = conn.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0]
        print(f"table with FK into entity: {name} ({count} rows)")


def _report_current_entity_state(conn: sqlite3.Connection) -> None:
    total = conn.execute("SELECT COUNT(*) FROM entity").fetchone()[0]
    living_true = conn.execute("SELECT COUNT(*) FROM entity WHERE living = 1").fetchone()[0]
    living_false = conn.execute("SELECT COUNT(*) FROM entity WHERE living = 0").fetchone()[0]
    print(
        f"entity: {total} rows total, {living_true} living=1, "
        f"{living_false} living=0 -- all will become living=NULL"
    )


def _print_entity_ddl(conn: sqlite3.Connection, label: str) -> None:
    row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'entity'"
    ).fetchone()
    print(f"--- {label} CREATE TABLE entity ---")
    print(row[0] if row else "(no entity table found)")
    print("--- end ---")


def _check_foreign_keys(conn: sqlite3.Connection, label: str) -> None:
    violations = conn.execute("PRAGMA foreign_key_check").fetchall()
    if violations:
        print(f"foreign_key_check ({label}) FAILED: {violations}")
        raise MigrationAborted(f"foreign_key_check violations after {label}: {violations}")
    print(f"foreign_key_check ({label}): clean")


def run_rebuild(conn: sqlite3.Connection) -> None:
    _print_entity_ddl(conn, "original")

    conn.execute("PRAGMA foreign_keys = OFF")

    conn.execute("BEGIN")
    try:
        conn.execute(ENTITY_NEW_SCHEMA)

        select_cols = ", ".join(_ENTITY_COLUMNS)
        conn.execute(
            f"""
            INSERT INTO entity_new (
                {select_cols},
                living, living_evidence_source_id, living_evidence,
                living_evidence_span_start, living_evidence_span_end
            )
            SELECT {select_cols}, NULL, NULL, NULL, NULL, NULL
            FROM entity
            """
        )

        conn.execute("DROP TABLE entity")
        conn.execute("ALTER TABLE entity_new RENAME TO entity")
        conn.execute("CREATE INDEX ix_entity_living ON entity (living)")
        conn.execute("CREATE INDEX ix_entity_subject_id ON entity (subject_id)")

        # Inside the open transaction, before commit: a violation here
        # still allows a real ROLLBACK, not a committed change that has
        # to be undone from the .bak file.
        _check_foreign_keys(conn, "pre-commit")

        conn.commit()
    except Exception:
        conn.rollback()
        raise

    conn.execute("PRAGMA foreign_keys = ON")

    # Belt-and-suspenders repeat, as asked for -- the pre-commit check
    # above is what actually guarantees safety; this one is a second,
    # independent confirmation that nothing changed between commit and
    # here, matching this codebase's habit of re-checking a thing that
    # ought to already be settled (see claim_extraction.py's defensive
    # claim_type re-check).
    _check_foreign_keys(conn, "post-commit")

    _print_entity_ddl(conn, "rebuilt")


def main() -> int:
    try:
        _require_backup()

        conn = sqlite3.connect(DB_PATH)
        # Manual transaction control only -- sqlite3's default
        # isolation_level auto-wraps DML in its own implicit transaction,
        # which would conflict with the explicit BEGIN/COMMIT/ROLLBACK
        # run_rebuild depends on for the pre-commit foreign_key_check.
        conn.isolation_level = None
        try:
            _refuse_if_already_migrated(conn)
            _report_referencing_tables(conn)
            _report_current_entity_state(conn)
            run_rebuild(conn)
        finally:
            conn.close()

    except MigrationAborted as exc:
        print(f"ABORTED: {exc}", file=sys.stderr)
        return 1

    print("migration complete: entity.living is now nullable, all rows reset to NULL")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
