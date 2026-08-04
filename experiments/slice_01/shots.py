"""Stage 3: images -> per-shot clips.

Throwaway code for experiments/slice_01 -- see docs/SLICE-SPEC.md and
FINDINGS.md. Not imported by anything, not meant to last.

The three source images for this run are a deliberate stress test, not
picked for documentary content: full-res phone/camera shots (up to ~30MB,
~36MP) chosen specifically because the *real* Hinterkaifeck archival photos
are ~1000px and can't support a zoom push at all -- see FINDINGS.md. That's
a fact about a hundred-year-old negative, not something this test can fix,
so it can't be used to measure zoom/encode cost. These oversized images can.

Two costs are measured separately per shot, because they come from
different places and don't scale the same way against a real 20-minute
episode:
  - prep: PIL decode + EXIF-orientation fix + downscale to ~2x the output
    frame height. Feeding a 30MB source straight into ffmpeg's zoompan
    (which upscales 4x internally to avoid integer-rounding stepping on
    slow zooms) would multiply that cost by 16x for no visual benefit --
    see docs/SLICE-SPEC.md's zoompan note.
  - encode: ffmpeg zoompan + h264_videotoolbox, on the already-downscaled
    source.
"""

import re
import resource
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageOps

from ffmpeg_config import FFMPEG_BIN, resolve_and_log

ROOT = Path(__file__).parent
PROJECT_ROOT = ROOT.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from packages.archive.fitness import FitnessReport, assess_fitness  # noqa: E402

INPUT_DIR = ROOT / "input"
WORK_DIR = ROOT / "work"
NARRATION_PATH = WORK_DIR / "narration_azure_en-US-AriaNeural.wav"

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".tiff", ".bmp", ".gif", ".heic"}

OUTPUT_WIDTH = 1920
OUTPUT_HEIGHT = 1080
FPS = 30
PREP_HEIGHT = OUTPUT_HEIGHT * 2  # "~2x the output frame height" per instructions
ZOOMPAN_UPSCALE = 4  # scale=iw*4:ih*4 before zoompan -- see SLICE-SPEC's stepping note
ZOOM_END = 1.3

# High-bitrate intermediate: concat later uses -c copy, so whatever quality
# this encode bakes in is what the delivery encode has to work with. Pinned
# explicitly rather than left to h264_videotoolbox's default so it isn't
# quietly dependent on ffmpeg-version heuristics.
INTERMEDIATE_BITRATE = "20M"


@dataclass
class ShotTiming:
    index: int
    source: Path
    prepped: Path
    clip: Path
    duration: float
    prep_seconds: float
    prep_peak_rss: int  # bytes, cumulative process high-water mark (see run_timed note)
    encode_seconds: float
    encode_fps: float
    encode_peak_rss: int  # bytes, this ffmpeg call only


def run_timed(cmd: list[str]) -> tuple[subprocess.CompletedProcess, int]:
    """Run cmd, capturing its exact peak RSS in bytes via `/usr/bin/time -l`
    (macOS reports bytes here, not the KB that Linux's `time -v` would)."""
    result = subprocess.run(["/usr/bin/time", "-l", *cmd], capture_output=True, text=True)
    match = re.search(r"^\s*(\d+)\s+maximum resident set size", result.stderr, re.MULTILINE)
    peak_rss = int(match.group(1)) if match else 0
    return result, peak_rss


def find_images() -> list[Path]:
    return sorted(
        p for p in INPUT_DIR.iterdir() if p.suffix.lower() in IMAGE_EXTENSIONS
    )


def ensure_decodable(path: Path) -> tuple[Path, str]:
    """Convert HEIC up front rather than skip it -- pillow-heif isn't part of
    this venv's dependency set, and `sips` is already on every Mac."""
    if path.suffix.lower() != ".heic":
        return path, "native"

    converted = WORK_DIR / (path.stem + "_from_heic.jpg")
    subprocess.run(
        ["sips", "-s", "format", "jpeg", str(path), "--out", str(converted)],
        check=True,
        capture_output=True,
    )
    return converted, "sips-converted"


def assess_image(path: Path, width: int, height: int) -> FitnessReport:
    import mimetypes

    mime_type = mimetypes.guess_type(path.name)[0] or "image/jpeg"
    return assess_fitness(width, height, mime_type)


def print_fitness_report(shot_number: int, path: Path, report: FitnessReport) -> None:
    orientation = "portrait" if report.aspect_ratio < 1.0 else "landscape"
    motion = (
        ", ".join(sorted(m.value for m in report.allowed_motion_types))
        if report.allowed_motion_types
        else "NONE -- no motion type is safe without upscaling"
    )
    print(f"shot{shot_number}: {path.name}")
    print(
        f"  long edge:          {report.long_edge_px}px "
        f"({orientation}, aspect {report.aspect_ratio:.3f})"
    )
    print(f"  meets minimum res:  {report.meets_minimum_resolution}")
    print(f"  allowed motion:     {motion}")
    print(f"  requires letterbox: {report.requires_letterbox}")
    for note in report.notes:
        print(f"  note: {note}")


def prep_image(index: int, path: Path) -> tuple[Path, float, int, tuple[int, int]]:
    """Decode, fix EXIF orientation, downscale.

    Returns (prepped_path, elapsed, peak_rss, original_size). peak_rss is
    RUSAGE_SELF.ru_maxrss sampled right after this call -- a cumulative
    high-water mark for the whole process (whisper's model from stage 2
    included, if this is running inside run.py), not an isolated
    per-call figure. It still answers the question that matters here: how
    close is this process to the 8GB ceiling at this point in the run.
    """
    start = time.perf_counter()

    decodable_path, decode_path_kind = ensure_decodable(path)

    with Image.open(decodable_path) as im:
        im = ImageOps.exif_transpose(im)
        original_size = im.size

        if im.height > PREP_HEIGHT:
            scale = PREP_HEIGHT / im.height
            new_size = (round(im.width * scale), PREP_HEIGHT)
            im = im.resize(new_size, Image.LANCZOS)

        if im.mode != "RGB":
            im = im.convert("RGB")

        out_path = WORK_DIR / f"shot{index}_prepped.jpg"
        im.save(out_path, quality=92)

    elapsed = time.perf_counter() - start
    peak_rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    if decode_path_kind == "sips-converted":
        print(f"  ({path.name}: converted from HEIC via sips before PIL could open it)")
    return out_path, elapsed, peak_rss, original_size


def encode_shot(index: int, prepped: Path, duration: float) -> tuple[Path, float, float, int]:
    """zoompan Ken Burns push-in + h264_videotoolbox at a pinned high-bitrate
    intermediate quality. Returns (clip_path, elapsed, encode_fps, peak_rss)."""
    frames = max(round(duration * FPS), 1)
    zoom_increment = (ZOOM_END - 1.0) / frames
    out_path = WORK_DIR / f"shot{index}.mp4"

    vf = (
        f"scale=iw*{ZOOMPAN_UPSCALE}:ih*{ZOOMPAN_UPSCALE},"
        f"zoompan=z='min(zoom+{zoom_increment:.8f},{ZOOM_END})':"
        f"d={frames}:s={OUTPUT_WIDTH}x{OUTPUT_HEIGHT}:fps={FPS}"
    )

    cmd = [
        FFMPEG_BIN, "-y", "-hide_banner", "-v", "warning",
        "-loop", "1", "-i", str(prepped),
        "-vf", vf,
        "-frames:v", str(frames),
        "-c:v", "h264_videotoolbox",
        "-b:v", INTERMEDIATE_BITRATE,
        "-pix_fmt", "yuv420p",
        str(out_path),
    ]

    start = time.perf_counter()
    result, peak_rss = run_timed(cmd)
    elapsed = time.perf_counter() - start

    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg failed on shot{index}:\n{result.stderr}")

    for line in result.stderr.splitlines():
        lowered = line.lower()
        if "fallback" in lowered or "not support" in lowered or "error" in lowered:
            print(f"  ffmpeg warning on shot{index}: {line}")

    encode_fps = frames / elapsed if elapsed > 0 else 0.0
    return out_path, elapsed, encode_fps, peak_rss


def narration_duration() -> float:
    import soundfile as sf

    if not NARRATION_PATH.exists():
        raise FileNotFoundError(f"{NARRATION_PATH} not found -- run narrate.py first.")
    return sf.info(str(NARRATION_PATH)).duration


def run() -> list[ShotTiming]:
    resolve_and_log()
    WORK_DIR.mkdir(exist_ok=True)
    images = find_images()
    if not images:
        raise FileNotFoundError(f"no images found in {INPUT_DIR}")

    print(f"found {len(images)} image(s) in {INPUT_DIR.relative_to(ROOT)}")
    total_duration = narration_duration()
    per_shot_duration = total_duration / len(images)
    print(
        f"narration duration: {total_duration:.2f}s / {len(images)} shots "
        f"= {per_shot_duration:.2f}s per shot\n"
    )

    timings: list[ShotTiming] = []
    for i, path in enumerate(images, start=1):
        prepped, prep_seconds, prep_peak_rss, original_size = prep_image(i, path)
        report = assess_image(path, *original_size)
        print_fitness_report(i, path, report)
        print(
            f"  prepped: {original_size[0]}x{original_size[1]} -> "
            f"{Image.open(prepped).size} in {prep_seconds:.2f}s "
            f"(process RSS so far: {prep_peak_rss / 1e6:.0f}MB)"
        )

        clip, encode_seconds, encode_fps, encode_peak_rss = encode_shot(
            i, prepped, per_shot_duration
        )
        print(
            f"  encoded: {clip.relative_to(ROOT)} in {encode_seconds:.2f}s "
            f"({encode_fps:.0f} fps, h264_videotoolbox, peak RSS {encode_peak_rss / 1e6:.0f}MB)\n"
        )

        timings.append(
            ShotTiming(
                index=i,
                source=path,
                prepped=prepped,
                clip=clip,
                duration=per_shot_duration,
                prep_seconds=prep_seconds,
                prep_peak_rss=prep_peak_rss,
                encode_seconds=encode_seconds,
                encode_fps=encode_fps,
                encode_peak_rss=encode_peak_rss,
            )
        )

    return timings


def main() -> None:
    run()


if __name__ == "__main__":
    main()
