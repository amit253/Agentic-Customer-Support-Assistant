"""Small local Streamlit demo for the guarded text and recorded-voice paths.

Run from the repository root with::

    python -m streamlit run scripts/streamlit_app.py --server.address 127.0.0.1

The app uses the same live SupportService and VoicePipeline as the CLI demos.
It is intentionally local-only: credentials are loaded by the application from
the ignored .env and are never displayed.
"""

from __future__ import annotations

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


@st.cache_resource(show_spinner="Loading the live voice pipeline...")
def load_voice_pipeline() -> tuple[Settings, VoicePipeline]:
    settings = Settings.from_environment()
    settings.require_groq_credentials()
    return settings, build_live_voice_pipeline(settings)


def safe_json(value: object) -> object:
    """Convert dataclasses and dates to display-safe JSON data."""

    return json.loads(json.dumps(value, default=str))


def show_provider_error(error: Exception) -> None:
    st.error(
        "The live provider could not be initialized. Check the local .env and "
        f"retry. ({type(error).__name__})"
    )


def render_text_tab() -> None:
    st.subheader("Text support")
    st.caption(
        "This sends the message through input safety, Groq routing, the selected "
        "handler, and output-claim validation."
    )

    session_label = st.selectbox("Demo session", list(SESSION_OPTIONS))
    message = st.text_area(
        "Customer message",
        value="How many liters is the Trailmark 28 backpack?",
        height=100,
    )

    if st.button("Send text request", type="primary"):
        if not message.strip():
            st.warning("Enter a customer message first.")
            return
        try:
            _, service = load_support_service()
            trace_id = f"streamlit-text-{uuid4().hex[:12]}"
            response = service.handle(
                message,
                session_id=SESSION_OPTIONS[session_label],
                channel="text",
                trace_id=trace_id,
            )
        except Exception as error:  # pragma: no cover - UI boundary
            show_provider_error(error)
            return

        if response.status == "ok":
            st.success(response.message)
        elif response.status == "failed_closed":
            st.warning(response.message)
        else:
            st.info(response.message)

        st.json(
            safe_json(
                {
                    "status": response.status,
                    "trace_id": response.trace_id,
                    "intent": response.intent,
                    "handler": response.handler_name,
                    "metadata": response.metadata,
                }
            )
        )


def render_voice_tab() -> None:
    st.subheader("Recorded voice demo")
    st.caption(
        "Select a real recorded clip, listen to it, and run it through Groq STT, "
        "the shared SupportService, and local Windows TTS."
    )

    clip_label = st.selectbox("Input recording", list(VOICE_CLIPS))
    session_label = st.selectbox(
        "Voice demo session",
        list(SESSION_OPTIONS),
        index=1,
        key="voice_session",
    )
    input_path = VOICE_CLIPS[clip_label]

    if not input_path.exists():
        st.error(f"Recording is missing: {input_path}")
        return

    st.audio(input_path.read_bytes(), format="audio/wav")
    st.caption(f"Input: `{input_path.relative_to(ROOT)}`")

    if st.button("Run live voice turn", type="primary"):
        try:
            _, pipeline = load_voice_pipeline()
            STREAMLIT_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
            trace_id = f"streamlit-voice-{uuid4().hex[:12]}"
            output_path = STREAMLIT_OUTPUT_DIR / f"{trace_id}.wav"
            with st.spinner("Running STT, support, and TTS..."):
                result = pipeline.process(
                    input_path,
                    session_id=SESSION_OPTIONS[session_label],
                    trace_id=trace_id,
                    output_path=output_path,
                )
        except Exception as error:  # pragma: no cover - UI boundary
            show_provider_error(error)
            return

        if result.status == "ok":
            st.success("Voice turn completed.")
        elif result.status == "handoff":
            st.warning("Voice turn completed with a safe handoff.")
        else:
            st.error("Voice turn failed safely.")

        if result.transcript:
            st.write(f"**Transcript:** {result.transcript}")
        if result.support_message:
            st.write(f"**Support response:** {result.support_message}")
        if result.output_path and Path(result.output_path).exists():
            st.write("**Generated response audio:**")
            st.audio(Path(result.output_path).read_bytes(), format="audio/wav")

        st.json(
            safe_json(
                {
                    "status": result.status,
                    "trace_id": result.trace_id,
                    "support_status": result.support_status,
                    "support_intent": result.support_intent,
                    "support_handler": result.support_handler,
                    "error_code": result.error_code,
                    "latency_ms": result.latency_ms,
                    "stt_attempts": result.stt_attempts,
                }
            )
        )


def main() -> None:
    st.set_page_config(
        page_title="Northstar Gear Support Demo",
        page_icon="🎒",
        layout="centered",
    )
    st.title("Northstar Gear Support")
    st.caption("Local demo of the guarded text and recorded-audio support paths")

    try:
        settings = Settings.from_environment()
        st.sidebar.success(f"Groq configured: {settings.groq_configured}")
        st.sidebar.caption("The key value is never displayed or logged.")
    except Exception as error:  # pragma: no cover - UI boundary
        st.sidebar.error(f"Configuration error: {type(error).__name__}")

    with st.expander("How this demo works"):
        st.markdown(
            "1. **Text:** input validation → safety guardrail → Groq router → "
            "RAG/tool/handoff handler → output-claim guard.\n"
            "2. **Voice:** recorded WAV → Groq Whisper STT → the same support "
            "service → local Windows TTS.\n"
            "3. Every request displays a trace ID for debugging."
        )

    text_tab, voice_tab = st.tabs(["Text support", "Voice demo"])
    with text_tab:
        render_text_tab()
    with voice_tab:
        render_voice_tab()


if __name__ == "__main__":
    main()
