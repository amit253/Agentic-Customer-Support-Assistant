"""Small local Streamlit demo for unified text and recorded-voice turns.

Run from the repository root with::

    python -m streamlit run scripts/streamlit_app.py --server.address 127.0.0.1 --server.port 8502

The app uses the same live SupportService and VoicePipeline as the CLI demos.
It is intentionally local-only: credentials are loaded by the application from
the ignored .env and are never displayed. Browser voice is record-then-send
through the microphone inside the message box; the real-time barge-in
scenarios remain in the CLI evidence path.

UI decisions:

* Each demo customer has a separate conversation, so switching customers
  never shows one customer's chat next to another customer's memory.
* Replies are shown only after the output guard has validated the complete
  text, so there is no token streaming; a spinner shows progress instead.
* Quick replies come from the handler's ``suggestions`` metadata, and thumbs
  feedback is appended to ``.tmp/feedback/feedback.jsonl`` with the trace ID
  so poor answers can be turned into new evaluation cases.
"""

from __future__ import annotations

import json
import time
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import streamlit as st

from agentic_support.config import Settings
from agentic_support.pipeline import SupportService, build_live_support_service
from agentic_support.voice import VoicePipeline, build_live_voice_pipeline


ROOT = Path(__file__).resolve().parents[1]
STREAMLIT_OUTPUT_DIR = ROOT / ".tmp" / "streamlit"
FEEDBACK_PATH = ROOT / ".tmp" / "feedback" / "feedback.jsonl"
VOICE_CLIPS = {
    "Normal order status": ROOT / "audio" / "normal_order_status.wav",
    "Return eligibility": ROOT / "audio" / "return_eligibility.wav",
    "Speech interruption": ROOT / "audio" / "wrong_order_interrupt.wav",
    "Adversarial interruption": ROOT / "audio" / "adversarial_false_start.wav",
}
SESSION_OPTIONS = {
    "Nadia (3 orders)": "demo-session-nadia",
    "Omar (3 orders)": "demo-session-omar",
    "Priya (1 order)": "demo-session-priya",
}
STARTER_PROMPTS = (
    "Where is my order?",
    "What is the return policy?",
    "Does the Trailmark 28 have a laptop sleeve?",
    "Talk to a human",
)
HANDLER_LABELS = {
    "product_question_handler": "Answered from help articles",
    "order_status_handler": "Checked with the order tool",
    "escalate_to_human_handler": "Handed to a human agent",
    "conversation_handler": "Conversation",
}
ROUTING_TIERS = {
    "deterministic_order_signal": "rule",
    "verified_session_memory": "session memory",
    "rule_smalltalk": "rule",
    "rule_human_request": "rule",
    "rule_gibberish": "rule",
    "semantic_exemplars": "examples",
    "classifier": "LLM",
    "router_fallback": "fallback",
}


@st.cache_resource(show_spinner=False)
def load_support_service() -> tuple[Settings, SupportService]:
    settings = Settings.from_environment()
    settings.require_groq_credentials()
    return settings, build_live_support_service(settings)


@st.cache_resource(show_spinner=False)
def load_voice_pipeline() -> tuple[Settings, VoicePipeline]:
    settings, support_service = load_support_service()
    return settings, build_live_voice_pipeline(settings, support_service=support_service)


def safe_json(value: object) -> object:
    """Convert dataclasses and dates to display-safe JSON data."""

    return json.loads(json.dumps(value, default=str))


def _conversation(session_id: str) -> list[dict[str, object]]:
    conversations = st.session_state.setdefault("conversations", {})
    return conversations.setdefault(session_id, [])


def _turn_caption(turn: dict[str, object]) -> str:
    metadata = turn.get("metadata") or {}
    if turn["status"] != "ok":
        label = "Stopped safely"
    else:
        label = HANDLER_LABELS.get(str(turn.get("handler")), "Answered")
    parts = [label]
    tier = ROUTING_TIERS.get(str(metadata.get("routing_source")))
    if tier:
        parts.append(f"routed by {tier}")
    if turn.get("latency_ms") is not None:
        parts.append(f"{float(turn['latency_ms']) / 1000:.1f} s")
    return " · ".join(parts)


def _save_feedback(session_id: str, turn: dict[str, object], key: str) -> None:
    rating = st.session_state.get(key)
    if rating is None:
        return
    FEEDBACK_PATH.parent.mkdir(parents=True, exist_ok=True)
    metadata = turn.get("metadata") or {}
    record = {
        "at": datetime.now(UTC).isoformat(timespec="seconds"),
        "trace_id": turn["trace_id"],
        "session_id": session_id,
        "rating": "up" if rating == 1 else "down",
        "user_text": turn.get("user_text") or turn.get("transcript"),
        "intent": turn.get("intent"),
        "handler": turn.get("handler"),
        "routing_source": metadata.get("routing_source"),
        "status": turn.get("status"),
    }
    with FEEDBACK_PATH.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record) + "\n")


def _render_handoff(metadata: dict[str, object]) -> None:
    reference = metadata.get("handoff_reference")
    if not reference:
        return
    st.info(f"Handoff reference: **{reference}**")
    summary = metadata.get("handoff_summary")
    if summary:
        with st.expander("What the human agent receives"):
            st.json(safe_json(summary))


def _render_conversation(session_id: str) -> None:
    for turn in _conversation(session_id):
        with st.chat_message("user"):
            if turn["kind"] == "voice":
                st.audio(turn["audio_bytes"], format="audio/wav")
                if turn.get("transcript"):
                    st.markdown(f"_{turn['transcript']}_")
            else:
                st.write(turn["user_text"])

        with st.chat_message("assistant"):
            st.markdown(str(turn["assistant_text"]))
            output_path = turn.get("output_path")
            if output_path and Path(str(output_path)).exists():
                st.audio(Path(str(output_path)).read_bytes(), format="audio/wav")
            metadata = turn.get("metadata") or {}
            _render_handoff(metadata)
            st.caption(_turn_caption(turn))
            key = f"feedback-{turn['trace_id']}"
            st.feedback("thumbs", key=key, on_change=_save_feedback, args=(session_id, turn, key))


def _render_suggestions(session_id: str) -> None:
    turns = _conversation(session_id)
    suggestions = (
        STARTER_PROMPTS
        if not turns
        else tuple((turns[-1].get("metadata") or {}).get("suggestions") or ())
    )
    if not suggestions:
        return
    choice = st.pills(
        "Suggestions",
        list(suggestions)[:4],
        key=f"suggestions-{session_id}-{len(turns)}",
        label_visibility="collapsed",
    )
    if choice:
        # Handle the click now; the next render uses a new widget key because
        # the turn count changed, so the same suggestion is not resubmitted.
        _handle_text(choice, session_id)
        st.rerun()


def _render_trace_details(session_id: str) -> None:
    turns = _conversation(session_id)
    if not turns:
        return
    with st.sidebar.expander("Trace details", expanded=False):
        for index, turn in enumerate(turns, start=1):
            st.caption(f"Turn {index}: {turn['status']} · `{turn['trace_id']}`")
            metadata = dict(turn.get("metadata") or {})
            metadata.pop("handoff_summary", None)
            st.json(
                safe_json(
                    {
                        "intent": turn.get("intent"),
                        "handler": turn.get("handler"),
                        "metadata": metadata,
                        "error_code": turn.get("error_code"),
                        "latency_ms": turn.get("latency_ms"),
                        "stt_attempts": turn.get("stt_attempts"),
                    }
                )
            )


def _handle_text(message: str, session_id: str) -> None:
    trace_id = f"streamlit-text-{uuid4().hex[:12]}"
    start = time.perf_counter()
    try:
        _, service = load_support_service()
        with st.spinner("Checking that for you..."):
            response = service.handle(
                message,
                session_id=session_id,
                channel="text",
                trace_id=trace_id,
            )
        turn = {
            "kind": "text",
            "user_text": message,
            "assistant_text": response.message,
            "status": response.status,
            "trace_id": response.trace_id,
            "intent": response.intent,
            "handler": response.handler_name,
            "metadata": response.metadata,
        }
    except Exception as error:  # pragma: no cover - UI boundary
        turn = {
            "kind": "text",
            "user_text": message,
            "assistant_text": "Something went wrong on our side. Please try again, or ask for a human agent.",
            "status": "failed",
            "trace_id": trace_id,
            "error_code": type(error).__name__,
        }
    turn["latency_ms"] = (time.perf_counter() - start) * 1000
    _conversation(session_id).append(turn)


def _handle_voice(audio_bytes: bytes, session_id: str) -> None:
    STREAMLIT_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    trace_id = f"streamlit-voice-{uuid4().hex[:12]}"
    input_path = STREAMLIT_OUTPUT_DIR / f"{trace_id}-input.wav"
    output_path = STREAMLIT_OUTPUT_DIR / f"{trace_id}-output.wav"
    input_path.write_bytes(audio_bytes)

    try:
        _, pipeline = load_voice_pipeline()
        with st.spinner("Transcribing, checking, and preparing a spoken reply..."):
            result = pipeline.process(
                input_path,
                session_id=session_id,
                trace_id=trace_id,
                output_path=output_path,
            )
        turn = {
            "kind": "voice",
            "audio_bytes": audio_bytes,
            "transcript": result.transcript,
            "assistant_text": result.support_message
            or "The voice request completed without a message.",
            "status": result.status if result.status != "ok" else (result.support_status or "ok"),
            "trace_id": result.trace_id,
            "intent": result.support_intent,
            "handler": result.support_handler,
            "metadata": result.support_metadata,
            "output_path": result.output_path,
            "error_code": result.error_code,
            "latency_ms": result.latency_ms,
            "stt_attempts": result.stt_attempts,
        }
    except Exception as error:  # pragma: no cover - UI boundary
        turn = {
            "kind": "voice",
            "audio_bytes": audio_bytes,
            "assistant_text": "I could not process that audio. Please try again, or type your question.",
            "status": "failed",
            "trace_id": trace_id,
            "error_code": type(error).__name__,
        }
    _conversation(session_id).append(turn)


def _render_checked_recordings(session_id: str) -> None:
    clip_label = st.selectbox("Recording", list(VOICE_CLIPS))
    input_path = VOICE_CLIPS[clip_label]
    if input_path.exists():
        if st.button("Send checked recording", key="send_checked_recording"):
            _handle_voice(input_path.read_bytes(), session_id)
            st.rerun()
    else:
        st.error(f"Recording is missing: {input_path}")


def _render_composer(session_id: str) -> None:
    """One message box: type text, or tap the mic inside it to record.

    ``st.chat_input(accept_audio=True)`` puts the microphone inside the box,
    and a recording is sent with Enter or the send arrow like a typed
    message. It replaces a separate ``st.audio_input`` widget that sat in a
    narrow column beside the box, where its controls and error text were
    clipped. Each submission is returned once, so no duplicate check is needed.
    """

    submission = st.chat_input(
        "Type a message, or tap the mic to speak...",
        accept_audio=True,
        audio_sample_rate=16000,
        key="composer",
    )
    if submission is None:
        return
    audio = getattr(submission, "audio", None)
    text = (getattr(submission, "text", "") or "").strip()
    if audio is not None:
        _handle_voice(audio.getvalue(), session_id)
    if text:
        _handle_text(text, session_id)
    if audio is not None or text:
        st.rerun()


def main() -> None:
    st.set_page_config(
        page_title="Northstar Gear Support",
        page_icon="🎒",
        layout="centered",
    )
    st.title("Northstar Gear Support")
    st.caption("Ask about an order, a return, our policies, or our backpacks, by text or voice.")

    try:
        settings = Settings.from_environment()
        st.sidebar.success(
            f"Groq configured: {settings.groq_configured} "
            f"({len(settings.groq_api_keys)} key(s))"
        )
        st.sidebar.caption("Key values are never displayed or logged.")
    except Exception as error:  # pragma: no cover - UI boundary
        st.sidebar.error(f"Configuration error: {type(error).__name__}")

    session_label = st.sidebar.selectbox("Demo customer", list(SESSION_OPTIONS))
    session_id = SESSION_OPTIONS[session_label]
    if st.sidebar.button("Clear this conversation"):
        st.session_state.setdefault("conversations", {})[session_id] = []
        try:
            _, support_service = load_support_service()
            support_service.clear_session(session_id)
        except Exception:
            pass
        st.rerun()

    if "service_ready" not in st.session_state:
        with st.spinner(
            "Starting support: loading the local search and routing models "
            "(the first start can take a minute)..."
        ):
            try:
                load_support_service()
                st.session_state["service_ready"] = True
            except Exception as error:  # pragma: no cover - UI boundary
                st.error(f"Support service could not start: {type(error).__name__}")
                return

    with st.expander("How this demo works"):
        st.markdown(
            "Every message goes through the same path: input checks → safety "
            "guardrail → hybrid router (rules, then labeled examples, then the "
            "Groq LLM only when needed) → help-article search, order tools, "
            "human handoff, or a conversational reply → output check that "
            "blocks unverified dates, amounts, and promises. To speak, tap the "
            "microphone inside the message box, record, then press Enter or the "
            "send arrow. Voice adds Groq "
            "Whisper speech-to-text before the service and local Windows "
            "text-to-speech after it. Each reply shows which path answered it; "
            "trace details are in the sidebar."
        )

    _render_conversation(session_id)
    _render_suggestions(session_id)
    _render_trace_details(session_id)
    with st.sidebar.expander("Developer test recordings"):
        _render_checked_recordings(session_id)
    _render_composer(session_id)


if __name__ == "__main__":
    main()
