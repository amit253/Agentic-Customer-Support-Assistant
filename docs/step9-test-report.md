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

The audible Step 8 scenario reports are real-time file-backed runs using the
configured live Groq STT/support path except for the explicitly injected
provider-failure scenario. Reports and limitations:

- `recordings/step8-noise-run.json`: noise did not interrupt playback; no STT
  follow-up was started.
- `recordings/step8-interruption-run.json`: recorded speech interrupted
  playback and the old turn was discarded; live input safety failed closed on
  the resulting transcript.
- `recordings/step8-adversarial-run.json`: recorded speech interrupted
  playback and the stale result was discarded; the transcript retained the
  refund request, but live classification failed closed.
- `recordings/step8-provider_failure-run.json`: two injected STT failures
  produced a safe audible handoff; this is not evidence of an actual Groq
  outage.

The detailed scenario timestamps and app-level playback-start latencies are
in [the Step 8 runbook](./voice-coordination.md). These live results are not
included in the keyless test pass count.

## Limitations

- A successful live end-to-end follow-up after speech interruption is not
  demonstrated; Step 8 remains incomplete.
- `end_of_speech_to_first_audio_ms` measures the application playback-start
  handoff, not acoustic loopback at the first physical audio sample.
- The optional pace/accent recording remains pending.
