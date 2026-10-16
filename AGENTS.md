# AGENTS.md

## Scope

These instructions apply to the Agentic Customer Support Assistant repository
at the workspace root. The assignment PDF in `Problem_Statement/` is the
source of truth for mandatory requirements.

## Execution contract

- Execute only the step explicitly requested by the user.
- Do not start a later step automatically.
- Before editing, inspect the repository, Git status, relevant files, and the
  assignment PDF.
- Preserve existing work and avoid unrelated changes.
- Do not create placeholder modules or claim a feature exists before it is
  implemented.
- At the end of each step, report changed files, design decisions, exact
  commands/results, completed/incomplete requirements, limitations, and the
  real commit hash if one was created.
- At the end of each step, ask: "Do you want to add a [USER] note on what you
  decided or found confusing?"

## Secrets and privacy

- Never ask the user to paste an API key into chat.
- Read provider secrets only from environment variables or ignored local files.
- Never print, log, commit, screenshot, or record a real API key.
- Do not use real customer or identity data. All support data is fictional.
- Inspect only whether secret variable names are set when that is necessary;
  never display their values.

## Testing and evidence

- Default tests must run without `GROQ_API_KEY` using fake/stub provider
  clients. Live-provider tests must be explicitly marked and skipped by
  default.
- Never invent test results, latency numbers, audio recordings, metrics,
  failures, timestamps, or Git history.
- Label mock/stub evidence separately from live-provider evidence.
- Use real timestamps for decisions and commits.
- Keep reproducible commands and actual output in the relevant documentation.

## Assignment integrity

- Maintain genuine incremental Git history; never squash, amend, rewrite, or
  fabricate commits.
- Add decisions-log entries only for decisions, comparisons, or failed
  experiments that actually happened.
- Red-team findings must come from reproduced system behavior. Do not
  pre-write or fabricate weaknesses.
- The user's own domain choices and adversarial scenario must be recorded
  honestly and be specific to the submission.
- If a requirement is blocked, state the blocker and provide exact next
  actions instead of claiming completion.

## Implementation style

- Prefer readable Python, small functions, explicit control flow, and clear
  interfaces over unnecessary abstractions.
- Explain why a design exists, its inputs/outputs, failure modes, tests, and
  production changes.
- Keep the shared support service independent of the text or voice transport.
- Guardrails must be enforced in application code, not only in prompts.
- Voice coordination must prevent stale or duplicate turn results and must
  degrade safely when a provider fails.

## Git workflow

At the end of a requested step:

1. Inspect `git status` and the diff.
2. Run relevant checks and record their real results.
3. Check staged files for secrets, unrelated changes, and accidental media.
4. Stage only reviewed files.
5. Commit only when the step's acceptance criteria are genuinely met.
6. If checks fail, report the failure and ask before committing incomplete work.
7. Show the real commit hash and recent log.
