"""Offline TTS via macOS `/usr/bin/say` -- v1 implementation of
packages.voice.provider.VoiceProvider.

`say` writes AIFF natively; downstream forced alignment and mixing
want WAV, so every `synthesize()` call converts AIFF -> WAV with
ffmpeg immediately after `say` writes it, and only the WAV path is
ever returned. The conversion forces `-f wav` explicitly rather than
inferring format from out_path's extension, so the output is
guaranteed to actually be WAV regardless of what extension a caller
happens to pass.

SCOPE BOUNDARY, same as provider.py: no database access, no
`packages.db` import, no LLM calls, no `VoiceTrack`/`Asset` write.
"""

from __future__ import annotations

import re
import subprocess
import tempfile
from collections.abc import Sequence
from pathlib import Path

from packages.visual.render import FFMPEG_BIN
from packages.visual.timing import NARRATION_WPM
from packages.voice.provider import VoiceSpec


class SayNotFoundError(Exception):
    """Raised at import time if /usr/bin/say is not present. No
    fallback -- this module has nothing to do without it."""

    def __init__(self, path: str) -> None:
        self.path = path
        super().__init__(f"{path!r} not found -- this module requires macOS's say.")


def _require_say(path: str) -> str:
    if not Path(path).is_file():
        raise SayNotFoundError(path)
    return path


SAY_BIN = _require_say("/usr/bin/say")

# Novelty/sound-effect voices present on macOS -- unusable for
# documentary narration (CLAUDE.md's R4: documentary register, not
# sensationalism), and an automated pipeline picking one would be a
# quality failure with no human in the loop before render to catch it.
# Confirmed present in real `say -v '?'` output on this machine before
# writing this list, not assumed from memory.
VOICE_DENYLIST: frozenset[str] = frozenset(
    {
        "Bad News", "Bahh", "Bells", "Boing", "Bubbles", "Cellos",
        "Good News", "Jester", "Junior", "Organ", "Superstar",
        "Trinoids", "Whisper", "Wobble", "Zarvox",
    }
)

# NARRATION_WPM (150), not repeated -- see that constant's own comment
# in packages/visual/timing.py for why 150 is the rate this project
# narrates at.
DEFAULT_VOICE_NAME = "Samantha"  # confirmed present in real `say -v '?'` output before hardcoding
DEFAULT_WPM = NARRATION_WPM


class VoiceListParseError(Exception):
    """Raised when a non-blank line from `say -v '?'` doesn't match
    the expected NAME LOCALE # SAMPLE shape. Raised, not skipped --
    silently dropping an unparseable line would silently shrink the
    available voice list instead of surfacing that a parsing
    assumption broke."""

    def __init__(self, line: str) -> None:
        self.line = line
        super().__init__(f"could not parse voice list line: {line!r}")


# Voice names can contain nested parentheses ("Eddy (English (UK))",
# "Grandma (English (US))"), and the full string including parentheses
# is what `say -v` expects -- so this cannot split on the first
# parenthesis. It also cannot reliably split on "the first run of 2+
# spaces," despite that looking like the obvious column boundary:
# `say` pads the name column to a fixed width for SHORT names (many
# spaces before the locale), but a long name like "Eddy (English
# (UK))" already fills that column, leaving only a SINGLE space before
# the locale code -- confirmed directly against real output before
# writing this, not assumed; splitting there would merge the name and
# locale into one field for every long name. What's actually reliable
# is the locale code's own shape (two lowercase letters, an
# underscore, then letters/digits -- "en_US", "ar_001") immediately
# followed by the run of 2+ spaces that always precedes "# <sample
# text>", regardless of name length. That's the anchor this pattern
# uses; verified against all 184 real lines on this machine, zero
# unparsed, before this was finalized.
_VOICE_LINE_PATTERN = re.compile(r"^(.+?)\s+[a-z]{2}_[A-Za-z0-9]+\s{2,}#")


def available_voices() -> list[str]:
    """Real voice names from `say -v '?'`, excluding VOICE_DENYLIST."""
    result = subprocess.run([SAY_BIN, "-v", "?"], capture_output=True, text=True, check=True)

    voices: list[str] = []
    for line in result.stdout.splitlines():
        if not line.strip():
            continue
        match = _VOICE_LINE_PATTERN.match(line)
        if match is None:
            raise VoiceListParseError(line)
        name = match.group(1)
        if name not in VOICE_DENYLIST:
            voices.append(name)
    return voices


class SayProvider:
    def __init__(self, spec: VoiceSpec | None = None) -> None:
        self._spec = spec if spec is not None else VoiceSpec(DEFAULT_VOICE_NAME, DEFAULT_WPM)

    def synthesize(self, text: str, out_path: Path) -> Path:
        out_path.parent.mkdir(parents=True, exist_ok=True)

        with tempfile.TemporaryDirectory() as tmp_dir:
            aiff_path = Path(tmp_dir) / "say_output.aiff"

            say_cmd = [
                SAY_BIN,
                "-v", self._spec.voice_name,
                "-r", str(self._spec.wpm),
                "-o", str(aiff_path),
                text,
            ]
            say_result = subprocess.run(say_cmd, capture_output=True, text=True)
            if say_result.returncode != 0:
                raise RuntimeError(f"say failed on {out_path.name}:\n{say_result.stderr}")

            ffmpeg_cmd = [
                FFMPEG_BIN, "-y", "-hide_banner", "-v", "warning",
                "-i", str(aiff_path),
                "-f", "wav",
                str(out_path),
            ]
            ffmpeg_result = subprocess.run(ffmpeg_cmd, capture_output=True, text=True)
            if ffmpeg_result.returncode != 0:
                raise RuntimeError(
                    f"ffmpeg AIFF->WAV conversion failed on {out_path.name}:\n"
                    f"{ffmpeg_result.stderr}"
                )

        return out_path

    def synthesize_cards(self, texts: Sequence[str], out_dir: Path) -> list[Path]:
        """One WAV per text, named by index, so each card gets its own
        clip -- same ordering convention as packages/visual/render.py's
        own per-card PNG/clip naming."""
        out_dir.mkdir(parents=True, exist_ok=True)
        return [
            self.synthesize(text, out_dir / f"card_{i:04d}.wav") for i, text in enumerate(texts)
        ]
