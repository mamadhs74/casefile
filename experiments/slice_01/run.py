"""Stage 5: orchestrate and measure.

Throwaway code for experiments/slice_01 -- see docs/SLICE-SPEC.md and
FINDINGS.md. Not imported by anything, not meant to last.

Runs align -> shots -> compose in order and times each. narrate.py is not
re-run here: its Azure branch is a paid, rate-limited network call, and
re-hitting it on every timing run just to reproduce a number we already
have (1.51s synth_time, recorded in FINDINGS.md from the actual narrate.py
run) buys nothing. That figure is carried into the table as a labeled
constant instead of a live measurement.

Peak memory: resource.getrusage() on macOS reports ru_maxrss in *bytes*,
not kilobytes like Linux -- worth getting this unit conversion right, since
getting it wrong doesn't error, it just quietly reports 1024x the truth.
"""

import resource
import time
from pathlib import Path

import align
import compose
import shots

ROOT = Path(__file__).parent
OUTPUT_DIR = ROOT / "output"
TIMINGS_PATH = OUTPUT_DIR / "timings.txt"

# From FINDINGS.md's recorded narrate.py run (en-US-AriaNeural, swedencentral) --
# not re-measured here, see module docstring.
NARRATE_AZURE_SYNTH_SECONDS = 1.51


def format_table(rows: list[tuple[str, float]], total_output_seconds: float) -> str:
    total_seconds = sum(seconds for _, seconds in rows)
    output_minutes = total_output_seconds / 60

    lines = [f"{'stage':<24}{'seconds':>10}{'per output minute':>20}"]
    for name, seconds in rows:
        per_minute = seconds / output_minutes if output_minutes else 0.0
        lines.append(f"{name:<24}{seconds:>10.1f}{per_minute:>20.1f}")
    lines.append("-" * 54)
    total_per_minute = total_seconds / output_minutes if output_minutes else 0.0
    lines.append(f"{'total':<24}{total_seconds:>10.1f}{total_per_minute:>20.1f}")

    extrapolated_minutes = total_per_minute * 20 / 60
    lines.append("")
    lines.append(f"extrapolated to a 20-minute episode: {extrapolated_minutes:.1f} minutes")
    return "\n".join(lines)


def peak_memory_report() -> str:
    self_bytes = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    children_bytes = resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss
    return (
        f"peak memory -- this process (PIL decode/prep): {self_bytes / 1e6:.0f} MB, "
        f"child processes (ffmpeg/whisper): {children_bytes / 1e6:.0f} MB"
    )


def main() -> None:
    OUTPUT_DIR.mkdir(exist_ok=True)
    rows: list[tuple[str, float]] = [("narrate (azure, recorded)", NARRATE_AZURE_SYNTH_SECONDS)]

    print("=== stage: align ===")
    start = time.perf_counter()
    align.main()
    rows.append(("align", time.perf_counter() - start))

    print("\n=== stage: shots ===")
    start = time.perf_counter()
    shot_timings = shots.run()
    shots_wall = time.perf_counter() - start
    for st in shot_timings:
        rows.append((f"shots:prep shot{st.index}", st.prep_seconds))
        rows.append((f"shots:encode shot{st.index}", st.encode_seconds))
    print(f"(shots stage wall time: {shots_wall:.1f}s)")

    print("\n=== stage: compose ===")
    start = time.perf_counter()
    compose_result = compose.run()
    rows.append(("compose:concat", compose_result["concat"]))
    mux_label = "compose:burn+mux" if compose_result["burned"] else "compose:mux (no burn)"
    rows.append((mux_label, compose_result["mux"]))
    compose_wall = time.perf_counter() - start
    print(f"(compose stage wall time: {compose_wall:.1f}s)")

    total_output_seconds = shots.narration_duration()
    table = format_table(rows, total_output_seconds)
    memory_line = peak_memory_report()

    print("\n" + table)
    print(memory_line)

    TIMINGS_PATH.write_text(table + "\n\n" + memory_line + "\n")
    print(f"\n-> {TIMINGS_PATH.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
