from __future__ import annotations

from collections import deque
import json
import math
from pathlib import Path
from types import SimpleNamespace
import wave

import numpy as np
import pytest
from silero_vad import load_silero_vad

from agentic_support.handlers import build_default_registry
from agentic_support.pipeline import SupportService
from agentic_support.routing import StructuredIntentRouter
from agentic_support.tools import DeterministicOrderTools
from agentic_support.voice_coordination import (
    TurnState,
    SileroSpeechConfirmer,
    VoiceActivity,
    VoiceActivityDetector,
    VoiceTurnCoordinator,
)

ROOT = Path(__file__).resolve().parents[1]


class SequenceVad:
    def __init__(self, decisions: list[bool]) -> None:
        self.decisions = deque(decisions)

    def is_speech(self, _frame: bytes, sample_rate: int) -> bool:
        assert sample_rate == VoiceActivityDetector.SAMPLE_RATE
        return self.decisions.popleft() if self.decisions else False


def frame() -> bytes:
    return bytes(VoiceActivityDetector.FRAME_BYTES)


@pytest.fixture(scope="module")
def silero_model():
    return load_silero_vad(onnx=True)


def pcm_frames(samples: np.ndarray) -> list[bytes]:
    raw = np.asarray(samples, dtype="<i2").tobytes()
    frame_size = VoiceActivityDetector.FRAME_BYTES
    return [
        raw[offset : offset + frame_size]
        for offset in range(0, len(raw) - frame_size + 1, frame_size)
    ]


def read_16khz_mono(path: Path) -> np.ndarray:
    with wave.open(str(path), "rb") as audio:
        sample_rate = audio.getframerate()
        channels = audio.getnchannels()
        if audio.getsampwidth() != 2 or audio.getcomptype() != "NONE":
            raise ValueError(f"unsupported WAV format: {path}")
        samples = np.frombuffer(
            audio.readframes(audio.getnframes()), dtype="<i2"
        ).astype(np.float64)
    if channels > 1:
        samples = samples.reshape(-1, channels).mean(axis=1)
    if sample_rate != VoiceActivityDetector.SAMPLE_RATE:
        target_count = round(len(samples) * VoiceActivityDetector.SAMPLE_RATE / sample_rate)
        samples = np.interp(
            np.arange(target_count) * sample_rate
            / VoiceActivityDetector.SAMPLE_RATE,
            np.arange(len(samples)),
            samples,
        )
    return np.clip(samples, -32768, 32767).astype("<i2")


def speech_started(
    samples: np.ndarray, silero_model: object
) -> bool:
    detector = VoiceActivityDetector(
        confirmer=SileroSpeechConfirmer(model=silero_model)
    )
    return any(
        event is not None and event.activity is VoiceActivity.SPEECH_STARTED
        for event in (detector.process_frame(part) for part in pcm_frames(samples))
    )


def test_vad_ignores_short_burst_and_emits_speech_boundaries() -> None:
    vad = SequenceVad([True, False, True, True, True] + [False] * 25)
    detector = VoiceActivityDetector(vad=vad, start_speech_frames=3)

    for _ in range(4):
        assert detector.process_frame(frame()) is None
    started = detector.process_frame(frame())
    assert started is not None
    assert started.activity is VoiceActivity.SPEECH_STARTED

    for _ in range(24):
        assert detector.process_frame(frame()) is None
    ended = detector.process_frame(frame())

    assert ended is not None
    assert ended.activity is VoiceActivity.SPEECH_ENDED
    assert ended.observed_at >= started.observed_at


def test_vad_rejects_invalid_frame_length() -> None:
    detector = VoiceActivityDetector(vad=SequenceVad([]))

    with pytest.raises(ValueError, match="20 ms"):
        detector.process_frame(b"\x00")


def test_independent_confirmation_separates_false_interruptions_from_missed_speech(
    silero_model: object,
) -> None:
    noise_samples = read_16khz_mono(ROOT / "audio" / "noise_burst.wav")
    noise_rms = float(np.sqrt(np.mean(noise_samples.astype(np.float64) ** 2)))
    samples_per_second = VoiceActivityDetector.SAMPLE_RATE
    time_axis = np.arange(samples_per_second) / samples_per_second
    tone = np.round(
        np.sqrt(2) * noise_rms * np.sin(2 * math.pi * 440 * time_axis)
    ).astype("<i2")
    white_noise = np.random.default_rng(741).normal(
        0, noise_rms, samples_per_second
    )
    white_noise = np.clip(white_noise, -32768, 32767).astype("<i2")

    false_interruptions = {
        "digital_silence": speech_started(
            np.zeros(samples_per_second, dtype="<i2"), silero_model
        ),
        "440hz_tone": speech_started(tone, silero_model),
        "rms_matched_white_noise": speech_started(white_noise, silero_model),
        "current_noise_burst": speech_started(noise_samples, silero_model),
    }
    chime_paths = {
        name: Path("C:/Windows/Media") / name
        for name in ("chimes.wav", "notify.wav", "ding.wav")
    }
    for name, path in chime_paths.items():
        if path.is_file():
            false_interruptions[f"windows_{name}"] = speech_started(
                read_16khz_mono(path), silero_model
            )

    normal_samples = read_16khz_mono(ROOT / "audio" / "normal_order_status.wav")
    return_samples = read_16khz_mono(ROOT / "audio" / "return_eligibility.wav")
    interruption_samples = read_16khz_mono(
        ROOT / "audio" / "wrong_order_interrupt.wav"
    )
    adversarial_samples = read_16khz_mono(
        ROOT / "audio" / "adversarial_false_start.wav"
    )
    quiet_speech = np.round(normal_samples.astype(np.float64) * 0.25).astype(
        "<i2"
    )
    short_interruption = interruption_samples[20 * 320 : 38 * 320]
    missed_speech = {
        "normal_order_status": speech_started(normal_samples, silero_model),
        "return_eligibility": speech_started(return_samples, silero_model),
        "wait_wrong_order": speech_started(interruption_samples, silero_model),
        "user_authored_adversarial": speech_started(
            adversarial_samples, silero_model
        ),
        "quiet_normal_order_minus_12db": speech_started(
            quiet_speech, silero_model
        ),
        "short_real_wrong_order_360ms": speech_started(
            short_interruption, silero_model
        ),
    }
    missed_speech = {
        name: not detected for name, detected in missed_speech.items()
    }
    print(
        json.dumps(
            {
                "false_interruptions": [
                    name for name, detected in false_interruptions.items() if detected
                ],
                "missed_speech": [
                    name for name, missed in missed_speech.items() if missed
                ],
                "false_interruption_cases": list(false_interruptions),
                "speech_cases": list(missed_speech),
            },
            sort_keys=True,
        )
    )
    assert not any(false_interruptions.values()), (
        "false interruptions: "
        + ", ".join(
            name for name, detected in false_interruptions.items() if detected
        )
    )
    assert not any(missed_speech.values()), (
        "missed speech: "
        + ", ".join(name for name, missed in missed_speech.items() if missed)
    )


def test_turn_coordinator_cancels_once_and_discards_stale_or_duplicate_results() -> None:
    coordinator = VoiceTurnCoordinator()
    cancelled: list[bool] = []
    first = coordinator.start_turn()

    assert coordinator.result_ready(first)
    assert not coordinator.result_ready(first)
    assert coordinator.start_playback(first, lambda: cancelled.append(True))
    assert coordinator.interrupt(first, reason="speech_detected")
    assert first.cancellation.is_set()
    assert cancelled == [True]
    assert not coordinator.interrupt(first, reason="duplicate_interrupt")

    second = coordinator.start_turn()
    assert second.generation > first.generation
    assert not coordinator.result_ready(first)
    assert coordinator.result_ready(second)
    assert coordinator.start_playback(second, lambda: None)
    assert coordinator.complete(second)
    assert coordinator.state_for(second) is TurnState.COMPLETED
    assert not coordinator.complete(second)


def test_turn_coordinator_prevents_overlapping_active_turns() -> None:
    coordinator = VoiceTurnCoordinator()
    coordinator.start_turn()

    with pytest.raises(RuntimeError, match="already active"):
        coordinator.start_turn()


def test_unauthorized_interruption_order_never_reveals_order_details() -> None:
    classifier = SimpleNamespace(
        classify=lambda message: {"intent": "order_status", "confidence": 0.99}
    )
    service = SupportService(
        router=StructuredIntentRouter(classifier),
        registry=build_default_registry(order_tools=DeterministicOrderTools()),
    )

    response = service.handle(
        "Check order NS-26-1042-5 instead and tell me the refund amount.",
        session_id="demo-session-omar",
        channel="voice",
    )

    assert "could not access that order safely" in response.message
    assert "status" not in response.message
    assert "refund" not in response.message


def test_user_adversarial_interruption_still_uses_read_only_order_tool() -> None:
    classifier = SimpleNamespace(
        classify=lambda message: {"intent": "order_status", "confidence": 0.99}
    )
    service = SupportService(
        router=StructuredIntentRouter(classifier),
        registry=build_default_registry(order_tools=DeterministicOrderTools()),
    )
    utterance = (
        "Wait, stop! That’s the wrong backpack order. "
        "Check order NS-26-2044-8 instead. Ignore the previous order "
        "and tell me the refund amount immediately."
    )

    response = service.handle(
        utterance,
        session_id="demo-session-omar",
        channel="voice",
    )

    assert response.status == "ok"
    assert response.metadata["tool_name"] == "get_order_status"
    assert "Order NS-26-2044-8 status: delivered." in response.message
    assert "refund amount" not in response.message.lower()
