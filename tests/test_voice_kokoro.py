"""packages/voice/kokoro_provider.py -- Kokoro TTS. Every test here
shells out to ffmpeg for format conversion and runs a real model
inference pass, so all of them are marked slow -- pyproject.toml's
addopts already excludes slow tests from the default run (opt in with
`pytest -m slow`), the same convention tests/test_voice_say.py and
tests/test_visual_render.py established.

The KokoroProvider instance is a module-scoped fixture, not built
fresh per test: constructing one loads a real ~82M-parameter model
(measured at ~3s on this machine), and every test in this file uses
the same default voice, so there is no reason to pay that cost five
times over.
"""

from __future__ import annotations

import subprocess
from collections.abc import Iterator
from pathlib import Path

import pytest

from packages.voice.kokoro_provider import DEFAULT_VOICE_NAME, KokoroProvider, available_voices

# Measured directly before this test was written (real Kokoro
# synthesis, af_heart): 11.575s for this exact sentence, comfortably
# inside [8, 16]. Real prose, not a word-count filler -- same reasoning
# tests/test_voice_say.py's own 30-word text uses.
_THIRTY_WORD_TEXT = (
    "Ledger clerk Edith Voss told investigators she saw Reyes in the "
    "counting house after hours, carrying a canvas satchel, on the "
    "evening of March fourth, eighteen ninety three, that year."
)


@pytest.fixture(scope="module")
def provider() -> Iterator[KokoroProvider]:
    yield KokoroProvider()


def _ffprobe(path: Path, entries: str) -> str:
    result = subprocess.run(
        [
            "ffprobe", "-v", "error",
            "-show_entries", entries,
            "-of", "default=noprint_wrappers=1:nokey=1",
            str(path),
        ],
        capture_output=True, text=True, check=True,
    )
    return result.stdout.strip()


@pytest.mark.slow
def test_available_voices_is_non_empty() -> None:
    voices = available_voices()
    assert voices
    assert DEFAULT_VOICE_NAME in voices


@pytest.mark.slow
def test_synthesize_produces_a_non_empty_file(provider: KokoroProvider, tmp_path: Path) -> None:
    out_path = provider.synthesize("A short test sentence.", tmp_path / "out.wav")

    assert out_path.exists()
    assert out_path.stat().st_size > 0


@pytest.mark.slow
def test_synthesize_output_is_wav_22050_mono_with_positive_duration(
    provider: KokoroProvider, tmp_path: Path
) -> None:
    out_path = provider.synthesize("A short test sentence.", tmp_path / "out.wav")

    assert "wav" in _ffprobe(out_path, "format=format_name").lower()
    assert _ffprobe(out_path, "stream=sample_rate") == "22050"
    assert _ffprobe(out_path, "stream=channels") == "1"

    duration = float(_ffprobe(out_path, "format=duration"))
    assert duration > 0.0


@pytest.mark.slow
def test_synthesize_cards_with_three_texts_produces_three_files(
    provider: KokoroProvider, tmp_path: Path
) -> None:
    texts = ["First card text.", "Second card text.", "Third card text."]

    paths = provider.synthesize_cards(texts, tmp_path)

    assert len(paths) == 3
    for path in paths:
        assert path.exists()
        assert path.stat().st_size > 0


@pytest.mark.slow
def test_30_word_text_produces_audio_between_8_and_16_seconds(
    provider: KokoroProvider, tmp_path: Path
) -> None:
    assert len(_THIRTY_WORD_TEXT.split()) == 30

    out_path = provider.synthesize(_THIRTY_WORD_TEXT, tmp_path / "out.wav")
    measured = float(_ffprobe(out_path, "format=duration"))

    assert 8.0 <= measured <= 16.0, f"measured {measured:.3f}s -- outside the [8, 16]s range"
