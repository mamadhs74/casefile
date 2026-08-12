"""Provider seam for text-to-speech backends. One Protocol, one spec
dataclass, zero implementation -- so a better backend can replace
packages.voice.say_provider.SayProvider later without any caller
changing.

SCOPE BOUNDARY: no database access, no `packages.db` import, no LLM
calls, no `VoiceTrack`/`Asset` write. This module (and its
implementations) turn text into audio files; persisting that as a
`VoiceTrack` row is a later task's job, not this one's.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


@dataclass(frozen=True)
class VoiceSpec:
    voice_name: str
    wpm: int


class VoiceProvider(Protocol):
    def synthesize(self, text: str, out_path: Path) -> Path:
        """Writes audio for `text` to out_path and returns out_path.
        Implementations raise on failure rather than returning a
        partial or silent file."""
        ...
