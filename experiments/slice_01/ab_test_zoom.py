"""A/B test: prep-scale factor and zoompan-vs-crop+scale, for FINDINGS.md.

Throwaway, ad hoc -- NOT part of the pipeline, NOT imported by shots.py.
shots.py's defaults (2x output height prep scale, zoompan) are unchanged by
this script; it only measures and reports. See the encode/decode-cost
observation in FINDINGS.md that motivated it: shots:encode ran at ~1.26x
realtime while compose:deliver (same encoder, same resolution, same
machine) ran at ~6.2x realtime. The 5x gap is almost certainly zoompan's
own `scale=iw*4:ih*4` upscale of the *entire* frame every output frame,
regardless of how far into the zoom it is -- fixed cost, paid 30 times a
second, that has nothing to do with h264_videotoolbox.

Two variables tested against the current production zoompan pipeline:
1. Prep scale factor: 2.0x output height (current default, 2160p), 1.4x
   (1512p), 1.2x (1296p). Lower prep resolution -> smaller frame for
   zoompan's 4x upscale to work on -> should cost less, at some point at
   the expense of visible softening on the tightest zoom.
2. Filter architecture: crop+scale with time-varying expressions instead
   of zoompan. Crops a shrinking window directly out of the (much larger)
   prepped frame -- no 4x upscale of the whole frame at all -- then scales
   just that window up to 1920x1080. If the zoompan slowness really is the
   full-frame upscale, this should be dramatically cheaper; the open
   question is whether skipping zoompan's approach re-introduces the
   integer-pixel-rounding stepping problem docs/SLICE-SPEC.md warned about.
"""

import re
import subprocess
import time
from pathlib import Path

from PIL import Image, ImageOps

from ffmpeg_config import FFMPEG_BIN, resolve_and_log

ROOT = Path(__file__).parent
INPUT_DIR = ROOT / "input"
WORK_DIR = ROOT / "work"
AB_DIR = WORK_DIR / "ab_test"

OUTPUT_WIDTH = 1920
OUTPUT_HEIGHT = 1080
FPS = 30
ZOOM_END = 1.3
ZOOMPAN_UPSCALE = 4
DURATION = 22.62  # matches the real per-shot duration (67.85s / 3 shots)
FRAMES = round(DURATION * FPS)

PREP_SCALE_FACTORS = [2.0, 1.4, 1.2]  # x output height (1080)


def run_timed(cmd: list[str]) -> tuple[subprocess.CompletedProcess, int]:
    result = subprocess.run(["/usr/bin/time", "-l", *cmd], capture_output=True, text=True)
    match = re.search(r"^\s*(\d+)\s+maximum resident set size", result.stderr, re.MULTILINE)
    return result, int(match.group(1)) if match else 0


def find_images() -> list[Path]:
    return sorted(p for p in INPUT_DIR.iterdir() if p.suffix.lower() == ".jpg")


def prep(path: Path, prep_height: int, tag: str) -> Path:
    with Image.open(path) as im:
        im = ImageOps.exif_transpose(im)
        if im.height > prep_height:
            scale = prep_height / im.height
            im = im.resize((round(im.width * scale), prep_height), Image.LANCZOS)
        if im.mode != "RGB":
            im = im.convert("RGB")
        out_path = AB_DIR / f"{path.stem}_{tag}.jpg"
        im.save(out_path, quality=92)
    return out_path


def encode_zoompan(prepped: Path, out_path: Path) -> tuple[float, int]:
    inc = (ZOOM_END - 1.0) / FRAMES
    vf = (
        f"scale=iw*{ZOOMPAN_UPSCALE}:ih*{ZOOMPAN_UPSCALE},"
        f"zoompan=z='min(zoom+{inc:.8f},{ZOOM_END})':"
        f"d={FRAMES}:s={OUTPUT_WIDTH}x{OUTPUT_HEIGHT}:fps={FPS}"
    )
    cmd = [
        FFMPEG_BIN, "-y", "-hide_banner", "-v", "warning",
        "-framerate", str(FPS), "-loop", "1", "-i", str(prepped),
        "-vf", vf, "-frames:v", str(FRAMES),
        "-c:v", "h264_videotoolbox", "-b:v", "20M", "-pix_fmt", "yuv420p",
        str(out_path),
    ]
    start = time.perf_counter()
    result, peak = run_timed(cmd)
    elapsed = time.perf_counter() - start
    if result.returncode != 0:
        raise RuntimeError(f"zoompan encode failed:\n{result.stderr}")
    return elapsed, peak


def encode_cropscale(prepped: Path, out_path: Path) -> tuple[float, int]:
    """Crop a shrinking window directly from the prepped frame (no 4x
    full-frame upscale), then scale just that window up to output size."""
    inc = (ZOOM_END - 1.0) / DURATION
    zoom_expr = f"min(1+{inc:.8f}*t,{ZOOM_END})"
    w_expr = f"iw/({zoom_expr})"
    h_expr = f"ih/({zoom_expr})"
    x_expr = f"(iw-({w_expr}))/2"
    y_expr = f"(ih-({h_expr}))/2"
    vf = (
        f"crop=w='{w_expr}':h='{h_expr}':x='{x_expr}':y='{y_expr}':exact=1,"
        f"scale={OUTPUT_WIDTH}:{OUTPUT_HEIGHT}"
    )
    cmd = [
        FFMPEG_BIN, "-y", "-hide_banner", "-v", "warning",
        "-framerate", str(FPS), "-loop", "1", "-i", str(prepped),
        "-vf", vf, "-frames:v", str(FRAMES),
        "-c:v", "h264_videotoolbox", "-b:v", "20M", "-pix_fmt", "yuv420p",
        str(out_path),
    ]
    start = time.perf_counter()
    result, peak = run_timed(cmd)
    elapsed = time.perf_counter() - start
    if result.returncode != 0:
        raise RuntimeError(f"crop+scale encode failed:\n{result.stderr}")
    return elapsed, peak


def extract_frame(clip: Path, timestamp: float, out_png: Path) -> None:
    cmd = [
        FFMPEG_BIN, "-y", "-hide_banner", "-v", "error",
        "-ss", str(timestamp), "-i", str(clip), "-frames:v", "1", str(out_png),
    ]
    subprocess.run(cmd, check=True)


def extract_burst(clip: Path, start_frame: int, count: int, out_dir: Path, tag: str) -> list[Path]:
    """Consecutive frames (not a time range) for a frame-to-frame smoothness check."""
    start_t = start_frame / FPS
    cmd = [
        FFMPEG_BIN, "-y", "-hide_banner", "-v", "error",
        "-ss", str(start_t), "-i", str(clip), "-frames:v", str(count),
        str(out_dir / f"{tag}_%03d.png"),
    ]
    subprocess.run(cmd, check=True)
    return sorted(out_dir.glob(f"{tag}_*.png"))


def mean_abs_diff(a: Path, b: Path) -> float:
    with Image.open(a) as im_a, Image.open(b) as im_b:
        ga = im_a.convert("L")
        gb = im_b.convert("L")
        pa = ga.tobytes()
        pb = gb.tobytes()
        return sum(abs(x - y) for x, y in zip(pa, pb)) / len(pa)


def main() -> None:
    resolve_and_log()
    AB_DIR.mkdir(exist_ok=True, parents=True)
    images = find_images()
    print(f"{len(images)} source images, {DURATION}s / {FRAMES} frames per test clip\n")

    print("=" * 70)
    print("PART 1: prep scale factor vs zoompan encode cost")
    print("=" * 70)
    results: dict[float, list[tuple[str, float, int]]] = {}
    for factor in PREP_SCALE_FACTORS:
        prep_height = round(OUTPUT_HEIGHT * factor)
        print(f"\n--- prep scale {factor}x (height={prep_height}px) ---")
        results[factor] = []
        for path in images:
            tag = f"scale{factor}"
            prepped = prep(path, prep_height, tag)
            out_clip = AB_DIR / f"{path.stem}_{tag}_zoompan.mp4"
            elapsed, peak = encode_zoompan(prepped, out_clip)
            print(
                f"  {path.stem[:40]:40s} prepped->{Image.open(prepped).size} "
                f"encode {elapsed:6.2f}s  peak RSS {peak / 1e6:5.0f}MB"
            )
            results[factor].append((path.stem, elapsed, peak))

    print("\nsummary (seconds per shot, realtime factor for a 22.62s clip):")
    for factor, rows in results.items():
        avg = sum(r[1] for r in rows) / len(rows)
        print(f"  scale {factor}x: avg {avg:6.2f}s  ({DURATION / avg:.2f}x realtime)")

    print("\n" + "=" * 70)
    print("PART 2: visual quality check at the tightest zoom (last frame)")
    print("=" * 70)
    biggest = max(images, key=lambda p: p.stat().st_size)
    print(f"using {biggest.name} (largest source, most detail to lose)\n")
    for factor in PREP_SCALE_FACTORS:
        clip = AB_DIR / f"{biggest.stem}_scale{factor}_zoompan.mp4"
        out_png = AB_DIR / f"tightest_zoom_scale{factor}.png"
        extract_frame(clip, DURATION - 0.1, out_png)
        print(f"  scale {factor}x -> {out_png.relative_to(ROOT)}")

    print("\n" + "=" * 70)
    print("PART 3: zoompan vs crop+scale (both at the 2.0x/2160p default prep)")
    print("=" * 70)
    cropscale_results = []
    for path in images:
        prepped = AB_DIR / f"{path.stem}_scale2.0.jpg"  # already prepped in part 1
        out_clip = AB_DIR / f"{path.stem}_cropscale.mp4"
        elapsed, peak = encode_cropscale(prepped, out_clip)
        print(
            f"  {path.stem[:40]:40s} encode {elapsed:6.2f}s  peak RSS {peak / 1e6:5.0f}MB"
        )
        cropscale_results.append((path.stem, elapsed, peak))

    zoompan_2x_avg = sum(r[1] for r in results[2.0]) / len(results[2.0])
    cropscale_avg = sum(r[1] for r in cropscale_results) / len(cropscale_results)
    print(f"\n  zoompan   @2.0x prep: avg {zoompan_2x_avg:6.2f}s ({DURATION / zoompan_2x_avg:.2f}x realtime)")
    print(f"  crop+scale @2.0x prep: avg {cropscale_avg:6.2f}s ({DURATION / cropscale_avg:.2f}x realtime)")
    print(f"  speedup: {zoompan_2x_avg / cropscale_avg:.2f}x")

    print("\nextracting tightest-zoom frame + a mid-clip smoothness burst for crop+scale...")
    cropscale_clip = AB_DIR / f"{biggest.stem}_cropscale.mp4"
    extract_frame(cropscale_clip, DURATION - 0.1, AB_DIR / "tightest_zoom_cropscale.png")

    burst_start_frame = FRAMES // 2
    zoompan_clip = AB_DIR / f"{biggest.stem}_scale2.0_zoompan.mp4"
    zoompan_burst = extract_burst(zoompan_clip, burst_start_frame, 6, AB_DIR, "burst_zoompan")
    cropscale_burst = extract_burst(cropscale_clip, burst_start_frame, 6, AB_DIR, "burst_cropscale")

    print("\nframe-to-frame mean abs pixel diff, mid-clip 6-frame burst (higher variance = more uneven/jerky):")
    for label, burst in [("zoompan", zoompan_burst), ("crop+scale", cropscale_burst)]:
        diffs = [mean_abs_diff(burst[i], burst[i + 1]) for i in range(len(burst) - 1)]
        mean_diff = sum(diffs) / len(diffs)
        variance = sum((d - mean_diff) ** 2 for d in diffs) / len(diffs)
        print(f"  {label:12s} diffs={['%.3f' % d for d in diffs]}  mean={mean_diff:.3f}  variance={variance:.4f}")


if __name__ == "__main__":
    main()
