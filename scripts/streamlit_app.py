"""Small local Streamlit demo for unified text and recorded-voice turns.

Run from the repository root with::

    python -m streamlit run scripts/streamlit_app.py --server.address 127.0.0.1 --server.port 8502

The app uses the same live SupportService and VoicePipeline as the CLI demos.
It is intentionally local-only: credentials are loaded by the application from
the ignored .env and are never displayed. Browser voice is record-then-send;
the real-time barge-in scenarios remain in the CLI evidence path.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from uuid import uuid4

import streamlit as st

from agentic_support.config import Settings
from agentic_support.pipeline import SupportService, build_live_support_service
from agentic_support.voice import VoicePipeline, build_live_voice_pipeline


ROOT = Path(__file__).resolve().parents[1]
STREAMLIT_OUTPUT_DIR = ROOT / ".tmp" / "streamlit"
VOICE_CLIPS = {
    "Normal order status": ROOT / "audio" / "normal_order_status.wav",
    "Return eligibility": ROOT / "audio" / "return_eligibility.wav",
    "Speech interruption": ROOT / "audio" / "wrong_order_interrupt.wav",
    "Adversarial interruption": ROOT / "audio" / "adversarial_false_start.wav",
}
SESSION_OPTIONS = {
    "Nadia (NS-26-1042-5)": "demo-session-nadia",
    "Omar (NS-26-2044-8, NS-26-4006-8)": "demo-session-omar",
    "Priya (NS-26-3005-6)": "demo-session-priya",
}


@st.cache_resource(show_spinner="Loading the live guarded support service...")
def load_support_service() -> tuple[Settings, SupportService]:
    settings = Settings.from_environment()
    settings.require_groq_credentials()
    return settings, build_live_support_service(settings)


@st.cache_resource(
    show_spinner=(
        "Preparing voice support; the first run may load the local RAG "
        "embedding model (~90 MB)..."
    )
)
def load_voice_pipeline() -> tuple[Settings, VoicePipeline]:
    settings = Settings.from_environment()
    settings.require_groq_credentials()
    _, support_service = load_support_service()
    return settings, build_live_voice_pipeline(
        settings,
        support_service=support_service,
    )


def safe_json(value: object) -> object:
    """Convert dataclasses and dates to display-safe JSON data."""

    return json.loads(json.dumps(value, default=str))


def _conversation() -> list[dict[str, object]]:
    return st.session_state.setdefault("conversation", [])


def _append_turn(turn: dict[str, object]) -> None:
    _conversation().append(turn)


def _render_conversation() -> None:
    turns = _conversation()
    for turn in turns:
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


def _render_trace_details() -> None:
    turns = _conversation()
    if not turns:
        return
    with st.sidebar.expander("Trace details", expanded=False):
        for index, turn in enumerate(turns, start=1):
            st.caption(
                f"Turn {index}: {turn['status']} · `{turn['trace_id']}`"
            )
            st.json(
                safe_json(
                    {
                        "intent": turn.get("intent"),
                        "handler": turn.get("handler"),
                        "metadata": turn.get("metadata", {}),
                        "error_code": turn.get("error_code"),
                        "latency_ms": turn.get("latency_ms"),
                        "stt_attempts": turn.get("stt_attempts"),
                    }
                )
            )


def _handle_text(message: str, session_id: str) -> None:
    trace_id = f"streamlit-text-{uuid4().hex[:12]}"
    try:
        _, service = load_support_service()
        response = service.handle(
            message,
            session_id=session_id,
            channel="text",
            trace_id=trace_id,
        )
        _append_turn(
            {
                "kind": "text",
                "user_text": message,
                "assistant_text": response.message,
                "status": response.status,
                "trace_id": response.trace_id,
                "intent": response.intent,
                "handler": response.handler_name,
                "metadata": response.metadata,
            }
        )
    except Exception as error:  # pragma: no cover - UI boundary
        _append_turn(
            {
                "kind": "text",
                "user_text": message,
                "assistant_text": "I could not complete that request safely.",
                "status": "failed",
                "trace_id": trace_id,
                "error_code": type(error).__name__,
            }
        )


def _handle_voice(audio_bytes: bytes, session_id: str) -> None:
    STREAMLIT_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    trace_id = f"streamlit-voice-{uuid4().hex[:12]}"
    input_path = STREAMLIT_OUTPUT_DIR / f"{trace_id}-input.wav"
    output_path = STREAMLIT_OUTPUT_DIR / f"{trace_id}-output.wav"
    input_path.write_bytes(audio_bytes)

    try:
        _, pipeline = load_voice_pipeline()
        with st.spinner("Running STT, support, and TTS..."):
            result = pipeline.process(
                input_path,
                session_id=session_id,
                trace_id=trace_id,
                output_path=output_path,
            )
        _append_turn(
            {
                "kind": "voice",
                "audio_bytes": audio_bytes,
                "transcript": result.transcript,
                "assistant_text": result.support_message
                or "The voice request completed without a message.",
                "status": result.status,
                "trace_id": result.trace_id,
                "intent": result.support_intent,
                "handler": result.support_handler,
                "metadata": result.support_metadata,
                "output_path": result.output_path,
                "error_code": result.error_code,
                "latency_ms": result.latency_ms,
                "stt_attempts": result.stt_attempts,
            }
        )
    except Exception as error:  # pragma: no cover - UI boundary
        _append_turn(
            {
                "kind": "voice",
                "audio_bytes": audio_bytes,
                "assistant_text": "I could not process that audio safely.",
                "status": "failed",
                "trace_id": trace_id,
                "error_code": type(error).__name__,
            }
        )


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
    """Render the text composer with a compact adjacent microphone control."""

    text_column, voice_column = st.columns([8, 1])
    with text_column:
        prompt = st.chat_input("Message Northstar Support...")
    with voice_column:
        recorded_audio = st.audio_input(
            "🎙️",
            sample_rate=16000,
            label_visibility="collapsed",
            key="browser_voice_input",
        )

    if prompt and prompt.strip():
        _handle_text(prompt.strip(), session_id)
        st.rerun()

    if recorded_audio is None:
        return

    audio_bytes = recorded_audio.getvalue()
    digest = hashlib.sha256(audio_bytes).hexdigest()
    if digest == st.session_state.get("last_processed_voice_digest"):
        return
    st.session_state["last_processed_voice_digest"] = digest
    _handle_voice(audio_bytes, session_id)
    st.rerun()


def main() -> None:
    st.set_page_config(
        page_title="Northstar Gear Support Demo",
        page_icon="🎒",
        layout="centered",
    )
    st.title("Northstar Gear Support")
    st.caption("Text and voice support in one simple conversation")

    try:
        settings = Settings.from_environment()
        st.sidebar.success(f"Groq configured: {settings.groq_configured}")
        st.sidebar.caption("The key value is never displayed or logged.")
    except Exception as error:  # pragma: no cover - UI boundary
        st.sidebar.error(f"Configuration error: {type(error).__name__}")

    session_label = st.sidebar.selectbox("Demo session", list(SESSION_OPTIONS))
    session_id = SESSION_OPTIONS[session_label]
    if st.sidebar.button("Clear conversation"):
        st.session_state["conversation"] = []
        try:
            _, support_service = load_support_service()
            support_service.clear_session(session_id)
        except Exception:
            pass
        st.rerun()

    st.info(
        "Type a message below or use the microphone button beside the text box. "
        "Voice replies include playable audio."
    )
    with st.expander("How this demo works"):
        st.markdown(
            "Both input types use the same path: input validation → safety "
            "guardrail → Groq router → RAG/tool/handoff handler → output-claim "
            "guard. Voice adds Groq Whisper STT before the service and local "
            "Windows TTS after it. Trace IDs and safe metadata are available "
            "in the sidebar."
        )

    _render_conversation()
    _render_trace_details()
    with st.sidebar.expander("Developer test recordings"):
        _render_checked_recordings(session_id)
    _render_composer(session_id)


if __name__ == "__main__":
    main()
