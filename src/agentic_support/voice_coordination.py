"""Turn ownership, cancellation, stale-result rejection, and VAD events."""

from __future__ import annotations

import logging
import threading
import time
import wave
from collections import deque
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Callable, Iterator, Protocol


class TurnState(StrEnum):
    PROCESSING = "processing"
    SPEAKING = "speaking"
    INTERRUPTED = "interrupted"
    COMPLETED = "completed"
    FAILED = "failed"


class VoiceActivity(StrEnum):
    SPEECH_STARTED = "speech_started"
    SPEECH_ENDED = "speech_ended"


class VadEngine(Protocol):
    def is_speech(self, frame: bytes, sample_rate: int) -> bool:
        """Return whether a valid PCM frame contains speech."""


class SpeechConfirmer(Protocol):
    def process_frame(self, frame: bytes) -> bool | None:
        """Return an independent speech decision when enough audio is buffered."""


class SileroSpeechConfirmer:
    """Confirm WebRTC candidates with the local Silero ONNX speech model."""

    MODEL_SAMPLE_RATE = 16_000
    MODEL_CHUNK_SAMPLES = 512
    SPEECH_PROBABILITY_THRESHOLD = 0.5

    def __init__(self, *, model: Callable[..., object] | None = None) -> None:
        import numpy
        import torch

        if model is None:
            from silero_vad import load_silero_vad

            model = load_silero_vad(onnx=True)
        reset_states = getattr(model, "reset_states", None)
        if callable(reset_states):
            reset_states()
        self._numpy = numpy
        self._torch = torch
        self._model = model
        self._samples: deque[float] = deque()

    def process_frame(self, frame: bytes) -> bool | None:
        if len(frame) != VoiceActivityDetector.FRAME_BYTES:
            raise ValueError("audio frame must be 20 ms of 16 kHz mono 16-bit PCM")
        samples = self._numpy.frombuffer(frame, dtype="<i2").astype(
            self._numpy.float32
        )
        self._samples.extend((samples / 32768.0).tolist())
        if len(self._samples) < self.MODEL_CHUNK_SAMPLES:
            return None

        chunk = self._numpy.fromiter(
            (self._samples.popleft() for _ in range(self.MODEL_CHUNK_SAMPLES)),
            dtype=self._numpy.float32,
            count=self.MODEL_CHUNK_SAMPLES,
        )
        probability = self._model(
            self._torch.from_numpy(chunk),
            sr=self.MODEL_SAMPLE_RATE,
        )
        score = float(probability.item())
        return score >= self.SPEECH_PROBABILITY_THRESHOLD


@dataclass(frozen=True, slots=True)
class TurnToken:
    turn_id: str
    generation: int
    cancellation: threading.Event = field(compare=False, repr=False)


@dataclass(frozen=True, slots=True)
class ActivityEvent:
    activity: VoiceActivity
    observed_at: datetime
    frame_index: int


class VoiceActivityDetector:
    """Confirm WebRTC speech candidates before emitting turn activity events."""

    SAMPLE_RATE = 16_000
    FRAME_MILLISECONDS = 20
    FRAME_BYTES = SAMPLE_RATE * FRAME_MILLISECONDS // 1000 * 2
    END_SILENCE_FRAMES = 25
    CONFIRMATION_WINDOW_FRAMES = 10
    CONFIRMATION_MAX_AGE_FRAMES = 5

    def __init__(
        self,
        *,
        mode: int = 2,
        start_speech_frames: int = 3,
        vad: VadEngine | None = None,
        confirmer: SpeechConfirmer | None = None,
    ) -> None:
        if mode not in range(4):
            raise ValueError("VAD mode must be between 0 and 3")
        if start_speech_frames < 1:
            raise ValueError("start_speech_frames must be positive")
        if vad is None:
            import webrtcvad

            vad = webrtcvad.Vad(mode)
        self._vad = vad
        self._confirmer = confirmer
        self._start_speech_frames = start_speech_frames
        self._frame_index = 0
        self._pending_speech_frames = 0
        self._candidate_pending_frames: int | None = None
        self._confirmed_speech_frame: int | None = None
        self._active = False
        self._silence_frames = 0

    def process_frame(self, frame: bytes) -> ActivityEvent | None:
        if len(frame) != self.FRAME_BYTES:
            raise ValueError("audio frame must be 20 ms of 16 kHz mono 16-bit PCM")
        self._frame_index += 1
        is_speech = self._vad.is_speech(frame, self.SAMPLE_RATE)
        confirmation = (
            self._confirmer.process_frame(frame) if self._confirmer is not None else None
        )
        if confirmation is True:
            self._confirmed_speech_frame = self._frame_index
        elif confirmation is False:
            self._confirmed_speech_frame = None

        if not self._active:
            if not is_speech:
                if self._candidate_pending_frames is None:
                    self._pending_speech_frames = 0
            else:
                self._pending_speech_frames += 1

            if (
                self._candidate_pending_frames is None
                and self._pending_speech_frames >= self._start_speech_frames
            ):
                self._candidate_pending_frames = 0

            if self._candidate_pending_frames is not None:
                if self._confirmer is None or self._confirmation_is_recent():
                    return self._start_speech()
                self._candidate_pending_frames += 1
                if self._candidate_pending_frames >= self.CONFIRMATION_WINDOW_FRAMES:
                    self._candidate_pending_frames = None
                    self._pending_speech_frames = 0
                return None
            return None

        if is_speech:
            self._silence_frames = 0
            return None

        self._silence_frames += 1
        if self._silence_frames < self.END_SILENCE_FRAMES:
            return None

        self._active = False
        self._pending_speech_frames = 0
        self._candidate_pending_frames = None
        self._confirmed_speech_frame = None
        self._silence_frames = 0
        return ActivityEvent(
            VoiceActivity.SPEECH_ENDED,
            datetime.now(UTC),
            self._frame_index,
        )

    def _confirmation_is_recent(self) -> bool:
        return (
            self._confirmed_speech_frame is not None
            and self._frame_index - self._confirmed_speech_frame
            <= self.CONFIRMATION_MAX_AGE_FRAMES
        )

    def _start_speech(self) -> ActivityEvent:
        self._active = True
        self._pending_speech_frames = 0
        self._candidate_pending_frames = None
        self._silence_frames = 0
        return ActivityEvent(
            VoiceActivity.SPEECH_STARTED,
            datetime.now(UTC),
            self._frame_index,
        )


def iter_pcm_frames(audio_path: Path) -> Iterator[bytes]:
    """Yield 20 ms PCM frames from supported microphone-replay WAV input."""

    with wave.open(str(audio_path), "rb") as wav:
        if (
            wav.getcomptype() != "NONE"
            or wav.getframerate() != VoiceActivityDetector.SAMPLE_RATE
            or wav.getnchannels() != 1
            or wav.getsampwidth() != 2
        ):
            raise ValueError("VAD input must be mono 16-bit 16 kHz PCM WAV")
        frame_size = (
            VoiceActivityDetector.FRAME_BYTES
            // (wav.getnchannels() * wav.getsampwidth())
        )
        while frame := wav.readframes(frame_size):
            if len(frame) != VoiceActivityDetector.FRAME_BYTES:
                break
            yield frame


class WindowsWavePlayback:
    """Play WAV through the Windows audio device and support immediate purge."""

    def __init__(self) -> None:
        import winsound

        self._winsound = winsound

    def start(self, audio_path: Path) -> None:
        if not audio_path.is_file():
            raise FileNotFoundError("playback_audio_not_found")
        self._winsound.PlaySound(
            str(audio_path),
            self._winsound.SND_FILENAME | self._winsound.SND_ASYNC,
        )

    def cancel(self) -> None:
        self._winsound.PlaySound(None, self._winsound.SND_PURGE)

    def wait(self, duration_seconds: float, *, poll_seconds: float = 0.02) -> None:
        deadline = time.monotonic() + duration_seconds
        while time.monotonic() < deadline:
            time.sleep(poll_seconds)

    def stop(self) -> None:
        self.cancel()


class VoiceTurnCoordinator:
    """Serialize voice-turn ownership and reject interrupted or duplicate results."""

    def __init__(self, *, logger: logging.Logger | None = None) -> None:
        self._logger = logger or logging.getLogger("agentic_support.voice_turns")
        self._lock = threading.Lock()
        self._generation = 0
        self._current: TurnToken | None = None
        self._state: TurnState | None = None
        self._result_delivered = False
        self._cancel_playback: Callable[[], None] | None = None

    def start_turn(self) -> TurnToken:
        with self._lock:
            if self._state not in (
                None,
                TurnState.INTERRUPTED,
                TurnState.COMPLETED,
                TurnState.FAILED,
            ):
                raise RuntimeError("a voice turn is already active")
            self._generation += 1
            token = TurnToken(
                turn_id=f"turn-{self._generation:04d}",
                generation=self._generation,
                cancellation=threading.Event(),
            )
            self._current = token
            self._state = TurnState.PROCESSING
            self._result_delivered = False
            self._cancel_playback = None
        self._logger.info(
            "voice_turn_started",
            extra={
                "event": "voice_turn_started",
                "fields": {"turn_id": token.turn_id, "generation": token.generation},
            },
        )
        return token

    def result_ready(self, token: TurnToken) -> bool:
        with self._lock:
            if (
                token != self._current
                or self._state is not TurnState.PROCESSING
                or self._result_delivered
            ):
                self._log_discard(token)
                return False
            self._result_delivered = True
            return True

    def start_playback(
        self,
        token: TurnToken,
        cancel_playback: Callable[[], None],
    ) -> bool:
        with self._lock:
            if (
                token != self._current
                or self._state is not TurnState.PROCESSING
                or not self._result_delivered
            ):
                self._log_discard(token)
                return False
            self._state = TurnState.SPEAKING
            self._cancel_playback = cancel_playback
        self._logger.info(
            "voice_playback_started",
            extra={
                "event": "voice_playback_started",
                "fields": {"turn_id": token.turn_id},
            },
        )
        return True

    def interrupt(self, token: TurnToken, *, reason: str) -> bool:
        with self._lock:
            if token != self._current or self._state is not TurnState.SPEAKING:
                self._log_discard(token)
                return False
            self._state = TurnState.INTERRUPTED
            token.cancellation.set()
            cancel_playback = self._cancel_playback
            self._cancel_playback = None
        if cancel_playback is None:
            raise RuntimeError("speaking turn has no playback cancellation callback")
        cancel_playback()
        self._logger.info(
            "voice_playback_cancelled",
            extra={
                "event": "voice_playback_cancelled",
                "fields": {
                    "turn_id": token.turn_id,
                    "reason": reason,
                    "cancelled": True,
                },
            },
        )
        return True

    def complete(self, token: TurnToken) -> bool:
        with self._lock:
            if (
                token != self._current
                or self._state is not TurnState.SPEAKING
                or not self._result_delivered
            ):
                self._log_discard(token)
                return False
            self._state = TurnState.COMPLETED
            self._cancel_playback = None
        self._logger.info(
            "voice_turn_completed",
            extra={
                "event": "voice_turn_completed",
                "fields": {"turn_id": token.turn_id},
            },
        )
        return True

    def fail(self, token: TurnToken, *, reason: str) -> bool:
        with self._lock:
            if token != self._current or self._state in (
                TurnState.INTERRUPTED,
                TurnState.COMPLETED,
                TurnState.FAILED,
            ):
                self._log_discard(token)
                return False
            self._state = TurnState.FAILED
            self._cancel_playback = None
        self._logger.warning(
            "voice_turn_failed",
            extra={
                "event": "voice_turn_failed",
                "fields": {"turn_id": token.turn_id, "reason": reason},
            },
        )
        return True

    def state_for(self, token: TurnToken) -> TurnState | None:
        with self._lock:
            return self._state if token == self._current else None

    def _log_discard(self, token: TurnToken) -> None:
        self._logger.info(
            "voice_stale_or_duplicate_result_discarded",
            extra={
                "event": "voice_stale_or_duplicate_result_discarded",
                "fields": {"turn_id": token.turn_id},
            },
        )
