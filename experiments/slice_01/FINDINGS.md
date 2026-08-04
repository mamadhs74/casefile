# Findings — slice_01

Updated as each stage runs. Render time and memory are not in here yet —
only stage 1 (narration) has actually run.

## Voice synthesis: Kokoro (kokoro-onnx)

### What was tried

Synthesized the same ~170-word narration script through three Kokoro
voices: `af_heart` (American, female), `am_michael` (American, male), and
`bm_george` (British, male) — picked to cover accent and gender in one pass
rather than three near-identical samples. All three ran cleanly: 24kHz
mono, 62–68s of audio, synthesized in 14–16s each (roughly 4x real-time on
CPU, which is a good sign for the render-time question once we get there).

### Why it failed

All three sound flat and monotone in the same way — tolerable for 60
seconds, fatiguing well before twenty minutes. This isn't a
voice-selection problem. Kokoro's 54 "voices" are speaker embeddings
layered on one shared prosody model. Picking a different voice changes
timbre — pitch range, breathiness, accent — but the prosody model decides
where stress, pacing, and pitch contour actually land, sentence by
sentence, and that model doesn't change no matter which embedding feeds
it. Three samples were enough to confirm the flatness is structural, not a
sampling accident: the differences between the three are entirely
timbral, not rhythmic.

### Why more voices wouldn't help

The other 51 voices in `voices-v1.0.bin` run through the exact same
prosody model. Trying voice 4 through 54 would produce 51 more samples
with the identical rhythmic problem in a different timbre — diminishing
information for the time spent. The fix isn't a better voice, it's a
different prosody model, which is why Azure Neural TTS is next: Azure's
neural voices carry their own per-voice, per-style prosody rather than one
shared model behind swappable embeddings.

## Kokoro phoneme override: doesn't work through this pipeline

Tested `[[...]]`, espeak-ng's documented raw-phoneme escape syntax,
through kokoro_onnx's actual call path (phonemizer-fork's `phonemize()`).
Confirmed empirically that it does not pass through — phonemizer-fork's
espeak backend phonemizes the bracket characters as literal English text
(spelling out the letters) instead of treating the contents as phonemes.
A real override would mean bypassing phonemizer-fork and driving
espeak-ng's C API directly, which is more plumbing than a throwaway
experiment justifies, especially for a provider already being moved away
from.

The workaround in `narrate.py`: text-level respelling, tuned by inspecting
phonemizer's IPA output until it landed close —
`Hinterkaifeck` → `Hinter-kife-eck`, `Cäzilia` → `Tset-seel-ya`. This is
not a phoneme override, it's an approximation that happens to phonemize
correctly through English G2P. It's documented as such in code, not
passed off as the real thing.

Azure gets the real thing: SSML `<phoneme alphabet="ipa" ph="...">` with
hand-transcribed IPA. Ran successfully — see below.

## Azure Neural TTS — runs, quality not yet judged

First live run, `en-US-AriaNeural`, `swedencentral` region: succeeded on
the first attempt. `work/narration_azure_en-US-AriaNeural.wav`, 24kHz
mono, 67.85s (Kokoro's `am_michael` sample was 68.12s of the same
script — comparable pacing). Synthesis took 1.5s network round-trip
against Kokoro's 15.7s of local inference, which is expected: Azure is a
cloud call, not something to read as "faster" in any way that matters for
the render-time question later.

Confirms two things the plan flagged as unverified:
- `en-US-AriaNeural` does support the `narration-professional` style in
  this region — the request would have failed outright if it didn't.
- The IPA phoneme overrides for `Hinterkaifeck` and `Cäzilia` were
  accepted as valid SSML and sent (already confirmed offline that the XML
  was well-formed before this run; this confirms Azure accepted it too).

Quality itself — whether the prosody is actually better, not just
technically running — hasn't been judged yet. That's a listening
decision, not a technical one.

## Stage 2 (`align.py`) — faster-whisper timings, script text as ground truth

`faster-whisper` (`base`, `int8`, CPU) transcribed the Azure narration and gave
word-level timings; the script in `input/script.txt` supplied the text. The
two were aligned with `difflib.SequenceMatcher` on normalized tokens: `equal`
blocks transfer Whisper's timing directly, `replace` blocks (Whisper heard
*something*, just not the right word) spread that span's timing across the
script words it covers, and anything Whisper dropped or inserted entirely is
interpolated from the nearest known neighbors.

Of 171 script words, 167 matched Whisper's transcript exactly and 4 needed
the mis-transcription path: `Cäzilia`→"Zetzilya", `Viktoria`→"Victoria",
`Hinterkaifeck`→"Hinterkifeck" (all three IPA pronunciation-override names —
expected, since Whisper only has the audio, not the SSML), and `Keys`→"He's"
(a genuine mishearing, no override involved). That fourth one is exactly the
failure case this design exists for: a pipeline that burned in Whisper's own
transcript would have silently shipped "He's went missing from locked doors."
No script words needed full interpolation this run — Whisper's transcript was
complete, just locally wrong in four places.

Cues were grouped at 7 words / 42 characters, preferring to break at
sentence/clause punctuation once a cue has ≥3 words. 31 cues over 67.85s.
`work/subs.ass` has an explicit `[V4+ Styles]` block: Arial 64pt, outline 3,
shadow 1, bottom-centered (`Alignment: 2`), no background box.

## Stage 3 (`shots.py`) — Ken Burns cost is in the filter, not the encoder

The three source images for this run were deliberately *not* Hinterkaifeck
photos — they're oversized stock photos (4366–7360px long edge, up to ~30MB)
picked specifically to stress-test render cost, because the real archival
material can't do that job. See the product-level finding below.

Each image: PIL decode, EXIF-orientation fix (`ImageOps.exif_transpose`),
downscale to ~2x the output frame height (2160px) before handing it to
ffmpeg. Skipping that downscale would mean zoompan's own upscale step
(`scale=iw*4:ih*4`, needed to avoid visible integer-rounding stepping on slow
zooms per docs/SLICE-SPEC.md) operating on a 7360px source — a ~29000px
intermediate frame, 16x the pixels for no visual benefit. Downscaling first
keeps the intermediate around 13000px (still comfortably above the 2496px
floor `fitness.py` requires for a full zoom push) while cutting the zoompan
filter's per-frame cost by roughly the same 16x.

Decode/prep was cheap and not the bottleneck: 0.2–0.5s per image even at
30MP+ source resolution. Encode was the real cost: ~18.5s per shot for a
22.6s clip, i.e. barely faster than realtime, at only 36–38 fps output. No
fallback warnings appeared in ffmpeg's stderr, so `h264_videotoolbox` was
genuinely engaged — the slowness is the zoompan filter itself doing
per-frame zoom math on a ~12-13000px-wide intermediate frame, not the
hardware encoder. This means the zoom-push cost scales with *source
resolution after prep*, not with output resolution — a fixed prep target
bounds it, which is exactly what the 2160px downscale step is doing.

Peak memory: 697MB in the main process (PIL decode of a 7360×4912 source,
plus faster-whisper's model living in-process from stage 2), 296MB in child
processes (ffmpeg). Nowhere near the 8GB ceiling with these three shots;
whether that holds for a 20-minute episode's worth of shots run back-to-back
is still an open question — this run never had more than one decoded image
in memory at a time.

## A/B test (`ab_test_zoom.py`): why shots:encode is 5x slower than compose:deliver

The prompt for this: `shots:encode` runs at ~1.26x realtime (54.4s of the
72.4s total run) while `compose:deliver` — same encoder, same 1920x1080
output, same machine — runs at ~6.2x realtime. Hypothesis: zoompan's
`scale=iw*4:ih*4` step rescales the *entire* prepped frame every output
frame, at a fixed cost regardless of how tight the crop is, so
`h264_videotoolbox` sits idle waiting on the filter graph rather than being
the bottleneck itself. Two things tested against the current 2.0x/2160p
zoompan default; **the default in `shots.py` was not changed by this
test** — it only measures.

### Part 1 — prep scale factor vs. zoompan cost

Re-prepped each of the three source images at 2.0x, 1.4x, and 1.2x output
height (2160p / 1512p / 1296p) and re-ran the exact same zoompan encode
(`-b:v 20M`, same zoom curve, same duration) against each:

```
scale 2.0x (2160p): avg 18.17s/shot  (1.25x realtime)  peak RSS ~280MB
scale 1.4x (1512p): avg 10.04s/shot  (2.25x realtime)  peak RSS ~178MB
scale 1.2x (1296p): avg  7.66s/shot  (2.95x realtime)  peak RSS ~152MB
```

Confirms the hypothesis directly: lower prep resolution costs meaningfully
less, close to the O(n²) scaling you'd expect from rescaling fewer pixels
per frame (linear-dimension ratios of 2160:1512:1296 ≈ 1 : 0.70 : 0.60,
squared ≈ 1 : 0.49 : 0.36; measured time ratios were 1 : 0.55 : 0.42 —
same direction, roughly the right magnitude).

**Visual quality check, tightest zoom (last frame, zoom=1.3x), largest
source (Poggersdorf, 7360×4912):** cropped into the highest-frequency
detail in frame — bare tree branches against sky — at all three scale
factors. No perceptible softening at any of the three, including 1.2x.
Worth being precise about why: at zoom=1.3x, the *effective* source
resolution feeding the final 1920px-wide frame is prep_width / 1.3. For
1.2x prep (~1944px wide), that's ~1495px — technically *below* 1920px,
meaning the last frame is very slightly upscaled, not downscaled. It isn't
visible on this content (soft winter branches, no fine text or hard edges),
but that's a property of *this* test content, not a guarantee — real
archival material with document text or sharp edges (e.g. the
`Aussageprotokoll` witness-statement scans mentioned in the product-level
finding below) would show upscaling artifacts sooner. 1.4x prep stays at
native resolution or better through the whole zoom range for these
aspect ratios (~1.5); 1.2x is the more aggressive choice.

Note this is a different question from what `fitness.py`'s
`FULL_MOTION_LONG_EDGE_PX` (2496px) gates — that threshold is about whether
the *original candidate photo* is fit to push-zoom at all. This test is
about how far an *already-qualified* image can be downscaled before
handing it to zoompan, purely for render-speed reasons. A 1.4x-prepped
7360px source and a fitness-gated 2496px source are different concerns
that happen to land in a similar range by coincidence of this test's
numbers, not because they're the same gate.

### Part 2 — zoompan vs. crop+scale (both at the 2.0x/2160p default prep)

Replaced zoompan with a filter chain that crops a shrinking window
directly out of the prepped frame (`crop=w='iw/zoom(t)':h='ih/zoom(t)':...`
with `zoom(t)` ramping 1.0→1.3 over the clip) and scales just that window
up to 1920x1080 — no 4x full-frame upscale at all. Prediction going in:
this should be dramatically cheaper, since it processes far fewer pixels
per frame (a shrinking ~3241px→2493px crop region vs. zoompan's fixed
~12964px canvas every frame).

**That prediction was wrong — no meaningful speedup:**

```
zoompan    @2.0x prep: avg 18.17s/shot (1.25x realtime)
crop+scale @2.0x prep: avg 17.88s/shot (1.27x realtime)
speedup: 1.02x -- a wash
```

Most likely explanation: `crop`'s output dimensions change on nearly every
frame (the crop rectangle shrinks continuously), which forces the
downstream `scale` filter to reinitialize its resampling context on
essentially every frame instead of reusing one fixed-size context for the
whole clip — a well-known ffmpeg cost that likely erases whatever was saved
by processing fewer raw pixels. Not confirmed by profiling ffmpeg
internals, but consistent with the numbers and standard behavior of
per-frame-varying `scale` parameters.

**Motion smoothness — worse, not equivalent.** Extracted 6 consecutive
frames mid-clip for both approaches and measured frame-to-frame mean
absolute pixel difference (grayscale) as a jerkiness proxy — smooth motion
should show fairly consistent diffs frame to frame; stepping shows
alternating near-zero (stuck/repeated frame) and large (multi-pixel jump)
diffs:

```
zoompan     diffs=[6.94, 7.80, 6.90, 6.20, 7.95]  mean=7.16  variance=0.41
crop+scale  diffs=[0.14, 9.72, 12.67, 0.17, 12.73]  mean=7.09  variance=33.20
```

zoompan's diffs are tight and consistent (variance 0.41) — smooth,
continuous motion, confirming its 4x-upscale trick does what
docs/SLICE-SPEC.md says it does. crop+scale's diffs alternate between
near-zero and large jumps (variance 33.2, ~80x higher) — two of the five
gaps are near-frozen frames followed by a 2-pixel-equivalent jump. This is
exactly the integer-pixel-rounding stepping problem SLICE-SPEC's zoompan
note originally warned about, just relocated to `crop`'s rectangle instead
of zoompan's canvas: cropping directly from a 2160p-scale frame (not
upscaled 4x first) means each frame's crop width can only take on
relatively few distinct integer values across a 679-frame clip, so
consecutive frames frequently round to the identical crop size.

**Conclusion: crop+scale is not a win.** No speed advantage (1.02x, noise
level) and materially worse smoothness. It would likely need its own
upscale-before-crop step to fix the stepping, at which point it's paying a
similar cost to zoompan for a similar reason and the whole exercise loses
its point. Not recommending it; `shots.py` still uses zoompan.

### Adopted: `PREP_SCALE_FACTOR = 1.4`

2.0x→1.4x cuts `shots:encode` from 18.2s to 10.0s/shot (45% less) with no
visible quality loss on this content. 1.2x was rejected as the default
despite its bigger win (7.7s/shot, 58% less): at zoom=1.3x its last frame
feeds the output from ~1495px of source, an actual upscale, and the real
content this pipeline exists for is document/newspaper scans — exactly
where that shows up first, unlike the soft winter-branch test content here
that happened to hide it. 1.4x stays at native resolution or better across
the whole zoom range for these aspect ratios.

Made this a named constant (`PREP_SCALE_FACTOR`, `shots.py`) with a
comment tying it to `ZOOM_END`, not a bare `1.4` in the prep call: the safe
value is `effective_source_at_max_zoom = PREP_SCALE_FACTOR / ZOOM_END`,
which needs to stay ≥ 1.0 for the tightest frame of the push to not be an
upscale. At `ZOOM_END = 1.3`, `1.4` gives a small margin above the `1.3`
break-even point; `1.2` sits below it. If the zoom curve ever pushes past
1.3x, this ratio needs recomputing against the new `ZOOM_END`, not left as
a leftover magic number.

crop+scale stays rejected (previous section) — `shots.py` still uses
zoompan, just at the new prep scale.

## Two real timing runs — both canonical, neither supersedes the other

Everything above used the deliberate oversized-stock-photo stress test.
That measures an upper bound on encode cost, not what a real episode
costs — the real Hinterkaifeck-era images are ~1000px, which `fitness.py`
correctly rejects for any motion type, so `shots.py` was never actually
exercising the code path a real case would hit. Two gaps closed to make
this a real second measurement rather than a hypothetical one:

- `shots.py`'s `INPUT_DIR` is now overridable via `SHOTS_INPUT_DIR`, and
  **defaults to `input_archival/`** — the realistic case is the default,
  not an opt-in. `input/` (the stress-test set) is used by setting
  `SHOTS_INPUT_DIR` explicitly. Both sets stay on disk permanently:
  `input/`'s stock photos are gitignored (cost nothing in the repo) but
  are the fixed upper-bound reference for measuring any future encoder or
  zoom-curve change against — deleting them would mean no comparable
  baseline later. `input_archival/`'s three real images are small (~900KB
  total) and committed.
- `shots.py` now actually *acts* on `fitness.py`'s verdict instead of just
  printing it. When `MotionType.ZOOM_IN` isn't in `allowed_motion_types`,
  `encode_shot_static()` runs instead of the zoompan push: the source is
  composited over a blurred, cover-scaled copy of itself (fills 16:9
  without a hard edge) with the sharp image centered on top at its best
  fit, held static for the shot's duration. This is the same treatment for
  "too small for any motion" and "portrait narrower than 1080px" (SLICE-
  SPEC's `requires_letterbox` case) — one code path handles both, since a
  blurred-fill background covers either problem.

Downloaded three real Hinterkaifeck-era images from Wikimedia Commons for
`input_archival/`, verified via the API in an earlier stage of this
experiment: `Hinterkaifeck-Hof.jpg` (918×716, the farmstead itself, public
domain — photographer died 1954), `Hinterkaifeck.jpg` (448×932, portrait,
the victims' memorial stone, CC0), `Photo_-_Hinterkaifeck.jpg` (960×430,
CC BY-SA 4.0). All three: `meets_minimum_resolution=False`,
`allowed_motion_types` empty, exactly as expected. The portrait one also
triggers `requires_letterbox=True`.

### Results (both at `PREP_SCALE_FACTOR = 1.4`, both with subtitle burn-in)

```
                          stress test (input/)     archival (input_archival/)
shots:prep (avg)          ~0.35s/shot               ~0.01s/shot
shots:encode (avg)        9.7s/shot (zoompan)       3.6s/shot (static+blurred-fill)
compose:deliver           11.0s                     11.1s
total                     47.4s                     27.7s
extrapolated (20min)      14.0 minutes              8.1 minutes
peak RSS (deliver)        1131MB                    1086MB
```

The archival case is ~40% cheaper end to end than the already-reduced
stress test, and the `shots:encode` gap is the whole story: static +
blurred-fill on a already-tiny source is a much smaller job for
`h264_videotoolbox` than a zoompan push on a 2.4MP prepped frame (3.6s vs
9.7s/shot). `compose:deliver` cost is essentially unchanged between the two
(11.0s vs 11.1s) — that stage's cost is driven by output duration and
resolution, not by what happened upstream, which is the expected and
correct result.

**Both numbers are canonical — neither is provisional or superseded by the
other:**
- **14.0 minutes (stress test, `input/`) is the upper bound.** Fixed
  reference for measuring any future change to the encoder, the zoom
  curve, or `PREP_SCALE_FACTOR` against. If a future change makes this
  number worse, that's a real regression even if the archival number looks
  fine, because a future case *could* legitimately have large, sharp
  sources (a well-preserved print, a modern reproduction).
- **8.1 minutes (`input_archival/`, now `shots.py`'s default) is the
  realistic case.** Real cases built from thin archival records — which,
  per the product-level finding below, is most of them for a case this
  old — should render close to this, not the stress-test number.

Neither replaces the other going forward: re-run both whenever something
upstream of `shots.py`/`compose.py` changes (encoder settings, zoom curve,
prep scale), and expect both figures to move together in the same
direction. If they diverge unexpectedly, that's a signal something is
now handling one source profile differently than the other, worth
investigating before trusting either number again.

Verified visually: extracted a frame from the portrait memorial-stone shot
(`work/shot2.mp4`) and confirmed the blurred-fill composite renders
correctly — sharp stone centered and legible (the actual inscription: "Am
31. März 1922 fiel... die Familie Gabriel-Gruber... zum Opfer" and the six
victims' names), blurred/darkened mirror of itself filling the sides, no
hard edge or flat-black letterboxing. `output/slice_delivery_archival.mp4`
and `output/timings_archival.txt` kept alongside `_stress` versions of both
for direct comparison.

## Stage 4 (`compose.py`) — was video-only-in-effect; now a real two-tier encode

**Before this fix, stage 4 was incomplete in a way that didn't announce
itself.** `mux()` fell back to `-c:v copy` whenever subtitle burn-in wasn't
available (which was every run, see below) — meaning the "final" video
stream was a byte-for-byte remux of `work/concat.mp4`, not an encode at
all. Audio *was* attached, so `output/slice.mp4` played with sound and
looked done, but there was no delivery-quality control anywhere: video
stayed at whatever the per-shot intermediates happened to produce (~14.4
Mbps, `yuvj420p` full-range, straight from JPEG decode), and audio rode
`ffmpeg`'s bare `-c:a aac` default (24kHz mono passthrough, not a real
delivery spec). `ffprobe` on `work/concat.mp4` — video-only by design, since
it's the pre-mux intermediate — was the thread that unraveled this: its
bitrate and pixel format turned out to be *identical* to the final output's,
which is only possible if the final pass never actually encoded anything.

**Fixed as a proper two-tier design:**
- Per-shot encode (`shots.py`) now pins an explicit high-bitrate
  intermediate (`-b:v 20M`) instead of relying on `h264_videotoolbox`'s
  default, which is what had quietly produced the ~14.4 Mbps figure above —
  not a documented guarantee, just whatever that encoder version defaults to.
- `concat.mp4` is still a `-c copy` stitch of those intermediates — no
  quality lost, nearly free, kept in `work/` for inspection.
- Exactly one delivery encode (`compose.deliver()`) does everything else in
  a single pass: mux the narration WAV, convert
  `scale=in_range=full:out_range=tv,format=yuv420p` (JPEG-sourced frames
  decode full-range; without this the output stays tagged `yuvj420p` and
  shifts levels on upload), encode with `h264_videotoolbox` at `-b:v 10M`,
  explicit `bt709` color tags, AAC at 192k/48kHz, and `-movflags
  +faststart`. Verified: `yuv420p`/`color_range=tv`/`bt709`, ~10.17 Mbps,
  48kHz AAC, `moov` before `mdat` in the file (faststart confirmed by byte
  offset). Video/audio duration are probed and logged before the encode
  (67.80s / 67.85s, 0.05s drift this run) with a warning if they differ by
  more than 0.2s, since `-shortest` truncates silently past that.
- Output goes to `output/slice_delivery.mp4` — deliberately not
  `output/slice.mp4`, so the old stream-copy artifact and the new real
  encode can't be confused mid-comparison. **This needs to collapse to one
  canonical output filename before this leaves the experiment stage** —
  keeping two names around is a debugging convenience, not a design worth
  carrying into the real pipeline.

**Subtitle burn-in is now working, but required an environment fix, not a
code fix.** Homebrew's regular `ffmpeg` formula ships with neither `libass`
nor `freetype` compiled in — confirmed directly, `ffmpeg -filters` only
matches `bass` (the audio filter), not `ass`. The full-featured build is
`ffmpeg-full`, from the `homebrew-ffmpeg/ffmpeg` tap, which does have
`libass`/`freetype`/`fontconfig` (`--enable-libass --enable-libfreetype
--enable-libfontconfig` in its build config) — but it's **keg-only**, so
even after installing it, plain `ffmpeg` on `PATH` still silently resolves
to the homebrew-core build. There's also a third candidate ffmpeg binary on
this machine, at `~/miniconda3/bin/ffmpeg` — enough ambiguity that trusting
`PATH` at all was a real risk of silent wrong-binary substitution, not a
hypothetical one.

Fixed with `ffmpeg_config.py`: `FFMPEG_BIN`/`FFPROBE_BIN` default to
`ffmpeg-full`'s keg-only path
(`/opt/homebrew/opt/ffmpeg-full/bin/ffmpeg{,probe}`), overridable via
environment variable, and every subprocess call in `shots.py`/`compose.py`
goes through them — no bare `"ffmpeg"`/`"ffprobe"` string anywhere in
either file. `resolve_and_log()` runs at the start of both `shots.run()`
and `compose.run()`, printing the resolved binary path, its version, and
whether the `ass` filter is present, so binary identity is visible in every
run's output rather than assumed. `burn_subs` was already a detected
capability before this (`deliver()` never hardcoded `False`) — with
`ffmpeg-full` pinned, it now resolves `True`, and subtitles burn in with no
code changes.

Verified visually, not just via ffprobe: extracted the frame at 8s from
`output/slice_delivery.mp4` and confirmed "his wife Cäzilia," is burned in,
bottom-centered with outline, matching stage 2's `[V4+ Styles]` block —
including the `ä` rendering correctly (fontconfig resolving a real glyph,
not a tofu box).

This was an environment prerequisite for stage 4/5, not a code defect: the
code path for burn-in was correct the whole time, it simply had no working
`ass` filter to call until a full-featured ffmpeg build was pinned by
explicit path.

(Also worth noting for later: uninstalling the old `ffmpeg` formula while
troubleshooting this auto-removed 12 "unneeded" dependent formulae,
including `python@3.11` — unrelated to this project's Python, which is
uv-managed and untouched, but worth knowing if something *else* on this
machine was quietly relying on that system Python.)

## Stage 5 (`run.py`) — timing table

`narrate` is not re-run by `run.py` — its Azure branch is a paid, rate-limited
network call, and re-hitting it just to reproduce a number already measured
(1.51s synth_time from the original narrate.py run, see above) buys nothing.
That figure is carried in as a labeled constant. Everything else below is a
live measurement from this run.

Peak RSS is now logged per row, not just once at the end — a number near the
8GB ceiling on any single step would invalidate that step's timing (thrashing
counted as "work"). Two different things feed it: `shots:encode` and
`compose:concat`/`compose:deliver` get an exact peak RSS for that one ffmpeg
process via `/usr/bin/time -l`; `align` and `shots:prep` run in-process, so
they get `resource.getrusage(RUSAGE_SELF).ru_maxrss` instead, which is a
*cumulative* high-water mark for the whole Python process (monotonic, never
decreases) rather than an isolated per-step figure — labeled as such rather
than passed off as something more precise than it is.

Shot 1's encode is split from shots 2–3's steady-state average in the
extrapolation. Shot 1 pays `ffmpeg`'s filter-graph init and a cold page
cache that the later shots don't; folding it into a flat per-shot average
and multiplying by an extrapolated shot count overstates the real cost. The
20-minute estimate below uses shot 1's actual cost once (a fixed, one-time
overhead) plus the steady-state per-output-second rate for the rest.

```
ffmpeg binary : /opt/homebrew/opt/ffmpeg-full/bin/ffmpeg
ffprobe binary: /opt/homebrew/opt/ffmpeg-full/bin/ffprobe
version       : ffmpeg version 8.1.2 Copyright (c) 2000-2026 the FFmpeg developers
ass filter    : present

(peak RSS: align/shots:prep = cumulative process high-water mark; shots:encode/compose = exact per-call, via /usr/bin/time -l)
stage                                   seconds  per out. min  peak RSS MB
narrate (azure, recorded)                   1.5           1.3          n/a
align                                       3.9           3.5          594
shots:prep shot1                            0.4           0.3          594
shots:prep shot2                            0.5           0.5          594
shots:prep shot3                            0.2           0.2          594
shots:encode shot1 (cold start)            18.6          16.4          274
shots:encode shot2                         17.9          15.8          305
shots:encode shot3                         17.9          15.9          301
shots:encode steady-state avg (n=2)        17.9          15.8          n/a  (info only)
compose:concat                              0.4           0.4           33
compose:deliver (burned)                   11.0           9.8         1140
--------------------------------------------------------------------------
total                                      72.4          64.0

extrapolated to a 20-minute episode: 21.2 minutes (uses shots 2..N steady-state rate, not shot 1's cold-start cost)

peak RSS across all child processes this run (cumulative high-water mark, not per-step): 1140 MB
```

This is the first fully real number: 21.2 minutes to render 20 minutes of
output, subtitle burn-in included this time (the previous 18.6/21.1-minute
figures in earlier drafts of this file did not — that gap is now closed).
The delivery encode's cost barely moved with burn-in on (11.0s either way,
same 1.1GB-ish peak RSS) — burning the ASS overlay is cheap relative to the
decode+filter+encode pass it's already riding on, which answers the open
question from the previous revision of this section. Same caveats as
before still apply: this is an upper bound (stress-test images, not
real archival-scale sources), and `output/slice_delivery.mp4` is still a
temporary name that needs to collapse to one canonical output filename
before this leaves the experiment stage. The single delivery encode
(`compose:deliver`, ~1.1GB peak RSS, ~11s for 67.8s of 1080p) is the
largest single memory consumer in the whole run — still well under the 8GB
ceiling here, but worth tracking as episode length grows, since it
processes the entire video in one pass rather than per-shot chunks.

## Product-level finding: archival photo resolution is a real ceiling, not a test artifact

The actual Hinterkaifeck-era photographs on Wikimedia Commons cap out around
1000px on the long edge — `packages/archive/fitness.py` correctly reports
zero safe motion types for them (`meets_minimum_resolution=False`, confirmed
against real files earlier in this experiment). This isn't a fixable gap in
the source-gathering step; it's a property of hundred-year-old negatives and
prints. Genuinely old archival material often cannot support a Ken Burns
zoom at 1080p+ no matter how carefully it's sourced.

This means the real pipeline needs a deliberate answer for low-resolution
archival stills beyond "reject and hope for a better source" — e.g. static
frame with blurred-fill background (which `fitness.py` already has the
signals for: `meets_minimum_resolution=False` plus `requires_letterbox`),
accepting visible softening for genuinely irreplaceable images, or leaning
harder on illustrative/generic imagery for cases where the archival record
is this thin. That's a product decision for `packages/visual/`, not
something this throwaway slice needs to solve — but it's a real constraint
the shot-list logic will hit on essentially every case this old, not an
edge case.
