from __future__ import annotations

import json
import subprocess
import wave
from pathlib import Path
from types import SimpleNamespace

import pytest

from agentic_support.config import Settings
from agentic_support.handlers import build_default_registry
from agentic_support.pipeline import SupportService
from agentic_support.routing import StructuredIntentRouter
from agentic_support.tools import DeterministicOrderTools
from agentic_support.voice import (
    GroqSpeechToText,
    GroqTextToSpeech,
    SpeechTranscript,
    VoicePipeline,
    VoiceProviderError,
    WindowsSpeechSynthesizer,
    inspect_wav,
)


def write_wav(path: Path, *, sample_rate: int = 16_000, channels: int = 1) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    frames = 1600
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(channels)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        wav.writeframes(b"\x00\x00" * frames * channels)


class FakeStt:
    def transcribe(self, audio_path: Path) -> SpeechTranscript:
        return SpeechTranscript("Where is order NS-26-4006-8?", language="en")


class FakeTts:
    def __init__(self) -> None:
        self.text: str | None = None

    def synthesize(self, text: str, output_path: Path):
        self.text = text
        write_wav(output_path, sample_rate=24_000)
        return inspect_wav(output_path)


def build_voice_service() -> SupportService:
    classifier = SimpleNamespace(
        classify=lambda message: {"intent": "order_status", "confidence": 0.99}
    )
    return SupportService(
        router=StructuredIntentRouter(classifier),
        registry=build_default_registry(order_tools=DeterministicOrderTools()),
    )


def test_file_voice_turn_uses_shared_service_and_writes_playable_audio(
    tmp_path: Path,
) -> None:
    input_path = tmp_path / "input.wav"
    output_path = tmp_path / "response.wav"
    write_wav(input_path)
    tts = FakeTts()

    result = VoicePipeline(
        support_service=build_voice_service(),
        stt=FakeStt(),
        tts=tts,
    ).process(
        input_path,
        session_id="demo-session-omar",
        trace_id="voice-test-trace",
        output_path=output_path,
    )

    assert result.status == "ok"
    assert result.trace_id == "voice-test-trace"
    assert result.transcript == "Where is order NS-26-4006-8?"
    assert result.support_status == "ok"
    assert result.support_message is not None
    assert "Order NS-26-4006-8 status: in_transit." in result.support_message
    assert tts.text == result.support_message
    assert output_path.is_file()
    assert result.output_audio is not None
    assert result.output_audio.sample_rate == 24_000


def test_invalid_input_format_returns_structured_failure(tmp_path: Path) -> None:
    input_path = tmp_path / "stereo.wav"
    write_wav(input_path, channels=2)
    stt = FakeStt()

    result = VoicePipeline(
        support_service=build_voice_service(),
        stt=stt,
        tts=FakeTts(),
    ).process(input_path, trace_id="invalid-audio")

    assert result.status == "failed"
    assert result.error_code == "input_audio_must_be_mono"


def test_stt_failure_returns_structured_failure(tmp_path: Path) -> None:
    input_path = tmp_path / "input.wav"
    write_wav(input_path)

    class BrokenStt:
        attempts = 0

        def transcribe(self, audio_path: Path) -> SpeechTranscript:
            self.attempts += 1
            raise VoiceProviderError("stt_provider_failed")

    stt = BrokenStt()
    tts = FakeTts()
    result = VoicePipeline(
        support_service=build_voice_service(),
        stt=stt,
        tts=tts,
    ).process(
        input_path,
        trace_id="stt-failure",
        output_path=tmp_path / "safe-handoff.wav",
    )

    assert result.status == "handoff"
    assert result.error_code == "stt_provider_failed_safe_handoff"
    assert result.transcript is None
    assert result.support_status == "failed_closed"
    assert result.stt_attempts == 2
    assert stt.attempts == 2
    assert result.output_audio is not None
    assert "request human support" in (result.support_message or "")
    assert tts.text == result.support_message
    assert result.latency_ms is not None and result.latency_ms >= 0


def test_groq_stt_adapter_uses_whisper_transcription_contract(tmp_path: Path) -> None:
    input_path = tmp_path / "input.wav"
    write_wav(input_path)
    captured: dict[str, object] = {}

    def create(**kwargs: object) -> object:
        captured.update(kwargs)
        return SimpleNamespace(
            text="Where is order NS2640068?", language="en", duration=1.2
        )

    client = SimpleNamespace(
        audio=SimpleNamespace(transcriptions=SimpleNamespace(create=create))
    )
    settings = Settings.from_environment(
        {"GROQ_API_KEY": "fake", "GROQ_STT_MODEL": "whisper-large-v3-turbo"}
    )
    transcript = GroqSpeechToText(settings, client=client).transcribe(input_path)

    assert transcript.text == "Where is order NS-26-4006-8?"
    assert captured["model"] == "whisper-large-v3-turbo"
    assert captured["response_format"] == "verbose_json"


def test_groq_stt_does_not_repair_invalid_order_id_check_digit(
    tmp_path: Path,
) -> None:
    input_path = tmp_path / "input.wav"
    write_wav(input_path)
    client = SimpleNamespace(
        audio=SimpleNamespace(
            transcriptions=SimpleNamespace(
                create=lambda **kwargs: SimpleNamespace(text="Order NS2640069")
            )
        )
    )
    settings = Settings.from_environment({"GROQ_API_KEY": "fake"})

    transcript = GroqSpeechToText(settings, client=client).transcribe(input_path)

    assert transcript.text == "Order NS2640069"


def test_groq_tts_adapter_writes_wav_from_sdk_response(tmp_path: Path) -> None:
    output_path = tmp_path / "tts.wav"

    class FakeSpeechResponse:
        def write_to_file(self, path: str) -> None:
            write_wav(Path(path), sample_rate=24_000)

    def create(**kwargs: object) -> FakeSpeechResponse:
        assert kwargs["response_format"] == "wav"
        return FakeSpeechResponse()

    client = SimpleNamespace(
        audio=SimpleNamespace(speech=SimpleNamespace(create=create))
    )
    settings = Settings.from_environment(
        {
            "GROQ_API_KEY": "fake",
            "GROQ_TTS_MODEL": "canopylabs/orpheus-v1-english",
            "GROQ_TTS_VOICE": "austin",
        }
    )
    metadata = GroqTextToSpeech(settings, client=client).synthesize(
        "Hello from the support line.", output_path
    )

    assert output_path.is_file()
    assert metadata.sample_rate == 24_000


def test_windows_tts_writes_playable_wav_without_forwarding_provider_keys(
    tmp_path: Path, monkeypatch
) -> None:
    output_path = tmp_path / "response.wav"
    payload_files: list[Path] = []
    monkeypatch.setenv("GROQ_API_KEY", "gsk_fake_key")
    monkeypatch.setenv("GROQ_API_KEYS", "gsk_fake_keys")

    def run_command(
        args: list[str], **kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        environment = kwargs["env"]
        assert isinstance(environment, dict)
        assert "GROQ_API_KEY" not in environment
        assert "GROQ_API_KEYS" not in environment
        payload_path = Path(environment["VOICE_TTS_PAYLOAD_FILE"])
        payload_files.append(payload_path)
        payload = json.loads(payload_path.read_text(encoding="utf-8"))
        assert payload["text"] == "Hello from the support line."
        assert Path(payload["output_path"]) == output_path.resolve()
        write_wav(output_path, sample_rate=22_050)
        return subprocess.CompletedProcess(
            args=args, returncode=0, stdout="", stderr=""
        )

    metadata = WindowsSpeechSynthesizer(
        powershell_path="powershell.exe", runner=run_command
    ).synthesize("Hello from the support line.", output_path)

    assert output_path.is_file()
    assert metadata.sample_rate == 22_050
    assert payload_files
    assert not payload_files[0].exists()


def test_windows_tts_reports_missing_power_shell(tmp_path: Path) -> None:
    synthesizer = WindowsSpeechSynthesizer(powershell_path="")

    with pytest.raises(VoiceProviderError, match="windows_tts_unavailable"):
        synthesizer.synthesize("Hello.", tmp_path / "response.wav")
