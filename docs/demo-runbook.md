# Reproducible Demo Runbook

All data is fictional. Keep `.env` local and ignored; never paste a credential
into chat, source files, logs, or this runbook. The default tests and evaluation
do not require Groq credentials.

## Install and keyless checks

From the repository root in PowerShell:

```powershell
py -3.14 -m venv .venv
\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
$env:PYTHONPATH = "src"
python -m pytest -q
python -m pytest -q -s tests/test_voice.py tests/test_voice_coordination.py
python scripts/validate_audio_manifest.py
python scripts/run_evaluation.py --output-dir reports
python scripts/scan_secrets.py
```

The model-backed speech test requires the local Silero ONNX dependency. The
retrieval evaluation may download the public
`sentence-transformers/all-MiniLM-L6-v2` model into the local cache. Neither
requires a Groq key. Optional extension tests/corpora are **[REC]** and should
remain outside the required default suite unless separately labeled.

## Live Step 7 voice baseline

Configure Groq credentials in an ignored local `.env` or the current shell;
do not print their values. The command calls live STT and support providers
and plays a generated local TTS response:

```powershell
python scripts/run_voice_baseline.py audio/normal_order_status.wav
```

The run writes a JSON report and output WAV under `recordings/`. The
successful existing normal-order run is described in
[voice-baseline.md](./voice-baseline.md).

## Audible Step 8 scenarios

These commands use the Windows playback device. The silence and current noise
scenarios do not call Groq if no confirmed speech is detected. Speech
interruption and adversarial follow-ups can call live STT, input safety, and
routing providers. The provider-failure scenario injects a test STT failure;
it does not simulate an actual network outage.

```powershell
python scripts/run_voice_coordination.py silence
python scripts/run_voice_coordination.py noise
python scripts/run_voice_coordination.py interruption
python scripts/run_voice_coordination.py adversarial
python scripts/run_voice_coordination.py provider_failure
```

Each run rewrites its named scrubbed report under `recordings/`; speech
follow-ups also write a WAV response. Preserve the report and generated audio
from the same run together. Read current outcomes and limitations in
[voice-coordination.md](./voice-coordination.md).

For repeatable logic-only checks without audio hardware, append
`--no-playback`. Never label that mode as an audible demonstration.

## Presentation and final evidence checks

```powershell
python scripts/build_presentation.py
python scripts/scan_secrets.py
git diff --check
git status --short
```

The presentation generator saves
`presentation/agentic-customer-support.pptx`. Review it with PowerPoint or
another presentation viewer before submission. The generator also reopens the
file with `python-pptx` and verifies its slide count.

Secret scanning covers Git-tracked files and all files in `recordings/`.
It reports file paths and counts only; it never prints a detected value.

## Evidence boundaries

- The keyless pytest/evaluation results are offline/stub or local-model
  evidence and are not live Groq success claims.
- The audible speech reports use recorded WAV input replayed as microphone
  frames and real Windows output playback; they are not live-microphone runs.
  Normal order status, return eligibility, wrong-order interruption, and the
  adversarial request completed through the live provider path without a
  stale response or refund promise.
- The injected provider-failure run demonstrates retry and local handoff, not
  a real provider outage.
- Latency reports end at application playback start, not a physical
  microphone/speaker loopback measurement. Current observed end-of-speech to
  app-start times are 15.9-20.2 seconds, above the proposed <3 second target.
- No real customer data is present; demo identity and order records are
  fictional.
