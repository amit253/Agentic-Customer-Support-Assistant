"""Run one real-time, file-backed Step 8 turn-taking scenario."""

from __future__ import annotations

import argparse
import json
import math
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Callable

from agentic_support.config import Settings
from agentic_support.pipeline import build_live_support_service
from agentic_support.voice import (
    GroqSpeechToText,
    SpeechTranscript,
    VoicePipeline,
    VoiceProviderError,
    WindowsSpeechSynthesizer,
    inspect_wav,
)
from agentic_support.voice_coordination import (
    ActivityEvent,
    SileroSpeechConfirmer,
    TurnToken,
    VoiceActivity,
    VoiceActivityDetector,
    VoiceTurnCoordinator,
    WindowsWavePlayback,
    iter_pcm_frames,
)


ROOT = Path(__file__).resolve().parents[1]
RESPONSE_AUDIO = ROOT / "recordings" / "step7-normal-order-response.wav"
SCENARIOS = {
    "silence": None,
    "noise": ROOT / "audio" / "noise_burst.wav",
    "normal_speech": ROOT / "audio" / "normal_order_status.wav",
    "return_eligibility": ROOT / "audio" / "return_eligibility.wav",
    "interruption": ROOT / "audio" / "wrong_order_interrupt.wav",
    "adversarial": ROOT / "audio" / "adversarial_false_start.wav",
}
FRAME_SECONDS = VoiceActivityDetector.FRAME_MILLISECONDS / 1000
SILENCE_FRAME = bytes(VoiceActivityDetector.FRAME_BYTES)


class NullPlayback:
    """Advance a timed replay without sending sound to the local device."""

    def start(self, audio_path: Path) -> None:
        if not audio_path.is_file():
            raise FileNotFoundError("playback_audio_not_found")
        return None

    def cancel(self) -> None:
        return None

    def wait(self, duration_seconds: float) -> None:
        if duration_seconds < 0:
            raise ValueError("playback duration cannot be negative")
        return None

    def stop(self) -> None:
        return None


class SimulatedProviderFailure:
    def __init__(self) -> None:
        self.attempts = 0

    def transcribe(self, audio_path: Path) -> SpeechTranscript:
        if not audio_path.is_file():
            raise FileNotFoundError("stt_input_audio_not_found")
        self.attempts += 1
        raise VoiceProviderError("simulated_stt_provider_failure")


def _wait_until(deadline: float) -> None:
    delay = deadline - time.monotonic()
    if delay > 0:
        time.sleep(delay)


def _process_monitor_frame(
    detector: VoiceActivityDetector,
    frame: bytes,
    events: list[dict[str, object]],
) -> ActivityEvent | None:
    event = detector.process_frame(frame)
    if event is not None:
        events.append(
            {
                "event": event.activity.value,
                "observed_at": event.observed_at.isoformat(),
                "frame_index": event.frame_index,
            }
        )
    return event


def _monitor_playback(
    *,
    coordinator: VoiceTurnCoordinator,
    token: TurnToken,
    playback: WindowsWavePlayback | NullPlayback,
    audible_playback: bool,
    playback_audio: Path,
    input_audio: Path | None,
    on_speech_end: Callable[[ActivityEvent], None],
    events: list[dict[str, object]],
) -> tuple[bool, ActivityEvent | None, float | None]:
    metadata = inspect_wav(playback_audio)
    detector = VoiceActivityDetector(confirmer=SileroSpeechConfirmer())
    source = iter_pcm_frames(input_audio) if input_audio is not None else iter(())
    input_started_at = time.monotonic() + 0.8
    playback_deadline = time.monotonic() + metadata.duration_seconds
    next_frame_at = time.monotonic()
    cancel_requested = False
    interruption_latency_ms: float | None = None
    speech_end: ActivityEvent | None = None
    if not coordinator.start_playback(token, playback.cancel):
        raise RuntimeError("coordinator_rejected_playback_start")
    playback.start(playback_audio)
    playback_started_at = datetime.now(UTC)
    events.append(
        {
            "event": (
                "assistant_playback_started"
                if audible_playback
                else "assistant_playback_simulated"
            ),
            "turn_id": token.turn_id,
            "observed_at": playback_started_at.isoformat(),
            "audio_path": str(playback_audio.relative_to(ROOT)),
            "playback_device_used": audible_playback,
        }
    )

    frame_limit = math.ceil(metadata.duration_seconds / FRAME_SECONDS)
    frames_processed = 0
    while (
        time.monotonic() < playback_deadline
        or (cancel_requested and speech_end is None)
    ):
        _wait_until(next_frame_at)
        now = time.monotonic()
        if input_audio is not None and now >= input_started_at:
            frame = next(source, SILENCE_FRAME)
        else:
            frame = SILENCE_FRAME
        event = _process_monitor_frame(detector, frame, events)
        frames_processed += 1
        next_frame_at += FRAME_SECONDS

        if (
            event is not None
            and event.activity is VoiceActivity.SPEECH_STARTED
            and not cancel_requested
        ):
            speech_detected_monotonic = time.monotonic()
            cancel_requested = coordinator.interrupt(
                token, reason="sustained_user_speech_detected"
            )
            if cancel_requested:
                interruption_latency_ms = (
                    time.monotonic() - speech_detected_monotonic
                ) * 1000
            events.append(
                {
                    "event": (
                        "barge_in_cancelled_playback"
                        if audible_playback
                        else "barge_in_cancelled_simulated_playback"
                    ),
                    "turn_id": token.turn_id,
                    "observed_at": datetime.now(UTC).isoformat(),
                    "cancelled": cancel_requested,
                    "speech_detection_to_cancel_ms": interruption_latency_ms,
                }
            )
            if not cancel_requested:
                break

        if event is not None and event.activity is VoiceActivity.SPEECH_ENDED:
            speech_end = event
            on_speech_end(event)
            break

        if not cancel_requested and frames_processed >= frame_limit:
            break

    if not cancel_requested:
        playback.stop()
        if not coordinator.complete(token):
            raise RuntimeError("coordinator_rejected_turn_completion")
        events.append(
            {
                "event": (
                    "assistant_playback_completed"
                    if audible_playback
                    else "assistant_playback_simulated_completion"
                ),
                "turn_id": token.turn_id,
                "observed_at": datetime.now(UTC).isoformat(),
                "cancelled": False,
            }
        )
    return cancel_requested, speech_end, interruption_latency_ms


def _pipeline_for(
    settings: Settings, *, failure_demo: bool
) -> tuple[VoicePipeline, SimulatedProviderFailure | None]:
    if failure_demo:
        provider = SimulatedProviderFailure()
        pipeline = VoicePipeline(
            support_service=build_live_support_service(settings),
            stt=provider,
            tts=WindowsSpeechSynthesizer(),
        )
        return pipeline, provider
    return (
        VoicePipeline(
            support_service=build_live_support_service(settings),
            stt=GroqSpeechToText(settings),
            tts=WindowsSpeechSynthesizer(),
        ),
        None,
    )


def _run_scenario(
    scenario: str, *, play_audio: bool, evidence_prefix: str = "step8"
) -> dict[str, object]:
    scenario_started_at = datetime.now(UTC)
    settings = Settings.from_environment()
    coordinator = VoiceTurnCoordinator()
    playback = WindowsWavePlayback() if play_audio else NullPlayback()
    events: list[dict[str, object]] = []
    failure_demo = scenario == "provider_failure"
    input_audio = (
        ROOT / "audio" / "return_eligibility.wav"
        if failure_demo
        else SCENARIOS[scenario]
    )
    if not RESPONSE_AUDIO.is_file():
        raise FileNotFoundError(
            "Step 7 response WAV missing; run the documented Step 7 baseline first"
        )
    if input_audio is not None and not input_audio.is_file():
        raise FileNotFoundError(
            f"record the {scenario} clip at {input_audio.relative_to(ROOT)} first"
        )

    # Build the voice pipeline at call setup, before the caller speaks, as a
    # phone line would. The Step 8 runs built it after end of speech, so their
    # 15.9-20.2 s latency included loading the local models on every turn.
    pipeline, provider = (
        _pipeline_for(settings, failure_demo=failure_demo)
        if input_audio is not None
        else (None, None)
    )
    setup_completed_at = datetime.now(UTC)

    first_token = coordinator.start_turn()
    if not coordinator.result_ready(first_token):
        raise RuntimeError("coordinator_rejected_initial_response")
    ended_events: list[ActivityEvent] = []
    cancelled, _, interruption_latency_ms = _monitor_playback(
        coordinator=coordinator,
        token=first_token,
        playback=playback,
        audible_playback=play_audio,
        playback_audio=RESPONSE_AUDIO,
        input_audio=input_audio,
        on_speech_end=ended_events.append,
        events=events,
    )
    stale_old_result_discarded = False
    handoff_result: dict[str, object] | None = None
    if failure_demo:
        if input_audio is None:
            raise RuntimeError("provider_failure_demo_requires_real_input_audio")
        if not cancelled or not ended_events:
            raise RuntimeError("provider_failure_demo_requires_a_real_interruption")
        followup_token = coordinator.start_turn()
        stale_old_result_discarded = not coordinator.result_ready(first_token)
        if not stale_old_result_discarded:
            raise RuntimeError("coordinator_accepted_superseded_turn_result")
        events.append(
            {
                "event": "stale_result_discarded",
                "turn_id": first_token.turn_id,
                "observed_at": datetime.now(UTC).isoformat(),
            }
        )
        result = pipeline.process(
            input_audio,
            session_id="demo-session-omar",
            end_of_speech_at=ended_events[-1].observed_at,
            output_path=ROOT / "recordings" / f"{evidence_prefix}-provider-failure-handoff.wav",
            trace_id=f"{evidence_prefix}-provider-failure",
        )
        assert isinstance(provider, SimulatedProviderFailure)
        if not coordinator.result_ready(followup_token):
            raise RuntimeError("coordinator_rejected_failure_handoff")
        if result.output_path is None or result.output_audio is None:
            raise RuntimeError("provider_failure_did_not_produce_safe_handoff_audio")
        if not coordinator.start_playback(followup_token, playback.cancel):
            raise RuntimeError("coordinator_rejected_failure_handoff_playback")
        playback.start(Path(result.output_path))
        first_playback_at = datetime.now(UTC) if play_audio else None
        playback.wait(result.output_audio.duration_seconds)
        playback.stop()
        if not coordinator.complete(followup_token):
            raise RuntimeError("coordinator_rejected_failure_handoff_completion")
        handoff_result = {
            "turn_id": followup_token.turn_id,
            "status": result.status,
            "support_status": result.support_status,
            "support_metadata": result.support_metadata,
            "error_code": result.error_code,
            "stt_attempts": provider.attempts,
            "support_message": result.support_message,
            "output_path": result.output_path,
            "end_of_speech_at": ended_events[-1].observed_at.isoformat(),
            "first_audio_at": (
                first_playback_at.isoformat() if first_playback_at else None
            ),
            "end_of_speech_to_first_audio_ms": (
                first_playback_at - ended_events[-1].observed_at
            ).total_seconds()
            * 1000
            if first_playback_at
            else None,
        }
    elif cancelled:
        if input_audio is None or not ended_events:
            raise RuntimeError("barge_in_without_complete_user_utterance")
        child_token = coordinator.start_turn()
        stale_old_result_discarded = not coordinator.result_ready(first_token)
        if not stale_old_result_discarded:
            raise RuntimeError("coordinator_accepted_superseded_turn_result")
        events.append(
            {
                "event": "stale_result_discarded",
                "turn_id": first_token.turn_id,
                "observed_at": datetime.now(UTC).isoformat(),
            }
        )
        result = pipeline.process(
            input_audio,
            session_id="demo-session-omar",
            trace_id=f"{evidence_prefix}-{scenario}",
            end_of_speech_at=ended_events[-1].observed_at,
            output_path=ROOT / "recordings" / f"{evidence_prefix}-{scenario}-response.wav",
        )
        accepted = coordinator.result_ready(child_token)
        if not accepted:
            raise RuntimeError("coordinator_rejected_followup_result")
        if result.output_path is not None:
            if not coordinator.start_playback(child_token, playback.cancel):
                raise RuntimeError("coordinator_rejected_followup_playback")
            playback.start(Path(result.output_path))
            first_playback_at = datetime.now(UTC) if play_audio else None
            playback.wait(result.output_audio.duration_seconds if result.output_audio else 0)
            playback.stop()
            if not coordinator.complete(child_token):
                raise RuntimeError("coordinator_rejected_followup_completion")
        else:
            first_playback_at = None
        handoff_result = {
            "turn_id": child_token.turn_id,
            "status": result.status,
            "support_status": result.support_status,
            "support_intent": result.support_intent,
            "support_handler": result.support_handler,
            "support_metadata": result.support_metadata,
            "transcript": result.transcript,
            "support_message": result.support_message,
            "error_code": result.error_code,
            "stt_attempts": result.stt_attempts,
            "output_path": result.output_path,
            "end_of_speech_at": ended_events[-1].observed_at.isoformat(),
            "first_audio_at": first_playback_at.isoformat()
            if first_playback_at
            else None,
            "end_of_speech_to_first_audio_ms": (
                first_playback_at - ended_events[-1].observed_at
            ).total_seconds()
            * 1000
            if first_playback_at
            else None,
        }

    return {
        "schema_version": "step8-voice-run-v1",
        "scenario": scenario,
        "evidence_type": (
            "recorded_user_audio_replayed_with_simulated_provider_failure"
            if failure_demo
            else "recorded_user_audio_replayed_in_real_time"
            if input_audio is not None
            else "silence_replayed_in_real_time"
        ),
        "playback_device_used": play_audio,
        "started_at": scenario_started_at.isoformat(),
        "pipeline_ready_before_speech_at": setup_completed_at.isoformat(),
        "turn_id": first_token.turn_id,
        "interruption_detected": cancelled,
        "speech_detection_to_cancel_ms": interruption_latency_ms,
        "input_source": "recorded_wav_replayed_as_microphone_frames",
        "old_turn_result_discarded": stale_old_result_discarded,
        "events": events,
        "followup": handoff_result,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "scenario",
        choices=(*SCENARIOS, "provider_failure"),
    )
    parser.add_argument(
        "--evidence-prefix",
        default="step8",
        help="file prefix for recordings/<prefix>-<scenario>-run.json and response audio",
    )
    parser.add_argument(
        "--no-playback",
        action="store_true",
        help="run the timed coordinator without sending audio to the Windows device",
    )
    args = parser.parse_args()
    result = _run_scenario(
        args.scenario,
        play_audio=not args.no_playback,
        evidence_prefix=args.evidence_prefix,
    )
    output_path = ROOT / "recordings" / f"{args.evidence_prefix}-{args.scenario}-run.json"
    output_path.write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    print(f"evidence_path={output_path.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
