"""Stage 4: clips + audio + subtitles -> final.

Throwaway code for experiments/slice_01 -- see docs/SLICE-SPEC.md and
FINDINGS.md. Not imported by anything, not meant to last.

Two ffmpeg passes, not one, because they have different re-encode costs:
1. Concat the shot clips with the concat demuxer and `-c copy` -- no
   re-encoding, just container-level stitching, so this is nearly free.
2. Attach the narration and burn in subtitles with the `ass` filter. Burning
   subtitles means decoding and re-encoding the video no matter what, so
   this pass is where the real cost is, not the concat.

Subtitles are burned in, not muxed as a soft track -- platforms handle soft
subs inconsistently and we want to see exactly what the viewer sees.

NOT DONE THIS RUN: the installed ffmpeg (homebrew-core's regular `ffmpeg`
formula) has neither the `ass` filter (needs libass) nor `drawtext` (needs
freetype) -- it's a stripped-down build. The full-featured build lives in
the `homebrew-ffmpeg/ffmpeg` tap, but its bottle isn't available for this
OS version, so installing it means compiling from source, which this
machine's Xcode Command Line Tools are too outdated to do -- that needs an
App Store update, not something to do as a side effect of a render-timing
test. See FINDINGS.md. work/subs.ass is still the valid stage-2 artifact;
this stage just doesn't burn it in yet.
"""

import subprocess
import time
from pathlib import Path

ROOT = Path(__file__).parent
WORK_DIR = ROOT / "work"
OUTPUT_DIR = ROOT / "output"
NARRATION_PATH = WORK_DIR / "narration_azure_en-US-AriaNeural.wav"
SUBS_PATH = WORK_DIR / "subs.ass"
CONCAT_LIST_PATH = WORK_DIR / "concat_list.txt"
CONCAT_PATH = WORK_DIR / "concat.mp4"
FINAL_PATH = OUTPUT_DIR / "slice.mp4"


def find_shot_clips() -> list[Path]:
    clips = sorted(
        WORK_DIR.glob("shot*.mp4"),
        key=lambda p: int("".join(c for c in p.stem if c.isdigit())),
    )
    if not clips:
        raise FileNotFoundError(f"no shot*.mp4 clips in {WORK_DIR} -- run shots.py first.")
    return clips


def concat_clips(clips: list[Path]) -> float:
    CONCAT_LIST_PATH.write_text("".join(f"file '{p.resolve()}'\n" for p in clips))

    cmd = [
        "ffmpeg", "-y", "-hide_banner", "-v", "warning",
        "-f", "concat", "-safe", "0", "-i", str(CONCAT_LIST_PATH),
        "-c", "copy",
        str(CONCAT_PATH),
    ]
    start = time.perf_counter()
    result = subprocess.run(cmd, capture_output=True, text=True)
    elapsed = time.perf_counter() - start

    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg concat failed:\n{result.stderr}")
    return elapsed


def mux(burn_subs: bool) -> tuple[float, bool]:
    """Attach narration audio. Burns subtitles via the `ass` filter if it's
    available in this ffmpeg build; otherwise falls back to a plain stream
    copy and reports that subtitles were not burned in -- see module
    docstring."""
    if not NARRATION_PATH.exists():
        raise FileNotFoundError(f"{NARRATION_PATH} not found -- run narrate.py first.")
    if not SUBS_PATH.exists():
        raise FileNotFoundError(f"{SUBS_PATH} not found -- run align.py first.")

    OUTPUT_DIR.mkdir(exist_ok=True)

    if burn_subs:
        ass_path = str(SUBS_PATH.resolve()).replace("\\", "/").replace(":", "\\:")
        video_args = ["-vf", f"ass={ass_path}", "-c:v", "h264_videotoolbox", "-pix_fmt", "yuv420p"]
    else:
        video_args = ["-c:v", "copy"]

    cmd = [
        "ffmpeg", "-y", "-hide_banner", "-v", "warning",
        "-i", str(CONCAT_PATH),
        "-i", str(NARRATION_PATH),
        *video_args,
        "-map", "0:v:0", "-map", "1:a:0",
        "-c:a", "aac",
        "-shortest",
        str(FINAL_PATH),
    ]
    start = time.perf_counter()
    result = subprocess.run(cmd, capture_output=True, text=True)
    elapsed = time.perf_counter() - start

    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg mux failed:\n{result.stderr}")

    for line in result.stderr.splitlines():
        lowered = line.lower()
        if "fallback" in lowered or "not support" in lowered or "error" in lowered:
            print(f"  ffmpeg warning: {line}")

    return elapsed, burn_subs


def ass_filter_available() -> bool:
    result = subprocess.run(
        ["ffmpeg", "-hide_banner", "-filters"], capture_output=True, text=True
    )
    return " ass " in result.stdout


def run() -> dict[str, float | bool]:
    clips = find_shot_clips()
    concat_seconds = concat_clips(clips)
    print(f"concat ({len(clips)} clips, -c copy): {concat_seconds:.2f}s -> {CONCAT_PATH.relative_to(ROOT)}")

    can_burn = ass_filter_available()
    if not can_burn:
        print(
            "  this ffmpeg build has no `ass` filter (no libass) and no `drawtext` "
            "(no freetype) -- muxing audio without burning subtitles. See FINDINGS.md."
        )
    mux_seconds, burned = mux(burn_subs=can_burn)
    label = "mux + subtitle burn-in" if burned else "mux (subtitles NOT burned -- see above)"
    print(f"{label}: {mux_seconds:.2f}s -> {FINAL_PATH.relative_to(ROOT)}")

    return {"concat": concat_seconds, "mux": mux_seconds, "burned": burned}


def main() -> None:
    run()


if __name__ == "__main__":
    main()
