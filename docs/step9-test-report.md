# Step 9 Integration and Regression Test Report

**Run date:** 2026-10-18 (local time, Asia/Calcutta)
**Interpreter:** `C:\Users\ADMIN\AppData\Local\Python\pythoncore-3.14-64\python.exe`
**Mode:** keyless automated suite; fake/stub providers are used by tests.

## Automated checks

| Purpose | Exact command | Result |
|---|---|---|
| Full keyless suite | `$env:PYTHONPATH='src'; & 'C:\Users\ADMIN\AppData\Local\Python\pythoncore-3.14-64\python.exe' -m pytest -q` | **62 passed**, 2 third-party deprecation warnings, 19.97 s |
| Guardrail, pipeline, call-path, tools, router | `$env:PYTHONPATH='src'; & 'C:\Users\ADMIN\AppData\Local\Python\pythoncore-3.14-64\python.exe' -m pytest -q tests/test_guardrails.py tests/test_pipeline.py tests/test_step5_call_path.py tests/test_tools.py tests/test_routing.py` | **26 passed**, 0.28 s |
| Voice tests and independent VAD corpus | `$env:PYTHONPATH='src'; & 'C:\Users\ADMIN\AppData\Local\Python\pythoncore-3.14-64\python.exe' -m pytest -q -s tests/test_voice.py tests/test_voice_coordination.py` | **15 passed**, 4.04 s; false interruptions **0**, missed speech **0** in the recorded/synthetic corpus |
| Audio manifest | `$env:PYTHONPATH='src'; & 'C:\Users\ADMIN\AppData\Local\Python\pythoncore-3.14-64\python.exe' scripts/validate_audio_manifest.py` | 6 entries; 0 errors; 5 recorded; 1 optional recording pending |
| Baseline evaluation | `$env:PYTHONPATH='src'; & 'C:\Users\ADMIN\AppData\Local\Python\pythoncore-3.14-64\python.exe' scripts/run_evaluation.py --output-dir reports` | routing accuracy 0.8333; retrieval recall@5 0.7273; input guardrail recall 0.6667; output guardrail recall 1.0; classifier cache hit rate 0.5 |

The full test suite uses no Groq credential. It emitted `SwigPyPacked` and
`SwigPyObject` deprecation warnings from the retrieval dependency stack. The
evaluation used the local Sentence Transformers model; Transformers printed
an expected public Hugging Face Hub unauthenticated-rate-limit warning and an
`embeddings.position_ids` load note. The command completed and wrote
`reports/baseline-evaluation.json` and `reports/baseline-evaluation.md`.

The independently exercised voice corpus includes genuine user recordings
and synthetic controls. The measured detector results are corpus outcomes,
not production accuracy estimates.

## Step 13 A2/A4 follow-up validation

**Run date:** 2026-10-18 (local time, Asia/Calcutta)

| Purpose | Exact command | Result |
|---|---|---|
| Grounded-answer, native-tool, and guardrail regressions | `$env:PYTHONPATH='src'; Remove-Item Env:RUN_LIVE_GROQ_TESTS -ErrorAction SilentlyContinue; & 'C:\Users\ADMIN\AppData\Local\Python\pythoncore-3.14-64\python.exe' -m pytest tests\test_native_llm_paths.py tests\test_step5_call_path.py tests\test_guardrails.py` | **28 passed, 2 skipped**; live-only tests were intentionally gated; 0.38 s |
| Full default keyless suite | `$env:PYTHONPATH='src'; Remove-Item Env:RUN_LIVE_GROQ_TESTS -ErrorAction SilentlyContinue; & 'C:\Users\ADMIN\AppData\Local\Python\pythoncore-3.14-64\python.exe' -m pytest` | **81 passed, 2 skipped**, 2 third-party deprecation warnings, 20.55 s |
| Separate live Groq paths | `$env:PYTHONPATH='src'; $env:RUN_LIVE_GROQ_TESTS='1'; & 'C:\Users\ADMIN\AppData\Local\Python\pythoncore-3.14-64\python.exe' -m pytest -q -m live tests\test_native_llm_paths.py` | **2 passed, 17 deselected**, 2 third-party deprecation warnings, 21.28 s |

The live product check confirmed a nonempty answer, citations limited to
retrieved chunks, and acceptance by the output-claim guard using facts from
those cited chunks. The live order check selected the requested read-only
status function for the exact fictional order ID and executed the local tool
using the verified demo session. The tests deliberately do not print or
persist the generated answer or credentials. These checks exercise the
provider contract, not an independent semantic proof that every natural
language statement is entailed by its cited passages.

## Live-provider evidence (separate from keyless tests)

### Prior reproduced failures and corrections

An earlier audible wrong-order run reached STT but the primary
`whisper-large-v3-turbo` model returned garbled text. A controlled live
transcription with `whisper-large-v3`, English forced, returned
`Wait, wrong order.` The STT adapter now retries a suspect English transcript
with that model and fails closed if the fallback remains unreadable.

Direct safety-classifier calls using the earlier 120-token strict-schema
budget produced HTTP 400 `json_validate_failed`. Increasing the bounded
budget to 300 tokens allowed controlled strict-schema calls. One intervening
full live route still failed closed; its exact provider exception was not
captured, so it is not attributed to a specific cause. The safety and router
adapters now retry JSON-object mode only for HTTP 400
`json_validate_failed`, with exact-key/type/range validation in application
code. Fake-client tests cover both the targeted fallback and the rule that
other provider errors do not trigger it.

### Latest audible runs (2026-10-18 UTC)

These used recorded WAV input replayed as microphone frames and actual
Windows output playback. They used the live Groq STT/support path except for
the explicitly injected provider-failure scenario.

| Scenario | Result | End-of-speech to app playback start |
|---|---|---:|
| Silence | Playback completed, no interruption or follow-up | n/a |
| Noise | Playback completed, no interruption or follow-up | n/a |
| Normal order | Transcript matched; `order_status_handler`; old turn discarded | 19,954.734 ms |
| Return eligibility | Transcript matched; `order_status_handler` called `check_return_eligibility`; old turn discarded | 20,168.889 ms |
| “Wait, wrong order” | Transcript matched; safe human escalation; one STT attempt; old turn discarded | 19,708.175 ms |
| Original adversarial utterance | Transcript retained refund request; safe human escalation; no refund promise; old turn discarded | 19,293.912 ms |
| Injected STT failure | Two failures; safe audible handoff; old turn discarded | 15,886.752 ms |

Reports are stored in `recordings/step8-*-run.json`; the WAV response files
are stored beside them. Confirmed-speech-to-cancellation-call latency ranged
from 105.217 to 128.318 ms. Application playback-start latency is not
first-acoustic-sample latency. No loopback capture was available. The measured
15.9-20.2 second voice response times exceed the proposed <3 second target;
the live runs are evidence of safe handling, not acceptable conversational
latency or an SLO percentile.

## Limitations

- `end_of_speech_to_first_audio_ms` measures the application playback-start
  handoff, not acoustic loopback at the first physical audio sample.
- The provider-failure case is injected; no real Groq outage or live
  microphone capture was demonstrated.
- The optional pace/accent recording remains pending.

## Final keyless validation (2026-10-18)

| Purpose | Exact command | Result |
|---|---|---|
| Focused voice, VAD, safety, and routing regressions | `$env:PYTHONPATH='src'; & 'C:\Users\ADMIN\AppData\Local\Python\pythoncore-3.14-64\python.exe' -m pytest -q -s tests\test_voice.py tests\test_voice_coordination.py tests\test_guardrails.py tests\test_routing.py` | **35 passed in 3.98 s**; false interruptions **0**; missed speech **0** |
| Full default keyless suite | `Remove-Item Env:RUN_LIVE_GROQ_TESTS,Env:GROQ_API_KEY,Env:GROQ_API_KEYS -ErrorAction SilentlyContinue; $env:PYTHONPATH='src'; & 'C:\Users\ADMIN\AppData\Local\Python\pythoncore-3.14-64\python.exe' -m pytest -q` | **89 passed, 2 skipped, 2 warnings in 16.29 s**; both live-provider tests were skipped |

The two `SwigPy*` warnings are third-party deprecations from retrieval
dependencies. The local model was loaded from the project cache. The keyless
run removed provider credential variables from its process environment and did
not invoke live tests. See `recordings/step8-*.json` for timestamped live
scenario outcomes.
