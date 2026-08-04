"""Stage 5: orchestrate and measure.

Throwaway code for experiments/slice_01 -- see docs/SLICE-SPEC.md and
FINDINGS.md. Not imported by anything, not meant to last.

Runs align -> shots -> compose in order and times each. narrate.py is not
re-run here: its Azure branch is a paid, rate-limited network call, and
re-hitting it on every timing run just to reproduce a number we already
have (1.51s synth_time, recorded in FINDINGS.md from the actual narrate.py
run) buys nothing. That figure is carried into the table as a labeled
constant instead of a live measurement.

Peak memory is reported per row, not just once at the end, because a
number near the 8GB ceiling at any single step invalidates that step's
timing (thrashing, not real work). Two different measurements feed it:
  - ffmpeg subprocess steps (shots:encode, compose:concat, compose:deliver)
    get an exact peak RSS for that one process, from `/usr/bin/time -l`
    (see shots.py / compose.py).
  - in-process steps (align, shots:prep) get
    resource.getrusage(RUSAGE_SELF).ru_maxrss, which on macOS is bytes (not
    the KB Linux's `time -v` would give) and is a *cumulative* high-water
    mark for the whole process, not an isolated per-step figure -- it only
    ever goes up. Labeled as such in the table rather than passed off as
    something it isn't.

Shot 1's encode time is split out from shots 2..N's steady-state average
for the 20-minute extrapolation: shot 1 pays ffmpeg's filter-graph init and
a cold page cache that later shots don't, so folding it into a flat
per-shot average and multiplying by an extrapolated shot count overstates
the real cost.
"""

import resource
import time
from dataclasses import dataclass
from pathlib import Path
from statistics import mean

import align
import compose
import shots

ROOT = Path(__file__).parent
OUTPUT_DIR = ROOT / "output"
TIMINGS_PATH = OUTPUT_DIR / "timings.txt"

# From FINDINGS.md's recorded narrate.py run (en-US-AriaNeural, swedencentral) --
# not re-measured here, see module docstring.
NARRATE_AZURE_SYNTH_SECONDS = 1.51


@dataclass
class Row:
    name: str
    seconds: float
    peak_rss: int | None  # bytes; None = not measured (e.g. the recorded narrate constant)
    counts_toward_total: bool = True


def rss_mb(row: Row) -> str:
    return f"{row.peak_rss / 1e6:.0f}" if row.peak_rss is not None else "n/a"


NAME_WIDTH = 38


def format_table(rows: list[Row], total_output_seconds: float, extrapolated_minutes: float) -> str:
    output_minutes = total_output_seconds / 60
    summed_rows = [r for r in rows if r.counts_toward_total]
    total_seconds = sum(r.seconds for r in summed_rows)

    lines = [
        "(peak RSS: align/shots:prep = cumulative process high-water mark; "
        "shots:encode/compose = exact per-call, via /usr/bin/time -l)",
        f"{'stage':<{NAME_WIDTH}}{'seconds':>9}{'per out. min':>14}{'peak RSS MB':>13}",
    ]
    for row in rows:
        per_minute = row.seconds / output_minutes if output_minutes else 0.0
        marker = "" if row.counts_toward_total else "  (info only)"
        lines.append(
            f"{row.name:<{NAME_WIDTH}}{row.seconds:>9.1f}{per_minute:>14.1f}{rss_mb(row):>13}{marker}"
        )
    lines.append("-" * (NAME_WIDTH + 36))
    total_per_minute = total_seconds / output_minutes if output_minutes else 0.0
    lines.append(f"{'total':<{NAME_WIDTH}}{total_seconds:>9.1f}{total_per_minute:>14.1f}")

    lines.append("")
    lines.append(
        f"extrapolated to a 20-minute episode: {extrapolated_minutes:.1f} minutes "
        "(uses shots 2..N steady-state rate, not shot 1's cold-start cost -- see below)"
    )
    return "\n".join(lines)


def extrapolate_minutes(
    fixed_rows_seconds: float,
    shot_timings: list[shots.ShotTiming],
    per_shot_duration: float,
    total_output_seconds: float,
) -> float:
    """20-minute estimate. Everything except shots:encode scales linearly
    with output duration, same as before. shots:encode gets a cold-start +
    steady-state-rate model instead of a flat per-shot average, since shot
    1 alone isn't representative -- see module docstring."""
    episode_seconds = 20 * 60
    scale = episode_seconds / total_output_seconds

    encode_times = [st.encode_seconds for st in shot_timings]
    cold_start = encode_times[0]
    steady_times = encode_times[1:] if len(encode_times) > 1 else encode_times
    steady_avg = mean(steady_times)
    steady_rate_per_output_second = steady_avg / per_shot_duration

    remaining_seconds = max(episode_seconds - per_shot_duration, 0.0)
    extrapolated_encode_total = cold_start + steady_rate_per_output_second * remaining_seconds

    extrapolated_fixed = fixed_rows_seconds * scale
    return (extrapolated_fixed + extrapolated_encode_total) / 60


def main() -> None:
    OUTPUT_DIR.mkdir(exist_ok=True)
    rows: list[Row] = [Row("narrate (azure, recorded)", NARRATE_AZURE_SYNTH_SECONDS, None)]
    fixed_rows_seconds = NARRATE_AZURE_SYNTH_SECONDS  # everything except shots:encode

    print("=== stage: align ===")
    start = time.perf_counter()
    align.main()
    align_seconds = time.perf_counter() - start
    align_peak_rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    rows.append(Row("align", align_seconds, align_peak_rss))
    fixed_rows_seconds += align_seconds

    print("\n=== stage: shots ===")
    start = time.perf_counter()
    shot_timings = shots.run()
    shots_wall = time.perf_counter() - start
    for st in shot_timings:
        rows.append(Row(f"shots:prep shot{st.index}", st.prep_seconds, st.prep_peak_rss))
        fixed_rows_seconds += st.prep_seconds
    for st in shot_timings:
        cold_marker = " (cold start)" if st.index == shot_timings[0].index else ""
        rows.append(Row(f"shots:encode shot{st.index}{cold_marker}", st.encode_seconds, st.encode_peak_rss))
    steady_avg_seconds = mean(st.encode_seconds for st in shot_timings[1:]) if len(shot_timings) > 1 else shot_timings[0].encode_seconds
    rows.append(
        Row(
            f"shots:encode steady-state avg (n={max(len(shot_timings) - 1, 1)})",
            steady_avg_seconds,
            None,
            counts_toward_total=False,
        )
    )
    print(f"(shots stage wall time: {shots_wall:.1f}s)")

    print("\n=== stage: compose ===")
    start = time.perf_counter()
    compose_result = compose.run()
    rows.append(Row("compose:concat", compose_result["concat_seconds"], compose_result["concat_peak_rss"]))
    fixed_rows_seconds += compose_result["concat_seconds"]
    deliver_label = "compose:deliver (burned)" if compose_result["burned"] else "compose:deliver (NOT burned)"
    rows.append(Row(deliver_label, compose_result["deliver_seconds"], compose_result["deliver_peak_rss"]))
    fixed_rows_seconds += compose_result["deliver_seconds"]
    compose_wall = time.perf_counter() - start
    print(f"(compose stage wall time: {compose_wall:.1f}s)")

    total_output_seconds = shots.narration_duration()
    per_shot_duration = total_output_seconds / len(shot_timings)
    extrapolated_minutes = extrapolate_minutes(
        fixed_rows_seconds, shot_timings, per_shot_duration, total_output_seconds
    )
    table = format_table(rows, total_output_seconds, extrapolated_minutes)

    children_bytes = resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss
    memory_line = (
        f"peak RSS across all child processes this run (cumulative high-water mark, "
        f"not per-step -- see per-row figures above for that): {children_bytes / 1e6:.0f} MB"
    )
    if not compose_result["burned"]:
        gap_line = (
            "NOTE: libass unavailable in FFMPEG_BIN -- delivery encode ran without "
            "subtitle burn-in. Blocking stage-4 gap, see FINDINGS.md."
        )
    else:
        gap_line = "subtitles burned into the delivery encode via FFMPEG_BIN's ass filter."

    print("\n" + table)
    print(memory_line)
    if gap_line:
        print(gap_line)

    out_text = table + "\n\n" + memory_line + "\n"
    if gap_line:
        out_text += gap_line + "\n"
    TIMINGS_PATH.write_text(out_text)
    print(f"\n-> {TIMINGS_PATH.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
