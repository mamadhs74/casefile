"""Single entry point: create_episode -> tag_sections -> compose_episode
-> render_episode -> upload, chained. Each stage is one of this
project's already-built, independently-runnable scripts, called as a
function (not shelled out to) -- scripts/create_episode.py,
scripts/tag_sections.py, scripts/compose_episode.py,
scripts/render_episode.py, packages/publish/youtube.py.

RUN ID: derived deterministically from (subject_id, thesis) -- a short
hash of the thesis text, prefixed with the subject id -- not a separate
CLI argument. Re-running this script with the exact same --subject-id
and --thesis therefore always resolves to the same run_id, which is
what makes "re-running resumes" work without the caller having to
remember or pass an id. A different thesis for the same subject is a
genuinely different run (docs/SCHEMA.md's own "two users covering the
same case are expected to produce different Episodes" reasoning) and
gets its own run_id and its own outputs/state files.

STATE: state/<run_id>.json. Each of the five stages records "completed"
(with a timestamp) or "failed" (with the exception's repr) -- nothing
else. On startup, the state file is loaded (or created fresh if this
run_id has never run) and every stage already marked "completed" is
skipped outright -- not re-verified, not re-run. The run resumes at the
first stage that is not yet "completed" (pending, or previously
failed). NO STAGE IS EVER RETRIED AUTOMATICALLY: a failure marks that
stage "failed" in the state file and this script exits immediately.
Re-running the same --subject-id/--thesis afterward is what retries a
failed stage -- a deliberate human decision to try again, not a loop
this script runs on its own.

OUTPUTS: outputs/<run_id>/, containing composed_script.json (written by
the compose_episode stage), the narration wavs and final.mp4 (written
by the render_episode stage) -- both stages already write exactly this
shape when given this directory, unchanged from how
scripts/compose_episode.py / scripts/render_episode.py behave when run
standalone with --episode-id (which default to outputs/<episode_id>/
instead -- this script overrides that default to outputs/<run_id>/ so
a re-run under a *different* thesis for the same subject, which is a
different run_id but could reuse the same episode_id if create_episode
were ever changed to allow a second episode per subject, never
collides on output files).

--stop-after <stage>: run up to and including that stage, then exit 0
without attempting the next one. Choices are exactly the five stage
names.

KNOWN ORDERING DEPENDENCY, not fixed here: create_episode's pool
derivation (scripts/create_episode.py) requires at least one of the
subject's sources to already have a claim tagged Section.RESOLUTION --
that's what "qualifying source" means there. For subject 10, this
already held (this session's own hand-tagging, since corrected and
re-verified) before this pipeline ever ran end to end, so the chain
create_episode -> tag_sections -> ... worked in the order given. For a
genuinely fresh, never-tagged subject, the create_episode stage will
fail immediately (SetupAborted: "no source with a RESOLUTION-tagged
claim") specifically because tag_sections hasn't run yet to produce
that tag -- tag_sections is stage 2, after create_episode, per the
task this was built under. The practical workaround today, for a new
subject, is running `scripts.tag_sections --subject-id <id>` (write
mode) once, by hand, before the first scripts.run_episode run against
it. Not reordered here since the stage order was given explicitly, not
inferred -- flagging it rather than silently working around it.

Usage:
    uv run python -m scripts.run_episode --subject-id 10 --thesis "..."
    uv run python -m scripts.run_episode --subject-id 10 --thesis "..." --stop-after render_episode
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import sys
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from packages.db.models import Episode, Strategy, Subject
from packages.db.session import get_session
from packages.publish.templates import PublishMetadataInput, get_publish_template
from packages.publish.youtube import UploadRequest, YouTubeUploader
from scripts.compose_episode import run_compose
from scripts.create_episode import create_episode_for_subject
from scripts.render_episode import render_episode
from scripts.tag_sections import run_tag_sections

STATE_DIR = Path("state")
OUTPUTS_DIR = Path("outputs")

STAGE_ORDER = ["create_episode", "tag_sections", "compose_episode", "render_episode", "upload"]


class MissingCredentialsPathError(Exception):
    """The upload stage requires Strategy.credentials_path -- if it's
    NULL, this stops the run with a clear message rather than skipping
    the stage silently, per the task this was built under."""

    def __init__(self, strategy_slug: str) -> None:
        self.strategy_slug = strategy_slug
        super().__init__(
            f"strategy {strategy_slug!r} has no credentials_path set -- see "
            f"docs/YOUTUBE_SETUP.md, then set Strategy.credentials_path for "
            f"this strategy before uploading"
        )


def _derive_run_id(subject_id: int, thesis: str) -> str:
    digest = hashlib.sha256(thesis.encode()).hexdigest()[:12]
    return f"subj{subject_id}-{digest}"


def _state_path(run_id: str) -> Path:
    return STATE_DIR / f"{run_id}.json"


def _load_state(run_id: str, subject_id: int, thesis: str) -> dict[str, Any]:
    path = _state_path(run_id)
    if path.exists():
        state: dict[str, Any] = json.loads(path.read_text())
        return state
    return {
        "run_id": run_id,
        "subject_id": subject_id,
        "thesis": thesis,
        "episode_id": None,
        "stages": {
            name: {"status": "pending", "error": None, "completed_at": None}
            for name in STAGE_ORDER
        },
    }


def _save_state(state: dict[str, Any]) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    _state_path(state["run_id"]).write_text(json.dumps(state, indent=2))


def _is_completed(state: dict[str, Any], name: str) -> bool:
    status: str = state["stages"][name]["status"]
    return status == "completed"


def _mark_completed(state: dict[str, Any], name: str) -> None:
    state["stages"][name] = {
        "status": "completed",
        "error": None,
        "completed_at": datetime.now(UTC).isoformat(),
    }
    _save_state(state)


def _mark_failed(state: dict[str, Any], name: str, exc: BaseException) -> None:
    state["stages"][name] = {
        "status": "failed",
        "error": repr(exc),
        "completed_at": None,
    }
    _save_state(state)


async def _run_stage(state: dict[str, Any], name: str, fn: Callable[[], Awaitable[None]]) -> None:
    """Runs stage `name` via `fn()` unless the state file already marks
    it "completed", in which case it's skipped outright. On failure,
    records "failed" (with the exception's repr) and re-raises -- the
    caller stops the whole run; there is no retry anywhere in this
    function."""
    if _is_completed(state, name):
        print(f"[{name}] already completed, skipping")
        return
    print(f"[{name}] running...")
    try:
        await fn()
    except Exception as exc:
        _mark_failed(state, name, exc)
        print(f"[{name}] FAILED, stopping (no retry): {exc!r}", file=sys.stderr)
        raise
    _mark_completed(state, name)
    print(f"[{name}] completed")


def _do_upload(episode_id: int, output_dir: Path) -> None:
    with get_session() as session:
        episode = session.get(Episode, episode_id)
        assert episode is not None
        subject = session.get(Subject, episode.subject_id)
        assert subject is not None
        strategy = session.get(Strategy, subject.strategy_id)
        assert strategy is not None

        if strategy.credentials_path is None:
            raise MissingCredentialsPathError(strategy.slug)

        template = get_publish_template(strategy.slug)
        composed = json.loads((output_dir / "composed_script.json").read_text())
        metadata = template(
            PublishMetadataInput(
                subject_title=subject.title,
                thesis=episode.thesis or "",
                event_year=subject.event_year,
            )
        )
        print(f"upload metadata: title={metadata.title!r}, tags={metadata.tags}")
        composed_sections = sorted(k for k in composed if k in ("ground", "sequence", "resolution"))
        print(f"composed sections present: {composed_sections}")

        uploader = YouTubeUploader(Path(strategy.credentials_path))
        result = uploader.upload(
            UploadRequest(
                video_path=output_dir / "final.mp4",
                title=metadata.title,
                description=metadata.description,
                tags=metadata.tags,
            )
        )
        print(f"uploaded: {result.studio_url} (video_id={result.video_id})")


async def _run(subject_id: int, thesis: str, stop_after: str | None) -> int:
    run_id = _derive_run_id(subject_id, thesis)
    print(f"run_id: {run_id}")
    state = _load_state(run_id, subject_id, thesis)
    output_dir = OUTPUTS_DIR / run_id

    load_dotenv()
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        print("GEMINI_API_KEY is not set (see .env.example).", file=sys.stderr)
        return 1

    async def _create_episode_stage() -> None:
        episode_id = create_episode_for_subject(subject_id, thesis)
        state["episode_id"] = episode_id

    async def _tag_sections_stage() -> None:
        await run_tag_sections(subject_id, api_key)

    async def _compose_stage() -> None:
        assert state["episode_id"] is not None
        await run_compose(state["episode_id"], output_dir, api_key)

    async def _render_stage() -> None:
        assert state["episode_id"] is not None
        render_episode(state["episode_id"], output_dir)

    async def _upload_stage() -> None:
        assert state["episode_id"] is not None
        _do_upload(state["episode_id"], output_dir)

    stages: list[tuple[str, Callable[[], Awaitable[None]]]] = [
        ("create_episode", _create_episode_stage),
        ("tag_sections", _tag_sections_stage),
        ("compose_episode", _compose_stage),
        ("render_episode", _render_stage),
        ("upload", _upload_stage),
    ]

    try:
        for name, fn in stages:
            await _run_stage(state, name, fn)
            if stop_after == name:
                print(f"--stop-after {name}: stopping")
                return 0
    except Exception:
        return 1

    return 0


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--subject-id", type=int, required=True)
    parser.add_argument("--thesis", type=str, required=True)
    parser.add_argument("--stop-after", choices=STAGE_ORDER, default=None)
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    return asyncio.run(_run(args.subject_id, args.thesis, args.stop_after))


if __name__ == "__main__":
    sys.exit(main())
