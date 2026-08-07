"""Regression test for the exact command README.md documents.

scripts/seed_dev.py briefly documented (and was invoked as) a bare script
path -- `uv run python scripts/seed_dev.py` -- which fails with
ModuleNotFoundError: No module named 'packages', the same reason
extract_claims.py and fetch_source.py both document module-form invocation
instead. No existing test caught this: every other test imports project
modules directly, never through a subprocess the way an operator actually
runs this command, so the documented interface broke while the suite
stayed green. This test runs the real command against a scratch database,
never data/casefile.db.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def _run_seed_dev(db_path: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "scripts.seed_dev"],
        cwd=REPO_ROOT,
        env={**os.environ, "CASEFILE_DB_PATH": str(db_path)},
        capture_output=True,
        text=True,
        timeout=30,
    )


def test_documented_seed_command_runs_against_a_scratch_db(tmp_path: Path) -> None:
    """The exact command README.md's "Seeding local data" section shows."""
    db_path = tmp_path / "seed_dev_regression.db"

    result = _run_seed_dev(db_path)

    assert result.returncode == 0, result.stderr
    assert "ModuleNotFoundError" not in result.stderr
    assert db_path.exists()


def test_documented_seed_command_is_safe_to_rerun(tmp_path: Path) -> None:
    """README.md: "Safe to re-run: it checks for existing cases first and
    does nothing if the database is already seeded." """
    db_path = tmp_path / "seed_dev_regression.db"

    first = _run_seed_dev(db_path)
    second = _run_seed_dev(db_path)

    assert first.returncode == 0, first.stderr
    assert second.returncode == 0, second.stderr
