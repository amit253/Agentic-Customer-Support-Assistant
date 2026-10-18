# Step 7 Voice Baseline

> **Point-in-time record.** This document records the state at the time it was written and is kept unchanged as history. Current results: `README.md`, `docs/evaluation.md`, `docs/voice-coordination.md` ("Final measured runs"), and `docs/requirements-matrix.md` ("Final status").

Status: Step 7 acceptance is met. Both required Step 7 user recordings are
format-validated. A live Groq STT -> shared support service -> local Windows
TTS run handled the normal order-status request and created a playable WAV
response. The first recorded return-eligibility attempt failed closed after
the live classifier rejected its request; a later Step 8 rerun succeeded and
is documented in the Step 8 evidence. No synthetic input is claimed as
assignment evidence.

## Pipeline

```text
recorded 16 kHz mono 16-bit WAV
  -> Groq Whisper-compatible STT
  -> shared SupportService(channel="voice")
  -> Windows System.Speech WAV output
```

The STT and TTS adapters are provider interfaces, so keyless tests inject fake
providers. The live service uses the configured Groq STT model:

- `GROQ_STT_MODEL=whisper-large-v3-turbo`;

Windows' built-in `System.Speech` synthesizer is used for TTS so playback does
not depend on a separate provider account or terms acceptance. The Groq TTS
adapter remains available for explicit use; this account's live request
returned `model_terms_required` for `canopylabs/orpheus-v1-english`.

## Audio contract

Input clips must be WAV/PCM, mono, 16-bit, and 16,000 Hz. The validator checks
file existence, size, compression, channels, sample width, sample rate, and
non-empty frames before STT.

TTS output is inspected as a playable PCM WAV but may use the provider's output
sample rate.

## Recorded Step 7 input clips

The user recorded the required normal order-status and return-eligibility clips
as WAV/PCM, mono, 16-bit, 16,000 Hz. Both entries are marked `recorded` in
`audio/manifest.json`; one optional pace/accent clip remains pending.

Groq Whisper removes punctuation from spoken order IDs, so the STT adapter
restores the Northstar order-ID separators only when the check digit validates.
Invalid check digits remain unchanged and fail through the existing safety
checks.

The manifest validator and voice tests were run from the repository root:

```text
$env:PYTHONPATH='src'; & 'C:\Users\ADMIN\AppData\Local\Python\pythoncore-3.14-64\python.exe' scripts/validate_audio_manifest.py
clip_count=6, error_count=0, pending_count=1, recorded_count=5

$env:PYTHONPATH='src'; & 'C:\Users\ADMIN\AppData\Local\Python\pythoncore-3.14-64\python.exe' -m pytest tests/test_voice.py -q
10 passed

$env:PYTHONPATH='src'; & 'C:\Users\ADMIN\AppData\Local\Python\pythoncore-3.14-64\python.exe' -m pytest -q
89 passed, 2 skipped, 2 warnings
```

The normal-order clip transcribed as `Where is order NS2640068?`. The adapter
restored the validated ID to `NS-26-4006-8`, enabling the order-status handler
and read-only order tool. The live response was:
`Order NS-26-4006-8 status: in_transit. Estimated delivery: 2026-10-22.`
The complete run result is `recordings/step7-normal-order-run.json`; its
playable local TTS response is `recordings/step7-normal-order-response.wav`
(mono, 16-bit PCM, 22,050 Hz).

The recorded return-eligibility clip transcribed as
`Can I return order NS-26-2044-8?`, but the live intent classifier returned
`classifier_failure_or_invalid_output`. The voice pipeline safely generated
its failed-closed response rather than claiming a policy answer. This initial
attempt is captured in `recordings/step7-return-eligibility-run.json` and
`recordings/step7-return-eligibility-response.wav`. The later successful
recorded-audio return-eligibility run is
`recordings/step8-return_eligibility-run.json`.

The successful normal-turn command and result were:

```powershell
$env:PYTHONPATH='src'
& 'C:\Users\ADMIN\AppData\Local\Python\pythoncore-3.14-64\python.exe' scripts/run_voice_baseline.py audio/normal_order_status.wav --output recordings/step7-normal-order-response.wav --trace-id step7-normal-order-20261017 | Tee-Object -FilePath recordings/step7-normal-order-run.json
```

Result: `status=ok`, `support_status=ok`, transcript
`Where is order NS-26-4006-8?`, order status `in_transit`, estimated delivery
`2026-10-22`, and playable output at 22,050 Hz mono 16-bit PCM. The run JSON
was checked for the configured Groq key values; none appeared in the evidence.

The current default `python` resolves to Python 3.12, where the Groq SDK and
`python-dotenv` are not installed. The successful live run used the workspace
Python 3.14 interpreter with `PYTHONPATH=src`; the project virtual environment
must be installed using the Local setup instructions before its `python`
command can run this pipeline.

For reproducibility, after activating an installed project environment and
configuring Groq credentials locally, run:

```powershell
$env:PYTHONPATH = "src"
python scripts/run_voice_baseline.py audio/normal_order_status.wav
```

The command creates playable WAV output and prints the trace, transcript,
support response, statuses, paths, and audio metadata. Review generated output
and logs in `recordings/` before committing or sharing them.

## Final live verification

On 2026-10-18, the current local `.env` was used without printing its
credential. The normal order clip completed with trace
`final-step7-20261018`, transcript `Where is order NS-26-4006-8?`, the
authorized `get_order_status` tool, and a playable WAV at
`recordings/step7-final-normal-response.wav`. The return clip completed with
trace `final-step7-return-20261018`, the `check_return_eligibility` tool, and a
playable WAV at `recordings/step7-final-return-response.wav`. Both run records
contain fictional data only and are stored beside the response audio.
