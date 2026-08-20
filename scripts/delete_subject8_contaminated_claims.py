"""One-off hard delete: subject 8's claims 4-20, a South Carolina Court
of Appeals opinion (State v. Antonio Long) involving first-degree
criminal sexual conduct against a minor, the victim identified
indirectly throughout via her named mother, Marlene Haywood ("Marlene
Haywood's minor child"). R7 (CLAUDE.md: living victims and named
individuals -- no identifying detail) and basic safety require this
never sit in the corpus at all, narratable or not.

Not a migration -- a forensic deletion, kept as a script (not run ad
hoc) for the same reason every other Tier-2 write this session is a
script: a reviewable, re-inspectable record of exactly what happened
and why, not a one-line untracked command.

Investigated before writing this, not assumed:
- Claims 4-20 (17 rows) are the ENTIRE Antonio Long case on subject 8
  -- claim ids 1-3 don't exist for this subject, and claim 21 onward is
  a different case (Hinterkaifeck, then Borden). No other subject-8
  claim belongs to this case.
- Every table with a FK into claim (found via sqlite_master, not
  assumed): claim_source, claim_entity, episode_claim, script_citation,
  plus episode.cold_open_claim_id (a plain nullable column, not a join
  table). Checked all five against claim ids 4-20: only claim_source
  has rows (17, one per claim, all citing source_id=5, a courtlistener.com
  PDF used elsewhere in this project's history purely as a length
  fixture -- docs/HANDOFF.md). claim_entity, episode_claim,
  script_citation, and episode.cold_open_claim_id have zero references
  to any of these 17 claims -- none of them was ever used in an
  episode, a script, or an entity link.
- source_id=5 itself is not deleted here -- out of scope (the task was
  claim rows and claim-dependent rows, not the source), and no other
  claim cites it, so it becomes an orphaned Source row after this runs.
  Recorded as a known follow-up, not acted on without being asked.

Safety, same shape as every other Tier-2 script this session:
1. Refuses to run unless data/casefile.db.bak already exists.
2. Refuses to run if any of the 17 target claim ids no longer exist
   (already deleted -- this script does not silently no-op a partial
   state, it aborts and asks a human to look).
3. PRAGMA foreign_key_check before and after, both printed.
4. Prints every row deleted, by id and table.

Usage (module form -- `packages` isn't importable when this file is run as
a bare script path, since this project isn't installed as a package; see
docs/SCHEMA.md):
    uv run python -m scripts.delete_subject8_contaminated_claims
"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

DB_PATH = Path("data/casefile.db")
BACKUP_PATH = Path("data/casefile.db.bak")

SUBJECT_ID = 8
TARGET_CLAIM_IDS = list(range(4, 21))  # 4..20 inclusive, 17 claims


class DeletionAborted(Exception):
    """Raised for any condition that should stop the script before or
    during the change. Caught once, at the bottom, to print a clean
    message and exit non-zero -- no partial state is ever left
    committed (the pre-commit foreign_key_check runs inside the open
    transaction, so a violation there still allows a real ROLLBACK)."""


def _require_backup() -> None:
    if not BACKUP_PATH.exists():
        raise DeletionAborted(
            f"refusing to run: {BACKUP_PATH} does not exist. "
            f"This script does not make its own backup."
        )
    print(f"backup present: {BACKUP_PATH} ({BACKUP_PATH.stat().st_size} bytes)")


def _require_targets_exist(conn: sqlite3.Connection) -> None:
    placeholders = ",".join("?" * len(TARGET_CLAIM_IDS))
    rows = conn.execute(
        f"SELECT id, subject_id FROM claim WHERE id IN ({placeholders})",
        TARGET_CLAIM_IDS,
    ).fetchall()
    found_ids = {row[0] for row in rows}
    missing = set(TARGET_CLAIM_IDS) - found_ids
    if missing:
        raise DeletionAborted(
            f"refusing to run: claim id(s) {sorted(missing)} not found -- "
            f"already deleted, or the id list is wrong. Not proceeding on a "
            f"partial or altered state."
        )
    wrong_subject = [row[0] for row in rows if row[1] != SUBJECT_ID]
    if wrong_subject:
        raise DeletionAborted(
            f"refusing to run: claim id(s) {wrong_subject} are not on subject "
            f"{SUBJECT_ID} -- not deleting a claim from a different subject."
        )
    print(f"confirmed: all {len(TARGET_CLAIM_IDS)} target claim ids exist on subject {SUBJECT_ID}")


def _check_foreign_keys(conn: sqlite3.Connection, label: str) -> None:
    violations = conn.execute("PRAGMA foreign_key_check").fetchall()
    print(f"--- PRAGMA foreign_key_check ({label}) ---")
    if violations:
        print(violations)
        raise DeletionAborted(f"foreign_key_check violations ({label}): {violations}")
    print("clean")


def run_deletion(conn: sqlite3.Connection) -> None:
    placeholders = ",".join("?" * len(TARGET_CLAIM_IDS))

    conn.execute("BEGIN")
    try:
        cs_rows = conn.execute(
            f"SELECT id FROM claim_source WHERE claim_id IN ({placeholders})",
            TARGET_CLAIM_IDS,
        ).fetchall()
        cs_ids = [row[0] for row in cs_rows]
        print(f"deleting claim_source rows {cs_ids} (claim_id in {TARGET_CLAIM_IDS})")
        conn.execute(
            f"DELETE FROM claim_source WHERE claim_id IN ({placeholders})",
            TARGET_CLAIM_IDS,
        )

        # claim_entity, episode_claim, script_citation: confirmed empty
        # for these claim ids before writing this script (see module
        # docstring) -- deleted here too, unconditionally, so this
        # script is correct even if that ever stops being true, rather
        # than silently relying on an investigation done once, by hand,
        # staying valid forever.
        for table in ("claim_entity", "episode_claim", "script_citation"):
            rows = conn.execute(
                f"SELECT id FROM {table} WHERE claim_id IN ({placeholders})",
                TARGET_CLAIM_IDS,
            ).fetchall()
            ids = [row[0] for row in rows]
            if ids:
                print(f"deleting {table} rows {ids} (claim_id in {TARGET_CLAIM_IDS})")
                conn.execute(
                    f"DELETE FROM {table} WHERE claim_id IN ({placeholders})",
                    TARGET_CLAIM_IDS,
                )
            else:
                print(f"{table}: no rows reference these claim ids")

        ep_rows = conn.execute(
            f"SELECT id, cold_open_claim_id FROM episode "
            f"WHERE cold_open_claim_id IN ({placeholders})",
            TARGET_CLAIM_IDS,
        ).fetchall()
        if ep_rows:
            print(f"clearing episode.cold_open_claim_id for episodes {[r[0] for r in ep_rows]}")
            conn.execute(
                f"UPDATE episode SET cold_open_claim_id = NULL "
                f"WHERE cold_open_claim_id IN ({placeholders})",
                TARGET_CLAIM_IDS,
            )
        else:
            print("episode.cold_open_claim_id: no episode references these claim ids")

        print(f"deleting claim rows {TARGET_CLAIM_IDS}")
        conn.execute(f"DELETE FROM claim WHERE id IN ({placeholders})", TARGET_CLAIM_IDS)

        _check_foreign_keys(conn, "pre-commit")

        conn.commit()
    except Exception:
        conn.rollback()
        raise

    _check_foreign_keys(conn, "post-commit")

    remaining = conn.execute(
        "SELECT COUNT(*) FROM claim WHERE subject_id = ?", (SUBJECT_ID,)
    ).fetchone()[0]
    print(f"subject {SUBJECT_ID}: {remaining} claim(s) remain")


def main() -> int:
    try:
        _require_backup()

        conn = sqlite3.connect(DB_PATH)
        conn.isolation_level = None
        try:
            _require_targets_exist(conn)
            run_deletion(conn)
        finally:
            conn.close()

    except DeletionAborted as exc:
        print(f"ABORTED: {exc}", file=sys.stderr)
        return 1

    print(f"deletion complete: {len(TARGET_CLAIM_IDS)} claim rows and dependents hard-deleted")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
