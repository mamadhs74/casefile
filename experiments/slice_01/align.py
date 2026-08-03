"""Stage 2: narration audio -> subtitle timings.

Throwaway code for experiments/slice_01 -- see docs/SLICE-SPEC.md and
FINDINGS.md. Not imported by anything, not meant to last.

faster-whisper (base, word_timestamps=True) gives us *timings*. It does not
give us *text* -- the script in input/script.txt is ground truth, because
Whisper will occasionally mis-transcribe a word (mishear "Cäzilia", drop an
article, hallucinate a filler word) and a naive pipeline that burns in
Whisper's own transcript would silently ship those errors as subtitles.

So: transcribe, then align Whisper's word list against the script's word
list with difflib (they're both just sequences of tokens), carry Whisper's
timing across wherever the words match, and interpolate across whatever
Whisper missed or added. Then group the script's words into cues and write
work/subs.ass.
"""

import re
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path

from faster_whisper import WhisperModel

ROOT = Path(__file__).parent
SCRIPT_PATH = ROOT / "input" / "script.txt"
WORK_DIR = ROOT / "work"
NARRATION_PATH = WORK_DIR / "narration_azure_en-US-AriaNeural.wav"
SUBS_PATH = WORK_DIR / "subs.ass"

WHISPER_MODEL = "base"
MAX_CUE_CHARS = 42
MAX_CUE_WORDS = 7
SENTENCE_END = ".!?"
CLAUSE_END = ".!?,;:"


@dataclass
class TimedWord:
    text: str  # original script spelling/punctuation, for display
    start: float
    end: float


def normalize(token: str) -> str:
    """Strip to bare lowercase letters/digits for matching Whisper against the script."""
    return re.sub(r"[^\w]", "", token).lower()


def transcribe(audio_path: Path) -> list[tuple[str, float, float]]:
    print(f"loading faster-whisper ({WHISPER_MODEL}, int8, cpu)...")
    model = WhisperModel(WHISPER_MODEL, device="cpu", compute_type="int8")

    segments, info = model.transcribe(str(audio_path), word_timestamps=True)
    print(f"detected language: {info.language} (p={info.language_probability:.2f})")

    words: list[tuple[str, float, float]] = []
    for segment in segments:
        for word in segment.words:
            words.append((word.word.strip(), word.start, word.end))
    return words


def align_to_script(
    whisper_words: list[tuple[str, float, float]], script_tokens: list[str]
) -> list[TimedWord]:
    """Carry Whisper's timings onto the script's words.

    difflib treats both word lists as opaque token sequences and reports the
    edit script between them. 'equal' blocks are the easy case -- direct
    timing transfer. Everything else (Whisper mis-transcribed, dropped, or
    inserted a word) has no direct timing, so it's interpolated afterward
    from whatever known timings bracket the gap, spread across the gap's
    script words in proportion to their character length.
    """
    norm_whisper = [normalize(w) for w, _, _ in whisper_words]
    norm_script = [normalize(t) for t in script_tokens]
    matcher = SequenceMatcher(None, norm_whisper, norm_script, autojunk=False)

    known: list[tuple[float, float] | None] = [None] * len(script_tokens)
    exact_count = 0
    replaced_count = 0

    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            for k in range(i2 - i1):
                _, start, end = whisper_words[i1 + k]
                known[j1 + k] = (start, end)
                exact_count += 1
        elif tag == "replace" and i2 > i1 and j2 > j1:
            # Whisper heard *something* here, just not the right word(s).
            # Spread that time span across the script words it covers.
            heard = " ".join(w for w, _, _ in whisper_words[i1:i2])
            expected = " ".join(script_tokens[j1:j2])
            print(f"  mis-transcribed: whisper heard {heard!r}, script says {expected!r}")
            block_start = whisper_words[i1][1]
            block_end = whisper_words[i2 - 1][2]
            span = block_end - block_start
            lengths = [len(script_tokens[j]) for j in range(j1, j2)]
            total_len = sum(lengths) or 1
            t = block_start
            for offset, j in enumerate(range(j1, j2)):
                dur = span * (lengths[offset] / total_len)
                known[j] = (t, t + dur)
                t += dur
                replaced_count += 1
        # 'delete' -> extra Whisper words (hallucination/filler) with no
        # script counterpart: dropped, nothing to assign.
        # 'insert' and empty 'replace' -> script words Whisper never heard
        # at all: left as None, filled in by interpolation below.

    interpolated_count = known.count(None)
    _interpolate_gaps(known, script_tokens)
    print(
        f"alignment: {exact_count} exact, {replaced_count} timed via a mis-transcribed "
        f"span, {interpolated_count} fully interpolated (of {len(script_tokens)} script words)"
    )

    return [
        TimedWord(text=script_tokens[j], start=known[j][0], end=known[j][1])  # type: ignore[index]
        for j in range(len(script_tokens))
    ]


def _interpolate_gaps(
    known: list[tuple[float, float] | None], script_tokens: list[str]
) -> None:
    n = len(known)
    i = 0
    while i < n:
        if known[i] is not None:
            i += 1
            continue
        gap_start = i
        while i < n and known[i] is None:
            i += 1
        gap_end = i  # exclusive

        prev_end = known[gap_start - 1][1] if gap_start > 0 else 0.0
        next_start = known[gap_end][0] if gap_end < n else prev_end + 0.3

        span = max(next_start - prev_end, 0.01)
        lengths = [len(script_tokens[j]) for j in range(gap_start, gap_end)]
        total_len = sum(lengths) or 1
        t = prev_end
        for offset, j in enumerate(range(gap_start, gap_end)):
            dur = span * (lengths[offset] / total_len)
            known[j] = (t, t + dur)
            t += dur


def group_cues(words: list[TimedWord]) -> list[list[TimedWord]]:
    """Pack words into cues of at most 7 words / 42 chars, preferring to
    break at sentence/clause punctuation once a cue has real content."""
    cues: list[list[TimedWord]] = []
    current: list[TimedWord] = []
    current_chars = 0

    for word in words:
        added_chars = len(word.text) + (1 if current else 0)
        if current and (
            current_chars + added_chars > MAX_CUE_CHARS or len(current) >= MAX_CUE_WORDS
        ):
            cues.append(current)
            current, current_chars, added_chars = [], 0, len(word.text)

        current.append(word)
        current_chars += added_chars

        last_char = word.text[-1:] if word.text else ""
        if len(current) >= 3 and last_char in CLAUSE_END:
            cues.append(current)
            current, current_chars = [], 0

    if current:
        cues.append(current)
    return cues


def format_ass_time(seconds: float) -> str:
    seconds = max(seconds, 0.0)
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = seconds % 60
    centis = round((secs - int(secs)) * 100)
    if centis == 100:
        centis = 0
        secs += 1
    return f"{hours}:{minutes:02d}:{int(secs):02d}.{centis:02d}"


ASS_HEADER = """[Script Info]
Title: casefile slice_01 stage 2
ScriptType: v4.00+
WrapStyle: 2
ScaledBorderAndShadow: yes
PlayResX: 1920
PlayResY: 1080

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Arial,64,&H00FFFFFF,&H000000FF,&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,3,1,2,80,80,60,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""


def write_ass(cues: list[list[TimedWord]], out_path: Path) -> None:
    lines = [ASS_HEADER]
    for cue in cues:
        start = format_ass_time(cue[0].start)
        end = format_ass_time(cue[-1].end)
        text = " ".join(w.text for w in cue)
        lines.append(f"Dialogue: 0,{start},{end},Default,,0,0,0,,{text}\n")
    out_path.write_text("".join(lines))


def main() -> None:
    if not NARRATION_PATH.exists():
        raise FileNotFoundError(
            f"{NARRATION_PATH} not found -- run narrate.py first (Azure branch)."
        )

    script_tokens = " ".join(SCRIPT_PATH.read_text().split()).split(" ")

    whisper_words = transcribe(NARRATION_PATH)
    print(f"whisper produced {len(whisper_words)} words; script has {len(script_tokens)}")

    timed_words = align_to_script(whisper_words, script_tokens)
    cues = group_cues(timed_words)
    print(f"grouped into {len(cues)} cues")

    write_ass(cues, SUBS_PATH)
    print(f"-> {SUBS_PATH.relative_to(ROOT)}")

    print("\nfirst few cues, for a sanity check before burning anything in:")
    for cue in cues[:8]:
        start = format_ass_time(cue[0].start)
        end = format_ass_time(cue[-1].end)
        text = " ".join(w.text for w in cue)
        print(f"  [{start} -> {end}]  {text}")


if __name__ == "__main__":
    main()
