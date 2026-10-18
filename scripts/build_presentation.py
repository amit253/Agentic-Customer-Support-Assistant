"""Build and reopen the assignment presentation from verified project facts."""

from __future__ import annotations

from pathlib import Path

from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import MSO_ANCHOR, MSO_AUTO_SIZE, PP_ALIGN
from pptx.util import Inches, Pt


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "presentation" / "agentic-customer-support.pptx"
NAVY = RGBColor(18, 36, 59)
BLUE = RGBColor(30, 111, 166)
PALE = RGBColor(235, 243, 249)
WHITE = RGBColor(255, 255, 255)
INK = RGBColor(30, 42, 54)


SLIDES: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "Agentic Customer Support Assistant",
        (
            "Northstar Gear - fictional customer-support domain",
            "Text and recorded-audio voice paths share SupportService",
            "Evidence snapshot: 2026-10-18",
            "Status: recorded-audio follow-ups pass; live latency remains high",
        ),
    ),
    (
        "Architecture and trust boundaries",
        (
            "Input shape checks -> InputGuard -> structured intent router",
            "Registered handler -> read-only tools or semantic retrieval",
            "OutputClaimGuard validates facts before the response leaves the service",
            "Voice transcript reuses the same support boundary",
        ),
    ),
    (
        "Domain, tools, and safety",
        (
            "All customers, sessions, orders, policies, and dates are fictional",
            "Order tools enforce format, verification, existence, and ownership",
            "Return eligibility is policy evidence, not refund approval",
            "Refund amounts and dates require confirmed tool facts",
        ),
    ),
    (
        "Grounded answers and tool-calling choice",
        (
            "12 original KB documents; local MiniLM embeddings and exact cosine scan",
            "Retrieval keeps source and chunk provenance; insufficient evidence is explicit",
            "Product answers cite retrieved chunks; only cited facts reach the output claim guard",
            "Native Groq calls select one allow-listed tool; local code validates arguments and ownership",
        ),
    ),
    (
        "Measured offline baseline",
        (
            "Keyless suite: 89 passed, 2 live checks skipped; 2 dependency warnings",
            "Routing accuracy 0.8333; retrieval recall@5 0.7273",
            "Input guardrail recall 0.6667; output guardrail recall 1.0",
            "Classifier cache hit rate 0.5 on the measured workload",
        ),
    ),
    (
        "Voice turn coordination",
        (
            "WebRTC candidate: 3 positive 20 ms frames; local Silero ONNX confirms",
            "Turn IDs, playback cancellation, stale-result discard, and bounded STT retry",
            "Labeled regression corpus: 0 false interruptions; 0 missed speech",
            "Corpus result only; not a universal speech/noise performance claim",
        ),
    ),
    (
        "Audible scenario evidence",
        (
            "Silence and current noise clip completed audible playback without interruption",
            "Normal order, return eligibility, and wrong-order follow-ups completed safely",
            "Adversarial follow-up escalated; no refund promise or stale response",
            "Injected STT failure retried twice and played a safe handoff",
        ),
    ),
    (
        "Latency and measurement limits",
        (
            "Successful speech follow-ups: 19,293.912-20,168.889 ms to app playback start",
            "Injected failure handoff: 15,886.752 ms; cancellation call: 105-128 ms",
            "App playback-start latency is not first-acoustic-sample latency",
            "All voice latency observations exceed proposed <3 second target",
        ),
    ),
    (
        "Red-team: two reproduced gaps",
        (
            "safe=true with confidence 0.0 allowed an injection before the fix",
            "Natural-language unverified delivery date passed output validation before the fix",
            "Both fixes have service-boundary regression tests",
            "Residual risks: semantic classifier errors and heuristic coverage",
        ),
    ),
    (
        "Scale and operations - PROPOSED",
        (
            "Stateless workers; durable shared session state; bounded queues and rate limits",
            "Versioned cache keys; provider deadlines, backpressure, circuit breaking",
            "Shadow route changes, canary with safety gates, immediate rollback",
            "No 10,000-session load test or distributed state store exists",
        ),
    ),
    (
        "Part C and next work",
        (
            "Voice-to-text/human shared-state transfer is designed, not implemented",
            "Groq degradation: bounded retry then fail-closed or local safe handoff",
            "Separate live Groq product-answer and native-tool smoke checks passed",
            "Next: reduce voice latency, measure acoustic output, practice unaided",
        ),
    ),
)


def _set_run_font(run, *, size: int, color: RGBColor, bold: bool = False) -> None:
    run.font.name = "Aptos"
    run.font.size = Pt(size)
    run.font.bold = bold
    run.font.color.rgb = color


def _add_cover(prs: Presentation) -> None:
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    background = slide.background.fill
    background.solid()
    background.fore_color.rgb = NAVY

    accent = slide.shapes.add_shape(
        MSO_SHAPE.RECTANGLE, Inches(0), Inches(0), Inches(0.22), Inches(7.5)
    )
    accent.fill.solid()
    accent.fill.fore_color.rgb = BLUE
    accent.line.fill.background()

    box = slide.shapes.add_textbox(Inches(0.9), Inches(1.5), Inches(11.4), Inches(3.8))
    frame = box.text_frame
    frame.clear()
    frame.vertical_anchor = MSO_ANCHOR.MIDDLE
    title = frame.paragraphs[0]
    title.text = SLIDES[0][0]
    title.font.name = "Aptos Display"
    title.font.size = Pt(34)
    title.font.bold = True
    title.font.color.rgb = WHITE

    for text in SLIDES[0][1]:
        paragraph = frame.add_paragraph()
        paragraph.text = text
        paragraph.font.name = "Aptos"
        paragraph.font.size = Pt(18)
        paragraph.font.color.rgb = PALE
        paragraph.space_before = Pt(12)


def _add_content_slide(prs: Presentation, title: str, bullets: tuple[str, ...], page: int) -> None:
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    slide.background.fill.solid()
    slide.background.fill.fore_color.rgb = WHITE

    header = slide.shapes.add_shape(
        MSO_SHAPE.RECTANGLE, Inches(0), Inches(0), Inches(13.333), Inches(0.85)
    )
    header.fill.solid()
    header.fill.fore_color.rgb = NAVY
    header.line.fill.background()

    title_box = slide.shapes.add_textbox(
        Inches(0.55), Inches(0.1), Inches(12.2), Inches(0.58)
    )
    title_frame = title_box.text_frame
    title_frame.clear()
    title_frame.vertical_anchor = MSO_ANCHOR.MIDDLE
    title_run = title_frame.paragraphs[0].add_run()
    title_run.text = title
    _set_run_font(title_run, size=24, color=WHITE, bold=True)

    body = slide.shapes.add_textbox(
        Inches(0.85), Inches(1.3), Inches(11.7), Inches(5.35)
    )
    frame = body.text_frame
    frame.clear()
    frame.word_wrap = True
    frame.auto_size = MSO_AUTO_SIZE.TEXT_TO_FIT_SHAPE
    for index, text in enumerate(bullets):
        paragraph = frame.paragraphs[0] if index == 0 else frame.add_paragraph()
        paragraph.text = text
        paragraph.level = 0
        paragraph.font.name = "Aptos"
        paragraph.font.size = Pt(21)
        paragraph.font.color.rgb = INK
        paragraph.space_after = Pt(22)

    footer = slide.shapes.add_textbox(
        Inches(0.6), Inches(7.03), Inches(12.1), Inches(0.25)
    )
    footer_frame = footer.text_frame
    footer_frame.clear()
    footer_frame.paragraphs[0].alignment = PP_ALIGN.RIGHT
    run = footer_frame.paragraphs[0].add_run()
    run.text = f"Agentic Customer Support Assistant  |  {page} / {len(SLIDES)}"
    _set_run_font(run, size=9, color=BLUE)


def build() -> Path:
    prs = Presentation()
    prs.slide_width = Inches(13.333)
    prs.slide_height = Inches(7.5)
    _add_cover(prs)
    for page, (title, bullets) in enumerate(SLIDES[1:], start=2):
        _add_content_slide(prs, title, bullets, page)

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    prs.save(OUTPUT)

    verified = Presentation(OUTPUT)
    if len(verified.slides) != len(SLIDES):
        raise RuntimeError("presentation_slide_count_mismatch")
    for slide, (expected_title, _) in zip(
        verified.slides, SLIDES, strict=True
    ):
        slide_text = "\n".join(
            shape.text
            for shape in slide.shapes
            if shape.has_text_frame
        )
        if expected_title not in slide_text:
            raise RuntimeError("presentation_expected_title_missing")
    print(
        {
            "presentation": str(OUTPUT.relative_to(ROOT)),
            "slides": len(verified.slides),
            "titles_verified": len(SLIDES),
            "verified_open": True,
        }
    )
    return OUTPUT


if __name__ == "__main__":
    build()
