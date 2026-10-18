# Live Defense Notes

These notes describe the current repository, not a rehearsal. No unaided
extension exercise has been performed.

## Explain the request path

`SupportService.handle()` in `src/agentic_support/pipeline.py` is the shared
text/voice boundary. It validates and normalizes input, calls
`InputGuard.check()`, then routes accepted input through
`StructuredIntentRouter.route()` to one of three handlers. Order tools are
read-only and check the server-side fictional session/customer mapping.
`OutputClaimGuard` checks the final response against facts supplied by
retrieval or verified tools. Return eligibility is not a refund approval.

## Explain speech interruption

`VoiceActivityDetector` in `src/agentic_support/voice_coordination.py` uses
WebRTC VAD to propose onset and independent local Silero ONNX inference to
confirm it. `VoiceTurnCoordinator` owns the current turn token, cancels
playback, and rejects stale results. `VoicePipeline` in
`src/agentic_support/voice.py` handles transcription, the shared service, and
TTS. `scripts/run_voice_coordination.py` feeds recorded WAV frames to the
detector and plays output using Windows audio; it does not capture live
microphone input.

## Explain the live provider corrections

`GroqSpeechToText` forces English for the current English-only recording set.
If the primary transcript contains replacement characters or non-ASCII
alphabetic text, it retries with `whisper-large-v3`; if the result is still
unreadable, it raises a safe provider error. Multilingual behavior is
unsupported and unverified.

`GroqSafetyClassifier` and `GroqStructuredClassifier` first request strict
JSON Schema output. Only HTTP 400 `json_validate_failed` triggers one retry in
JSON-object mode. `InputGuard` and the router then validate exact keys and
field types/ranges locally. Other provider errors do not trigger this
fallback. Tests use fake clients and require no credentials.

## Reproducible evidence

The 2026-10-18 audible reports demonstrate silence, the current noise clip,
normal order status, return eligibility, “Wait, wrong order,” the original
adversarial utterance, and an injected STT-failure handoff. Four audible
speech scenarios completed through live STT/support calls and discarded the
superseded turn. The adversarial response escalated; it did not promise a
refund. The provider failure used an injected provider, not a real Groq outage.

The ONNX detector corpus reported zero false interruptions in seven
non-speech controls and zero missed speech in six speech cases. This result
applies only to that corpus. Speech cancellation-call latency was
105.217-117.732 ms. End-of-speech to application playback start was
15,886.752-20,168.889 ms; the proposed sub-three-second target was not met.
No acoustic loopback measurement was available, so these values must not be
described as first-acoustic-sample latency.

## Honest limitations

- No live-microphone capture test or physical audio loopback timing was run.
- Groq outage recovery is injected only; there is no circuit breaker or
  alternate-provider failover.
- The English transcription fallback is not a multilingual strategy.
- The two reported red-team defects were reproduced before fixes and are now
  regression-tested. The report should not claim two currently unfixed,
  reproduced vulnerabilities.
- No unaided live-defense practice has been performed. Practice one small,
  reversible change without AI assistance before the defense if time permits.
