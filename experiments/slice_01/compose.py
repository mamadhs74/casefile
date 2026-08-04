"""Stage 4: clips + audio + subtitles -> final.

Throwaway code for experiments/slice_01 -- see docs/SLICE-SPEC.md and
FINDINGS.md. Not imported by anything, not meant to last.

Two-tier design:
1. Concat the shot clips with the concat demuxer and `-c copy` -- no
   re-encoding, just container-level stitching. Each shot clip is already a
   pinned high-bitrate intermediate (see shots.py), so this step doesn't
   soften anything; it's nearly free either way.
2. Exactly one delivery encode: mux the narration audio in, burn subtitles
   in if the `ass` filter is available, convert to limited-range yuv420p
   (JPEG-sourced frames decode full-range, which shifts levels on upload if
   it isn't corrected), and encode once at delivery bitrate with
   h264_videotoolbox.

Subtitle burn-in is a detected capability (`ffmpeg_config.resolve_and_log()`
checks for the `ass` filter fresh every run), not a hardcoded decision --
the moment libass is present in FFMPEG_BIN, this same code path burns
subs.ass with no changes needed. See FINDINGS.md: plain
"ffmpeg" resolves to homebrew-core's build (no libass); ffmpeg-full has it
but is keg-only, so FFMPEG_BIN/FFPROBE_BIN in ffmpeg_config.py pin the
explicit path rather than trusting PATH -- there's also a conda ffmpeg on
this machine, so silent binary substitution is a real risk, not a
hypothetical one.

Subtitles are burned in, not muxed as a soft track -- platforms handle soft
subs inconsistently and we want to see exactly what the viewer sees.
"""

import re
import subprocess
import time
from pathlib import Path

from ffmpeg_config import FFMPEG_BIN, FFPROBE_BIN, resolve_and_log

ROOT = Path(__file__).parent
WORK_DIR = ROOT / "work"
OUTPUT_DIR = ROOT / "output"
NARRATION_PATH = WORK_DIR / "narration_azure_en-US-AriaNeural.wav"
SUBS_PATH = WORK_DIR / "subs.ass"
CONCAT_LIST_PATH = WORK_DIR / "concat_list.txt"
CONCAT_PATH = WORK_DIR / "concat.mp4"

# Deliberately not output/slice.mp4 -- this is the new two-tier delivery
# path and the old name shouldn't be silently overwritten mid-comparison.
# Should collapse to one canonical output name before this leaves the
# experiment stage -- see FINDINGS.md.
DELIVERY_PATH = OUTPUT_DIR / "slice_delivery.mp4"

DELIVERY_BITRATE = "10M"
DURATION_DRIFT_TOLERANCE = 0.2  # seconds -- -shortest silently truncates past this


def run_timed(cmd: list[str]) -> tuple[subprocess.CompletedProcess, int]:
    """Run cmd, capturing its exact peak RSS in bytes via `/usr/bin/time -l`
    (macOS reports bytes here, not the KB that Linux's `time -v` would)."""
    result = subprocess.run(["/usr/bin/time", "-l", *cmd], capture_output=True, text=True)
    match = re.search(r"^\s*(\d+)\s+maximum resident set size", result.stderr, re.MULTILINE)
    peak_rss = int(match.group(1)) if match else 0
    return result, peak_rss


def find_shot_clips() -> list[Path]:
    clips = sorted(
        WORK_DIR.glob("shot*.mp4"),
        key=lambda p: int("".join(c for c in p.stem if c.isdigit())),
    )
    if not clips:
        raise FileNotFoundError(f"no shot*.mp4 clips in {WORK_DIR} -- run shots.py first.")
    return clips


def concat_clips(clips: list[Path]) -> tuple[float, int]:
    CONCAT_LIST_PATH.write_text("".join(f"file '{p.resolve()}'\n" for p in clips))

    cmd = [
        FFMPEG_BIN, "-y", "-hide_banner", "-v", "warning",
        "-f", "concat", "-safe", "0", "-i", str(CONCAT_LIST_PATH),
        "-c", "copy",
        str(CONCAT_PATH),
    ]
    start = time.perf_counter()
    result, peak_rss = run_timed(cmd)
    elapsed = time.perf_counter() - start

    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg concat failed:\n{result.stderr}")
    return elapsed, peak_rss


def probe_duration(path: Path) -> float:
    result = subprocess.run(
        [
            FFPROBE_BIN, "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            str(path),
        ],
        capture_output=True, text=True, check=True,
    )
    return float(result.stdout.strip())


def deliver(burn_subs: bool) -> dict:
    if not NARRATION_PATH.exists():
        raise FileNotFoundError(f"{NARRATION_PATH} not found -- run narrate.py first.")
    if not SUBS_PATH.exists():
        raise FileNotFoundError(f"{SUBS_PATH} not found -- run align.py first.")

    OUTPUT_DIR.mkdir(exist_ok=True)

    video_duration = probe_duration(CONCAT_PATH)
    audio_duration = probe_duration(NARRATION_PATH)
    drift = abs(video_duration - audio_duration)
    print(f"  video duration {video_duration:.2f}s, audio duration {audio_duration:.2f}s (drift {drift:.2f}s)")
    if drift > DURATION_DRIFT_TOLERANCE:
        print(
            f"  WARNING: video/audio duration differ by {drift:.2f}s, over the "
            f"{DURATION_DRIFT_TOLERANCE}s tolerance -- -shortest will silently "
            "truncate whichever is longer."
        )

    # JPEG-sourced frames decode as full-range; without an explicit
    # conversion ffmpeg tags the output yuvj420p (full range), which shifts
    # levels on platforms that assume standard limited-range yuv420p.
    range_fix = "scale=in_range=full:out_range=tv,format=yuv420p"
    if burn_subs:
        ass_path = str(SUBS_PATH.resolve()).replace("\\", "/").replace(":", "\\:")
        vf = f"ass={ass_path},{range_fix}"
    else:
        vf = range_fix

    cmd = [
        FFMPEG_BIN, "-y", "-hide_banner", "-v", "warning",
        "-i", str(CONCAT_PATH),
        "-i", str(NARRATION_PATH),
        "-vf", vf,
        "-map", "0:v:0", "-map", "1:a:0",
        "-c:v", "h264_videotoolbox", "-b:v", DELIVERY_BITRATE,
        "-pix_fmt", "yuv420p", "-color_range", "tv",
        "-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709",
        "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
        "-movflags", "+faststart",
        "-shortest",
        str(DELIVERY_PATH),
    ]
    start = time.perf_counter()
    result, peak_rss = run_timed(cmd)
    elapsed = time.perf_counter() - start

    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg delivery encode failed:\n{result.stderr}")

    for line in result.stderr.splitlines():
        lowered = line.lower()
        if "fallback" in lowered or "not support" in lowered:
            print(f"  ffmpeg warning: {line}")

    return {
        "seconds": elapsed,
        "peak_rss": peak_rss,
        "burned": burn_subs,
        "video_duration": video_duration,
        "audio_duration": audio_duration,
        "duration_drift": drift,
    }


def run() -> dict:
    can_burn = resolve_and_log()
    clips = find_shot_clips()
    concat_seconds, concat_peak_rss = concat_clips(clips)
    print(
        f"concat ({len(clips)} clips, -c copy): {concat_seconds:.2f}s, "
        f"peak RSS {concat_peak_rss / 1e6:.0f}MB -> {CONCAT_PATH.relative_to(ROOT)}"
    )

    if can_burn:
        print("  ass filter available -- burning subs.ass into the delivery encode.")
    else:
        print(
            "  ass filter unavailable in FFMPEG_BIN -- delivery encode proceeds "
            "without subtitle burn-in. This is a blocking stage-4 gap, not a design "
            "choice -- see FINDINGS.md."
        )

    delivery = deliver(burn_subs=can_burn)
    label = "deliver (burned)" if delivery["burned"] else "deliver (NOT burned -- libass unavailable)"
    print(
        f"{label}: {delivery['seconds']:.2f}s, peak RSS {delivery['peak_rss'] / 1e6:.0f}MB "
        f"-> {DELIVERY_PATH.relative_to(ROOT)}"
    )

    return {
        "concat_seconds": concat_seconds,
        "concat_peak_rss": concat_peak_rss,
        "deliver_seconds": delivery["seconds"],
        "deliver_peak_rss": delivery["peak_rss"],
        "burned": delivery["burned"],
    }


def main() -> None:
    run()


if __name__ == "__main__":
    main()
