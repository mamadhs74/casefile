"""packages/voice/say_provider.py -- offline TTS via macOS `say`. Every
test here shells out to `say` and/or ffmpeg, so all of them are marked
slow -- pyproject.toml's addopts already excludes slow tests from the
default run (opt in with `pytest -m slow`), the same convention
tests/test_visual_render.py established.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from packages.visual.timing import NARRATION_WPM, duration_for_words
from packages.voice.provider import VoiceSpec
from packages.voice.say_provider import (
    DEFAULT_VOICE_NAME,
    VOICE_DENYLIST,
    SayProvider,
    available_voices,
)

# Measured directly before this test was written (real `say -v Samantha
# -r 150`): 11.716s against duration_for_words(30, 150) == 12.0s, a
# 0.284s diff -- comfortably inside the 3.0s tolerance, not a value
# picked to make the test pass. A degenerate "word "*30 input measured
# 9.01s against the same 12.0s prediction (2.99s diff, right at the
# tolerance edge) -- real prose tracks the requested rate much more
# closely than a monotone word list does, which is why this text is
# realistic prose, not a word count filler.
_THIRTY_WORD_TEXT = (
    "Ledger clerk Edith Voss told investigators she saw Reyes in the "
    "counting house after hours, carrying a canvas satchel, on the "
    "evening of March fourth, eighteen ninety three, that year."
)


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
def test_available_voices_is_non_empty_and_includes_a_known_voice() -> None:
    voices = available_voices()
    assert voices
    assert DEFAULT_VOICE_NAME in voices


@pytest.mark.slow
def test_available_voices_excludes_every_denylisted_name() -> None:
    voices = set(available_voices())
    overlap = voices & VOICE_DENYLIST
    assert not overlap, f"denylisted voices leaked through: {overlap}"


@pytest.mark.slow
def test_paren_named_voice_round_trips_through_synthesize(tmp_path: Path) -> None:
    voices = available_voices()
    paren_names = [name for name in voices if "(" in name]
    assert paren_names, "no parenthesized voice name found to test against"

    provider = SayProvider(VoiceSpec(voice_name=paren_names[0], wpm=NARRATION_WPM))
    out_path = provider.synthesize(
        "Testing a voice name with nested parentheses.", tmp_path / "out.wav"
    )

    assert out_path.exists()
    assert out_path.stat().st_size > 0


@pytest.mark.slow
def test_synthesize_produces_a_non_empty_file(tmp_path: Path) -> None:
    provider = SayProvider()
    out_path = provider.synthesize("A short test sentence.", tmp_path / "out.wav")

    assert out_path.exists()
    assert out_path.stat().st_size > 0


@pytest.mark.slow
def test_synthesize_output_is_wav_with_positive_duration(tmp_path: Path) -> None:
    provider = SayProvider()
    out_path = provider.synthesize("A short test sentence.", tmp_path / "out.wav")

    assert _ffprobe(out_path, "stream=codec_type") == "audio"
    assert "wav" in _ffprobe(out_path, "format=format_name").lower()

    duration = float(_ffprobe(out_path, "format=duration"))
    assert duration > 0.0


@pytest.mark.slow
def test_30_word_text_matches_duration_for_words_within_3_seconds(tmp_path: Path) -> None:
    assert len(_THIRTY_WORD_TEXT.split()) == 30

    provider = SayProvider(VoiceSpec(voice_name=DEFAULT_VOICE_NAME, wpm=NARRATION_WPM))
    out_path = provider.synthesize(_THIRTY_WORD_TEXT, tmp_path / "out.wav")

    measured = float(_ffprobe(out_path, "format=duration"))
    predicted = duration_for_words(30, wpm=NARRATION_WPM)
    diff = abs(measured - predicted)

    assert diff <= 3.0, (
        f"measured {measured:.3f}s vs. duration_for_words' predicted {predicted:.3f}s "
        f"-- diff {diff:.3f}s exceeds the 3.0s tolerance"
    )


@pytest.mark.slow
def test_synthesize_cards_with_three_texts_produces_three_files(tmp_path: Path) -> None:
    provider = SayProvider()
    texts = ["First card text.", "Second card text.", "Third card text."]

    paths = provider.synthesize_cards(texts, tmp_path)

    assert len(paths) == 3
    for path in paths:
        assert path.exists()
        assert path.stat().st_size > 0
