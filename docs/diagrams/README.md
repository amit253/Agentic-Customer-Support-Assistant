# Diagrams

Each diagram has an editable Mermaid source (`.mmd`), a vector render (`.svg`)
for documents and slides, and a 2x PNG for chat or email. All five describe
the current code; file and module names in the boxes are real.

| Diagram | Shows | Files |
|---|---|---|
| System architecture | Transports, the guarded `SupportService`, routing tiers, agents, grounding and tools, output validation, session memory, voice reply and barge-in | [01-architecture.svg](01-architecture.svg) · [.png](01-architecture.png) · [.mmd](01-architecture.mmd) |
| Request flow | One turn end to end as a sequence: voice or text in, guard, router, agent, tools or retrieval, claim guard, memory, reply | [02-request-flow.svg](02-request-flow.svg) · [.png](02-request-flow.png) · [.mmd](02-request-flow.mmd) |
| Memory handling | A voice turn, a text follow-up resolved from verified memory, and a human handoff carrying both, in one session | [03-memory-handling.svg](03-memory-handling.svg) · [.png](03-memory-handling.png) · [.mmd](03-memory-handling.mmd) |
| Hybrid routing | The rule cascade, the labeled-example tier, the LLM tier, and the clarify fallback, with the share each tier decided live | [04-hybrid-routing.svg](04-hybrid-routing.svg) · [.png](04-hybrid-routing.png) · [.mmd](04-hybrid-routing.mmd) |
| Voice barge-in | Noise rejected, speech confirmed, playback cancelled, stale turn discarded, STT retry and safe handoff | [05-voice-barge-in.svg](05-voice-barge-in.svg) · [.png](05-voice-barge-in.png) · [.mmd](05-voice-barge-in.mmd) |

![System architecture](01-architecture.svg)

## Editing and re-rendering

Edit a `.mmd` file, then render with the pinned mermaid-cli Docker image
(Docker Desktop must be running; nothing is installed on the host):

```powershell
python scripts/render_diagrams.py              # all diagrams
python scripts/render_diagrams.py 03-memory    # one diagram by name prefix
```

Shared colors and spacing are in [mermaid-config.json](mermaid-config.json).
GitHub also renders Mermaid directly, so a `.mmd` body can be pasted into a
Markdown code block marked `mermaid`.

Two Mermaid rules worth knowing when editing: in sequence diagrams a semicolon
ends a statement, so message text must not contain one; and a subgraph's
`direction` is ignored when a node inside it links to a node outside it.
