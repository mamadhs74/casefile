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
