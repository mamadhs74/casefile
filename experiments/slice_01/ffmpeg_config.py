"""Pinned ffmpeg/ffprobe binaries for the slice_01 pipeline.

Throwaway code for experiments/slice_01 -- see docs/SLICE-SPEC.md and
FINDINGS.md. Not imported by anything outside this experiment.

homebrew-core's `ffmpeg` formula ships without libass or freetype -- no
`ass`/`subtitles`/`drawtext` filters at all. The full-featured build is
`ffmpeg-full` from the homebrew-ffmpeg/ffmpeg tap, which has libass, but
it's keg-only (not linked onto PATH), so plain `ffmpeg` in a subprocess
call silently resolves to the wrong binary. There is also a conda ffmpeg
at ~/miniconda3/bin/ffmpeg -- a third candidate a bare "ffmpeg" string
could resolve to depending on shell state. None of shots.py, compose.py,
or run.py may invoke "ffmpeg"/"ffprobe" as a bare string; every subprocess
call goes through FFMPEG_BIN/FFPROBE_BIN below.

Defaults point at ffmpeg-full's keg-only path. Override with the
FFMPEG_BIN / FFPROBE_BIN environment variables if that path ever changes.
"""

import os
import subprocess

FFMPEG_BIN = os.environ.get("FFMPEG_BIN", "/opt/homebrew/opt/ffmpeg-full/bin/ffmpeg")
FFPROBE_BIN = os.environ.get("FFPROBE_BIN", "/opt/homebrew/opt/ffmpeg-full/bin/ffprobe")


def resolve_and_log() -> bool:
    """Print the resolved binary, its version, and ass-filter availability.
    Call once at pipeline start so binary substitution is never silent.
    Returns whether the `ass` filter is present (i.e. whether burn-in can
    actually run)."""
    if not os.path.exists(FFMPEG_BIN):
        raise FileNotFoundError(
            f"FFMPEG_BIN={FFMPEG_BIN!r} does not exist. Set the FFMPEG_BIN "
            "env var to point at a real ffmpeg binary."
        )

    version_result = subprocess.run(
        [FFMPEG_BIN, "-version"], capture_output=True, text=True, check=True
    )
    version_line = version_result.stdout.splitlines()[0] if version_result.stdout else "(unknown)"

    filters_result = subprocess.run(
        [FFMPEG_BIN, "-hide_banner", "-filters"], capture_output=True, text=True, check=True
    )
    has_ass = " ass " in filters_result.stdout

    print(f"ffmpeg binary : {FFMPEG_BIN}")
    print(f"ffprobe binary: {FFPROBE_BIN}")
    print(f"version       : {version_line}")
    print(f"ass filter    : {'present' if has_ass else 'ABSENT -- subtitle burn-in will be skipped'}")

    return has_ass


if __name__ == "__main__":
    resolve_and_log()
