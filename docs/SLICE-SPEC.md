# Vertical slice — the media pipeline, end to end

`experiments/slice_01/`

Produce one watchable 60-second video from a hardcoded script and three images,
and measure how long every stage takes.

**This is throwaway code.** It does not touch the database, the API, or any
existing package. It imports nothing from `packages/` except `fitness.py`. It
will be read once, learned from, and either deleted or rewritten properly.
Do not make it configurable, do not make it general, do not write tests beyond
what's needed to know it worked.

The output is not a feature. The output is three numbers and a file you watch.

---

## What we're actually trying to learn

1. **Render time.** How long does 60 seconds of 1080p Ken Burns take on an
   8 GB M-series Air? Multiply out to 20 minutes. If that number is 90 minutes,
   the whole "several videos a week" premise needs rethinking.
2. **Voice quality.** Is free local TTS tolerable for twenty minutes of
   documentary narration, or does it become grating? Sixty seconds is enough to
   know.
3. **Memory ceiling.** Does anything swap or get killed at 8 GB?

A fourth thing you'll learn incidentally: how much fiddling the subtitle
alignment needs before it looks professional.

---

## Stack

Add to the project's dev dependencies, or install into a throwaway venv inside
`experiments/` — your call, but prefer the throwaway venv so a heavy ML
dependency doesn't become part of the main project before it's earned its place.

- **TTS: `kokoro-onnx`.** Try this before the `kokoro` package. `kokoro` pulls
  in PyTorch (~2 GB); `kokoro-onnx` runs the same model through onnxruntime at a
  fraction of the footprint, which matters at 8 GB. Model weights download on
  first run (~350 MB) — expect a wait, and note it so it isn't mistaken for a
  hang.
- **Alignment: `faster-whisper`**, `base` model. Uses CTranslate2, no PyTorch.
  Downloads ~150 MB on first run. `small` if `base` mis-times noticeably, but
  start with `base`.
- **Rendering: ffmpeg via subprocess.** Already installed (8.1.2). No MoviePy —
  it holds decoded frames in RAM and that's the exact resource you're short on.
- **Fitness: `packages/archive/fitness.py`**, already built. Use it. This is the
  first time that code meets a real image and it should tell you whether a
  source is big enough to zoom.

---

## Inputs

`experiments/slice_01/input/`

- `script.txt` — roughly 150 words of documentary narration. Write it yourself
  or take it from any of the seeded subjects; the content doesn't matter, but
  the *register* does. Write it the way the real thing would be written, in
  full sentences with proper punctuation, because punctuation is what TTS uses
  for prosody and a script written as fragments will sound wrong for reasons
  that have nothing to do with the model.
- `shot1.jpg`, `shot2.jpg`, `shot3.jpg` — three public-domain images. Get them
  from Wikimedia Commons by hand. **Deliberately pick a mix:** one at least
  2500px on the long edge, one between 1920 and 2500, one in portrait
  orientation. That way the slice exercises all three branches of `fitness.py`
  and the aspect-ratio handling, rather than the easy case three times.

---

## Stages

Five scripts, each runnable alone, each writing to `work/` so a failed stage
doesn't force re-running the ones before it. `run.py` calls them in order and
times each.

### 1. `narrate.py` — script → audio

Read `script.txt`, synthesize to `work/narration.wav` at 24 kHz mono.

Print the voice identifier used and the audio duration. Try at least three
different Kokoro voices and keep the files — you're evaluating them, and you
can't do that from one sample. Name the outputs by voice so you can A/B.

### 2. `align.py` — audio → subtitle timings

Run `faster-whisper` over `work/narration.wav` with `word_timestamps=True`.

Important: you are transcribing audio whose exact text you already have.
Whisper will occasionally mis-transcribe a word, and when it does, take
Whisper's *timings* and your script's *text*. The script is ground truth. A
naive implementation that uses Whisper's transcript will silently introduce
errors into your subtitles.

Group words into cues of at most 42 characters or 7 words, whichever comes
first, breaking at punctuation where possible. Write `work/subs.ass` with an
explicit `[V4+ Styles]` block — font, size, outline, shadow, alignment,
margins. Bottom-centered, generous outline, no background box.

### 3. `shots.py` — images → per-shot clips

One clip per image, written to `work/shot1.mp4` etc. Divide the narration
duration by three for now; real shot durations come from the shot list later.

**The Ken Burns detail that will waste your afternoon if you skip it:**
ffmpeg's `zoompan` filter computes zoom on the *input* resolution and rounds
positions to integer pixels, which produces visible stepping on slow zooms.
The fix is to upscale before zoompan and downscale after:

```
scale=iw*4:ih*4,zoompan=z='min(zoom+0.0004,1.3)':d=<frames>:s=1920x1080:fps=30
```

Test a slow push-in specifically and watch it full-screen. If it judders, the
upscale factor is too low.

For images that aren't 16:9, fill the frame with a blurred, scaled copy of the
image itself behind the correctly-fitted foreground. Letterboxing to flat black
looks like a mistake; the blurred fill is what documentaries actually do.

Encode with `h264_videotoolbox`. On Apple Silicon this uses the hardware
encoder and is several times faster than `libx264` while barely touching the
CPU. Verify it's actually engaged — if ffmpeg silently falls back to software,
your timing numbers are wrong in the pessimistic direction and you'll draw the
wrong conclusion.

### 4. `compose.py` — clips + audio + subtitles → final

Concat the shot clips with the `concat` demuxer (not the filter — the demuxer
avoids re-encoding), attach the narration, burn in subtitles with the `ass`
filter, and write `output/slice.mp4`.

Burn the subtitles rather than muxing them as a soft track. Platforms treat
soft subs inconsistently and you want to see what the viewer sees.

### 5. `run.py` — orchestrate and measure

Run all four in order. Time each stage with `time.perf_counter()`. At the end
print a table:

```
stage        seconds    per output minute
narrate         12.4               12.4
align            8.1                8.1
shots           41.7               41.7
compose          6.2                6.2
------------------------------------------
total           68.4               68.4

extrapolated to a 20-minute episode: 22.8 minutes
```

The extrapolation is rough — some costs are fixed, some scale superlinearly —
but it's the number that matters, and having it wrong-but-close beats not
having it.

Also print peak memory. `resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss`
gets you the child processes, which is where ffmpeg lives.

---

## Done means

- `output/slice.mp4` exists, plays, and is 60 seconds of narrated video with
  legible subtitles and images that move without juddering.
- The timing table is printed and written to `output/timings.txt`.
- You have three narration samples in different voices and an opinion about
  which one you'd listen to for twenty minutes.

Then write down what you learned in `experiments/slice_01/FINDINGS.md` —
render time, the voice you picked and why, anything that was harder than
expected. That file is the actual deliverable. The video is evidence.

---

## Explicitly out of scope

No database. No API. No job queue. No music. No thumbnail. No transitions
between shots beyond a hard cut. No variation profile. No archive search — the
images are hand-picked and sitting in a folder.

If you find yourself generalizing anything in here, stop. The generalized
version gets written later, informed by what this teaches you.
