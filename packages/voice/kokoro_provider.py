"""Kokoro TTS (local, offline, no GPU) -- second implementation of
packages.voice.provider.VoiceProvider, alongside SayProvider. Neither
replaces the other: SayProvider stays as the fallback, unmodified.

Verified on this machine before writing this module: `uv add kokoro
soundfile`, then a real synthesis call, confirmed non-silent real
audio via soundfile amplitude inspection (max amplitude ~0.32, not the
near-zero a silent or broken file would show) -- not just a successful
process exit. No GPU required, no Apple Silicon error; it ran on CPU
through the same call every other environment uses.

Kokoro has no words-per-minute parameter -- `VoiceSpec.wpm` is
accepted (the Protocol requires it) and IGNORED here, unconditionally.
Concretely, this means per-card timing for Kokoro-narrated cards can
never come from `duration_for_words` -- there is no "requested rate"
here to even be wrong about, only real audio to measure. Timing has to
come from the same real measurement scripts/render_scratch_visual.py
already does against SayProvider's output.

Kokoro's native output is a float32 waveform at 24000 Hz mono.
SayProvider's own output -- and everything downstream that consumes
it, notably scripts/render_scratch_visual.py's concat step -- expects
22050 Hz mono pcm_s16le, so every synthesize() call here writes
Kokoro's native audio to a temp WAV first, then converts with ffmpeg
(FFMPEG_BIN, reused from packages.visual.render, not duplicated) to
that exact format. Same output contract as SayProvider, completely
different model underneath.

SCOPE BOUNDARY, same as provider.py and say_provider.py: no database
access, no `packages.db` import, no LLM calls, no `VoiceTrack`/`Asset`
write.
"""

from __future__ import annotations

import subprocess
import tempfile
from collections.abc import Sequence
from pathlib import Path

import soundfile as sf
import torch
from huggingface_hub import list_repo_files
from kokoro import KPipeline

from packages.visual.render import FFMPEG_BIN
from packages.voice.provider import VoiceSpec

REPO_ID = "hexgrad/Kokoro-82M"
NATIVE_SAMPLE_RATE = 24000

# Matches SayProvider's own output format exactly -- see module
# docstring for why.
OUTPUT_SAMPLE_RATE = 22050
OUTPUT_CHANNELS = "1"

# Measured, not guessed -- picked from Kokoro's own VOICES.md quality
# grades (hexgrad/Kokoro-82M on HuggingFace), not from listening, which
# isn't possible here. Among American English voices, af_heart is
# graded A -- the single highest overall grade of all 20 American
# English voices (af_bella is next, at A-), and it's also the voice
# used in the package's own README usage example. Cross-checked by
# actually synthesizing one real sentence with af_heart, af_bella,
# af_nicole, am_fenrir, am_michael, am_puck, and bf_emma before
# picking: all seven produced valid, non-silent audio with no errors,
# so this is a preference among working options, not a stand-in for a
# broken one. Best-graded alternatives, for override: af_bella (A-,
# female); am_fenrir, am_michael, am_puck (C+, the top American
# English male tier -- no American English male voice grades higher);
# bf_emma (B-, the top British English voice).
DEFAULT_VOICE_NAME = "af_heart"
DEFAULT_WPM = 150  # accepted, ignored -- see module docstring


def available_voices() -> list[str]:
    """Real voice names from the hexgrad/Kokoro-82M repo's voices/
    directory on HuggingFace Hub -- queried live, same "always ask the
    real source, never hardcode a stale snapshot" posture
    say_provider.py's own available_voices() already uses. Spans every
    language Kokoro ships a voice for, not just English -- the same
    inclusive convention say_provider.py uses (its VOICE_DENYLIST
    excludes novelty voices, not other languages)."""
    files = list_repo_files(REPO_ID)
    return sorted(
        f.rsplit("/", 1)[-1].removesuffix(".pt") for f in files if f.startswith("voices/")
    )


class KokoroProvider:
    def __init__(self, spec: VoiceSpec | None = None) -> None:
        self._spec = spec if spec is not None else VoiceSpec(DEFAULT_VOICE_NAME, DEFAULT_WPM)
        # The pipeline's lang_code has to match the voice's own prefix
        # (af_/am_ -> 'a', bf_/bm_ -> 'b', ...) -- Kokoro's own
        # LANG_CODES keys are exactly these single-letter prefixes, so
        # this is a real derivation, not a coincidence of English-only
        # naming. Built once, here, and reused for every synthesize()
        # call -- KPipeline loads a real model; constructing a fresh
        # one per call would reload it every time.
        lang_code = self._spec.voice_name[0]
        self._pipeline = KPipeline(lang_code=lang_code, repo_id=REPO_ID)

    def synthesize(self, text: str, out_path: Path) -> Path:
        out_path.parent.mkdir(parents=True, exist_ok=True)

        chunks = [result.audio for result in self._pipeline(text, voice=self._spec.voice_name)]
        audio = torch.cat(chunks)

        with tempfile.TemporaryDirectory() as tmp_dir:
            native_path = Path(tmp_dir) / "kokoro_output.wav"
            sf.write(native_path, audio.numpy(), NATIVE_SAMPLE_RATE)

            cmd = [
                FFMPEG_BIN, "-y", "-hide_banner", "-v", "warning",
                "-i", str(native_path),
                "-ar", str(OUTPUT_SAMPLE_RATE),
                "-ac", OUTPUT_CHANNELS,
                "-f", "wav", "-c:a", "pcm_s16le",
                str(out_path),
            ]
            result = subprocess.run(cmd, capture_output=True, text=True)
            if result.returncode != 0:
                raise RuntimeError(
                    f"ffmpeg failed converting Kokoro output for {out_path.name}:\n"
                    f"{result.stderr}"
                )

        return out_path

    def synthesize_cards(self, texts: Sequence[str], out_dir: Path) -> list[Path]:
        """One WAV per text, named by index -- same convention
        say_provider.py's own synthesize_cards() uses."""
        out_dir.mkdir(parents=True, exist_ok=True)
        return [
            self.synthesize(text, out_dir / f"card_{i:04d}.wav") for i, text in enumerate(texts)
        ]
