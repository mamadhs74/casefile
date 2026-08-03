"""Stage 1: script -> narration audio.

Throwaway code for experiments/slice_01 -- see docs/SLICE-SPEC.md and
FINDINGS.md. Not imported by anything, not meant to last.

Two providers behind synthesize(text, voice) -> Path:

- Kokoro (kokoro-onnx): always runs, no credentials needed. Its prosody
  isn't good enough for twenty minutes of narration -- see FINDINGS.md --
  kept here as a fallback that always works, not a candidate anymore.
- Azure Neural TTS: reads AZURE_SPEECH_KEY from the environment, never
  hardcoded, never written anywhere. Skipped entirely if unset, so this
  script still runs with nothing configured. UNTESTED as of this commit --
  no Azure account exists yet.
"""

import os
import time
from abc import ABC, abstractmethod
from pathlib import Path
from xml.sax.saxutils import escape as xml_escape

import httpx
import soundfile as sf
from kokoro_onnx import Kokoro

ROOT = Path(__file__).parent
SCRIPT_PATH = ROOT / "input" / "script.txt"
WORK_DIR = ROOT / "work"
MODEL_PATH = ROOT / "models" / "kokoro-v1.0.onnx"
VOICES_PATH = ROOT / "models" / "voices-v1.0.bin"

# Names the default English G2P mangles. Kokoro has no working per-word
# phoneme override in this pipeline -- the espeak-ng [[...]] raw-phoneme
# escape does not pass through phonemizer-fork, confirmed empirically, see
# FINDINGS.md -- so its entry is a plain-English respelling, tuned by
# inspecting phonemizer's IPA output until it landed close. Azure gets a
# real IPA override via SSML <phoneme>.
PRONUNCIATION_OVERRIDES = {
    "Hinterkaifeck": {
        "kokoro_respelling": "Hinter-kife-eck",
        "azure_ipa": "ˈhɪntɚkaɪfɛk",
    },
    "Cäzilia": {
        "kokoro_respelling": "Tset-seel-ya",
        "azure_ipa": "tsɛˈtsiːlja",
    },
}


class TTSProvider(ABC):
    name: str

    @abstractmethod
    def synthesize(self, text: str, voice: str) -> Path:
        """Write a 24kHz mono WAV to WORK_DIR and return its path."""


class KokoroProvider(TTSProvider):
    name = "kokoro"
    VOICES = ["am_michael"]  # one is enough now -- see FINDINGS.md

    def __init__(self) -> None:
        print(f"loading kokoro model ({MODEL_PATH.name}, {VOICES_PATH.name})...")
        self._kokoro = Kokoro(str(MODEL_PATH), str(VOICES_PATH))

    def synthesize(self, text: str, voice: str) -> Path:
        for name, override in PRONUNCIATION_OVERRIDES.items():
            text = text.replace(name, override["kokoro_respelling"])

        samples, sample_rate = self._kokoro.create(text, voice=voice, speed=1.0, lang="en-us")
        out_path = WORK_DIR / f"narration_kokoro_{voice}.wav"
        sf.write(str(out_path), samples, sample_rate, subtype="PCM_16")
        return out_path


class AzureProvider(TTSProvider):
    name = "azure"
    VOICES = ["en-US-AriaNeural"]
    SPEAKING_STYLE = "narration-professional"  # or "newscast-formal" -- try both once there's a key
    ENDPOINT = "https://{region}.tts.speech.microsoft.com/cognitiveservices/v1"

    def __init__(self) -> None:
        key = os.environ.get("AZURE_SPEECH_KEY")
        if not key:
            raise RuntimeError("AZURE_SPEECH_KEY not set")
        self._key = key
        self._region = os.environ.get("AZURE_SPEECH_REGION", "eastus")

    def _build_ssml(self, text: str, voice: str) -> str:
        escaped = xml_escape(text)
        for name, override in PRONUNCIATION_OVERRIDES.items():
            name_escaped = xml_escape(name)
            phoneme = f'<phoneme alphabet="ipa" ph="{override["azure_ipa"]}">{name_escaped}</phoneme>'
            escaped = escaped.replace(name_escaped, phoneme)

        return (
            '<speak version="1.0" xmlns="http://www.w3.org/2001/10/synthesis" '
            'xmlns:mstts="https://www.w3.org/2001/mstts" xml:lang="en-US">'
            f'<voice name="{voice}">'
            f'<mstts:express-as style="{self.SPEAKING_STYLE}">{escaped}</mstts:express-as>'
            "</voice></speak>"
        )

    def synthesize(self, text: str, voice: str) -> Path:
        ssml = self._build_ssml(text, voice)
        response = httpx.post(
            self.ENDPOINT.format(region=self._region),
            headers={
                "Ocp-Apim-Subscription-Key": self._key,
                "Content-Type": "application/ssml+xml; charset=utf-8",
                "X-Microsoft-OutputFormat": "riff-24khz-16bit-mono-pcm",
                "User-Agent": "casefile-slice-01",
            },
            content=ssml.encode("utf-8"),
            timeout=60.0,
        )
        response.raise_for_status()

        out_path = WORK_DIR / f"narration_azure_{voice}.wav"
        out_path.write_bytes(response.content)
        return out_path


def run_provider(provider: TTSProvider, text: str, voices: list[str]) -> None:
    for voice in voices:
        start = time.perf_counter()
        out_path = provider.synthesize(text, voice)
        elapsed = time.perf_counter() - start

        info = sf.info(str(out_path))
        print(
            f"{provider.name:8s} {voice:20s}  duration={info.duration:6.2f}s"
            f"  synth_time={elapsed:6.2f}s  sample_rate={info.samplerate}"
            f"  -> {out_path.relative_to(ROOT)}"
        )


def main() -> None:
    text = " ".join(SCRIPT_PATH.read_text().split())
    WORK_DIR.mkdir(exist_ok=True)

    run_provider(KokoroProvider(), text, KokoroProvider.VOICES)

    if os.environ.get("AZURE_SPEECH_KEY"):
        run_provider(AzureProvider(), text, AzureProvider.VOICES)
    else:
        print(
            "AZURE_SPEECH_KEY not set -- skipping Azure TTS. "
            "Set AZURE_SPEECH_KEY (and optionally AZURE_SPEECH_REGION, "
            "default eastus) to try it."
        )


if __name__ == "__main__":
    main()
