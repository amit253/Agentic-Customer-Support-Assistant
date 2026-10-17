"""File-based STT -> SupportService -> TTS voice baseline."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Literal, Protocol

from .config import Settings
from .contracts import ContractValidationError, parse_order_id
from .logging_config import log_event
from .pipeline import SupportResponse, SupportService, build_live_support_service
from .tracing import trace_context


class AudioValidationError(ValueError):
    """Raised when a recorded clip is not a supported PCM WAV input."""


class VoiceProviderError(RuntimeError):
    """Raised when STT or TTS cannot produce a valid result."""


@dataclass(frozen=True, slots=True)
class AudioMetadata:
    path: str
    sample_rate: int
    channels: int
    sample_width_bytes: int
    frames: int
    duration_seconds: float
    file_bytes: int


@dataclass(frozen=True, slots=True)
class SpeechTranscript:
    text: str
    language: str | None = None
    duration_seconds: float | None = None


@dataclass(frozen=True, slots=True)
class VoiceTurnResult:
    status: Literal["ok", "failed"]
    trace_id: str
    input_path: str
    transcript: str | None
    support_status: str | None
    output_path: str | None
    error_code: str | None
    support_message: str | None = None
    input_audio: AudioMetadata | None = None
    output_audio: AudioMetadata | None = None


class SpeechToText(Protocol):
    def transcribe(self, audio_path: Path) -> SpeechTranscript:
        """Transcribe one validated audio file."""


class TextToSpeech(Protocol):
    def synthesize(self, text: str, output_path: Path) -> AudioMetadata:
        """Write playable audio to output_path."""


def inspect_wav(audio_path: Path, *, max_bytes: int = 25_000_000) -> AudioMetadata:
    """Inspect a PCM WAV without decoding or exposing audio content."""

    if not audio_path.is_file():
        raise AudioValidationError("audio_file_not_found")
    file_bytes = audio_path.stat().st_size
    if file_bytes > max_bytes:
        raise AudioValidationError("audio_file_too_large")
    try:
        with wave.open(str(audio_path), "rb") as wav:
            frames = wav.getnframes()
            sample_rate = wav.getframerate()
            channels = wav.getnchannels()
            sample_width = wav.getsampwidth()
            compression = wav.getcomptype()
    except (wave.Error, OSError) as exc:
        raise AudioValidationError("invalid_wav_file") from exc
    if compression != "NONE":
        raise AudioValidationError("compressed_wav_not_supported")
    if frames <= 0 or sample_rate <= 0:
        raise AudioValidationError("empty_or_invalid_wav")
    return AudioMetadata(
        path=str(audio_path),
        sample_rate=sample_rate,
        channels=channels,
        sample_width_bytes=sample_width,
        frames=frames,
        duration_seconds=frames / sample_rate,
        file_bytes=file_bytes,
    )


def validate_input_wav(audio_path: Path) -> AudioMetadata:
    """Require the recorded-input format used by the baseline pipeline."""

    metadata = inspect_wav(audio_path)
    if metadata.channels != 1:
        raise AudioValidationError("input_audio_must_be_mono")
    if metadata.sample_width_bytes != 2:
        raise AudioValidationError("input_audio_must_be_16_bit_pcm")
    if metadata.sample_rate != 16_000:
        raise AudioValidationError("input_audio_must_be_16khz")
    return metadata


class GroqSpeechToText:
    """Groq Whisper-compatible transcription adapter."""

    def __init__(self, settings: Settings, *, client: Any | None = None) -> None:
        self.model_name = settings.groq_stt_model
        if client is None:
            from groq import Groq

            client = Groq(api_key=settings.require_groq_credentials()[0])
        self._client = client

    def transcribe(self, audio_path: Path) -> SpeechTranscript:
        validate_input_wav(audio_path)
        try:
            with audio_path.open("rb") as audio_file:
                response = self._client.audio.transcriptions.create(
                    file=(audio_path.name, audio_file),
                    model=self.model_name,
                    response_format="verbose_json",
                    temperature=0.0,
                )
        except Exception as exc:
            raise VoiceProviderError("stt_provider_failed") from exc
        text = getattr(response, "text", None)
        if not isinstance(text, str) or not text.strip():
            raise VoiceProviderError("stt_returned_empty_transcript")
        duration = getattr(response, "duration", None)
        return SpeechTranscript(
            text=_normalize_transcribed_order_ids(" ".join(text.split())),
            language=getattr(response, "language", None),
            duration_seconds=float(duration) if isinstance(duration, (int, float)) else None,
        )


_ORDER_ID_SPEECH_PATTERN = re.compile(
    r"\bNS(?:-|\s)?(?P<year>\d{2})(?:-|\s)?"
    r"(?P<sequence>\d{4})(?:-|\s)?(?P<check_digit>\d)\b",
    re.IGNORECASE,
)


def _normalize_transcribed_order_ids(text: str) -> str:
    def restore_valid_id(match: re.Match[str]) -> str:
        order_id = (
            f"NS-{match.group('year')}-{match.group('sequence')}-"
            f"{match.group('check_digit')}"
        )
        try:
            parse_order_id(order_id)
        except ContractValidationError:
            return match.group(0)
        return order_id

    return _ORDER_ID_SPEECH_PATTERN.sub(restore_valid_id, text)


class GroqTextToSpeech:
    """Groq speech endpoint adapter that writes WAV output."""

    def __init__(self, settings: Settings, *, client: Any | None = None) -> None:
        self.model_name = settings.groq_tts_model
        self.voice = settings.groq_tts_voice
        if client is None:
            from groq import Groq

            client = Groq(api_key=settings.require_groq_credentials()[0])
        self._client = client

    def synthesize(self, text: str, output_path: Path) -> AudioMetadata:
        if not text.strip():
            raise VoiceProviderError("tts_input_empty")
        output_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            response = self._client.audio.speech.create(
                model=self.model_name,
                voice=self.voice,
                input=text,
                response_format="wav",
            )
            if hasattr(response, "write_to_file"):
                response.write_to_file(str(output_path))
            else:
                content = response.read() if hasattr(response, "read") else response.content
                output_path.write_bytes(content)
        except Exception as exc:
            raise VoiceProviderError("tts_provider_failed") from exc
        return inspect_wav(output_path)


class WindowsSpeechSynthesizer:
    """Write local Windows speech to a WAV without requiring provider access."""

    _SCRIPT = """
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Speech
$payload = Get-Content -LiteralPath $env:VOICE_TTS_PAYLOAD_FILE -Raw -Encoding UTF8 | ConvertFrom-Json
$synth = New-Object System.Speech.Synthesis.SpeechSynthesizer
try {
    $synth.SetOutputToWaveFile($payload.output_path)
    $synth.Speak($payload.text)
} finally {
    $synth.Dispose()
}
"""

    def __init__(
        self,
        *,
        powershell_path: str | None = None,
        runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
    ) -> None:
        executable = (
            shutil.which("powershell.exe")
            if powershell_path is None
            else powershell_path
        )
        self._powershell_path = executable or None
        self._runner = runner

    def synthesize(self, text: str, output_path: Path) -> AudioMetadata:
        if not text.strip():
            raise VoiceProviderError("tts_input_empty")
        if self._powershell_path is None:
            raise VoiceProviderError("windows_tts_unavailable")

        output_path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(
            {"text": text, "output_path": str(output_path.resolve())},
            ensure_ascii=False,
        )
        child_environment = os.environ.copy()
        child_environment.pop("GROQ_API_KEY", None)
        child_environment.pop("GROQ_API_KEYS", None)

        try:
            with tempfile.TemporaryDirectory(prefix="agentic-support-tts-") as folder:
                payload_path = Path(folder) / "request.json"
                payload_path.write_text(payload, encoding="utf-8")
                child_environment["VOICE_TTS_PAYLOAD_FILE"] = str(payload_path)
                completed = self._runner(
                    [
                        self._powershell_path,
                        "-NoLogo",
                        "-NoProfile",
                        "-NonInteractive",
                        "-Command",
                        self._SCRIPT,
                    ],
                    capture_output=True,
                    check=False,
                    env=child_environment,
                    text=True,
                    timeout=60,
                )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise VoiceProviderError("windows_tts_provider_failed") from exc
        if completed.returncode != 0:
            raise VoiceProviderError("windows_tts_provider_failed")
        return inspect_wav(output_path)


class VoicePipeline:
    """Run one file-based voice turn through the shared SupportService."""

    def __init__(
        self,
        *,
        support_service: SupportService,
        stt: SpeechToText,
        tts: TextToSpeech,
    ) -> None:
        self.support_service = support_service
        self.stt = stt
        self.tts = tts

    def process(
        self,
        audio_path: Path,
        *,
        session_id: str = "demo-session-omar",
        trace_id: str | None = None,
        output_path: Path | None = None,
    ) -> VoiceTurnResult:
        with trace_context(trace_id) as active_trace_id:
            try:
                input_metadata = validate_input_wav(audio_path)
            except AudioValidationError as exc:
                return VoiceTurnResult(
                    status="failed",
                    trace_id=active_trace_id,
                    input_path=str(audio_path),
                    transcript=None,
                    support_status=None,
                    output_path=None,
                    error_code=str(exc),
                    support_message=None,
                )

            try:
                transcript = self.stt.transcribe(audio_path)
            except VoiceProviderError as exc:
                return VoiceTurnResult(
                    status="failed",
                    trace_id=active_trace_id,
                    input_path=str(audio_path),
                    transcript=None,
                    support_status=None,
                    output_path=None,
                    error_code=str(exc),
                    support_message=None,
                    input_audio=input_metadata,
                )

            support_response: SupportResponse = self.support_service.handle(
                transcript.text,
                session_id=session_id,
                channel="voice",
                trace_id=active_trace_id,
            )
            target = output_path or Path("recordings") / f"voice-{active_trace_id}.wav"
            try:
                output_metadata = self.tts.synthesize(support_response.message, target)
            except (AudioValidationError, VoiceProviderError) as exc:
                log_event(
                    self.support_service.logger,
                    "voice_tts_failed",
                    reason=str(exc),
                )
                return VoiceTurnResult(
                    status="failed",
                    trace_id=active_trace_id,
                    input_path=str(audio_path),
                    transcript=transcript.text,
                    support_status=support_response.status,
                    output_path=str(target),
                    error_code=str(exc),
                    support_message=support_response.message,
                    input_audio=input_metadata,
                )
            return VoiceTurnResult(
                status="ok",
                trace_id=active_trace_id,
                input_path=str(audio_path),
                transcript=transcript.text,
                support_status=support_response.status,
                output_path=str(target),
                error_code=None,
                support_message=support_response.message,
                input_audio=input_metadata,
                output_audio=output_metadata,
            )


def build_live_voice_pipeline(settings: Settings | None = None) -> VoicePipeline:
    """Build Groq STT, shared support, and local Windows TTS for voice turns."""

    active_settings = settings or Settings.from_environment()
    return VoicePipeline(
        support_service=build_live_support_service(active_settings),
        stt=GroqSpeechToText(active_settings),
        tts=WindowsSpeechSynthesizer(),
    )
