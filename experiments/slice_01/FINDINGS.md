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

## Stage 4 (`compose.py`) — subtitle burn-in blocked by the ffmpeg build, not the code

Concat demuxer + `-c copy` stitched the three clips in 0.3-0.4s, as expected
— no re-encoding, just container-level work.

Subtitle burn-in did not happen this run. The installed ffmpeg is Homebrew's
regular `ffmpeg` formula, which — it turns out — ships without `libass`
*and* without `freetype`, so neither the `ass` filter nor `drawtext` exists
in this build at all. The full-featured build lives in the
`homebrew-ffmpeg/ffmpeg` tap, but its bottle isn't published for this OS
version, so installing it means compiling from source — which failed
because this machine's Xcode Command Line Tools (16.0) are older than what
Xcode 26.3-era source needs. Fixing that needs an App Store / Xcode update,
which is not something to do as a side effect of a render-timing test.

Net effect: `output/slice.mp4` exists and plays (1920x1080, h264, AAC audio,
67.8s) but without burned-in subtitles this run. `work/subs.ass` is still a
valid, correct stage-2 artifact — the gap is entirely in stage 4's ability
to render it, and it's an environment problem with a known fix, not an
unknown one.

(Also worth noting for later: uninstalling the old `ffmpeg` formula to try
the tap version auto-removed 12 "unneeded" dependent formulae, including
`python@3.11` — unrelated to this project's Python, which is uv-managed and
untouched, but worth knowing if something *else* on this machine was quietly
relying on that system Python.)

## Stage 5 (`run.py`) — timing table

`narrate` is not re-run by `run.py` — its Azure branch is a paid, rate-limited
network call, and re-hitting it just to reproduce a number already measured
(1.51s synth_time from the original narrate.py run, see above) buys nothing.
That figure is carried in as a labeled constant. Everything else below is a
live measurement from this run.

```
stage                      seconds   per output minute
narrate (azure, recorded)       1.5                 1.3
align                          4.1                 3.6
shots:prep shot1               0.4                 0.3
shots:encode shot1            18.6                16.4
shots:prep shot2               0.5                 0.5
shots:encode shot2            18.3                16.2
shots:prep shot3               0.2                 0.2
shots:encode shot3            18.5                16.3
compose:concat                 0.4                 0.3
compose:mux (no burn)          0.6                 0.5
------------------------------------------------------
total                         63.0                55.7

extrapolated to a 20-minute episode: 18.6 minutes

peak memory -- this process (PIL decode/prep): 697 MB, child processes (ffmpeg/whisper): 296 MB
```

18.6 minutes to render 20 minutes of output is a workable ratio for "several
videos a week" on this hardware — with two caveats. First, this is an upper
bound: these three source images (up to ~30MB, 36MP) are far larger than
typical archival material, chosen specifically to stress the render path;
real Hinterkaifeck-scale sources would cost less to encode, not more.
Second, subtitle burn-in isn't in this number at all (see stage 4) — once
that's unblocked, the extrapolation needs redoing with the real burn-in cost
included, which will not be free (it's a full decode+encode pass over 20
minutes of 1080p video).

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
