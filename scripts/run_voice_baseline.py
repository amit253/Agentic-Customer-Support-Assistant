"""Run one live recorded-audio STT -> support -> TTS baseline turn."""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from pathlib import Path

from agentic_support.config import Settings
from agentic_support.voice import VoicePipeline, build_live_voice_pipeline


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input_audio", type=Path)
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--session-id", default="demo-session-omar")
    parser.add_argument("--trace-id", default=None)
    args = parser.parse_args()

    settings = Settings.from_environment()
    pipeline: VoicePipeline = build_live_voice_pipeline(settings)
    result = pipeline.process(
        args.input_audio,
        session_id=args.session_id,
        trace_id=args.trace_id,
        output_path=args.output,
    )
    print(
        json.dumps(
            {
                "status": result.status,
                "trace_id": result.trace_id,
                "input_path": result.input_path,
                "transcript": result.transcript,
                "support_status": result.support_status,
                "support_message": result.support_message,
                "output_path": result.output_path,
                "error_code": result.error_code,
                "input_audio": asdict(result.input_audio)
                if result.input_audio is not None
                else None,
                "output_audio": asdict(result.output_audio)
                if result.output_audio is not None
                else None,
            },
            indent=2,
            sort_keys=True,
        )
    )
    if result.status != "ok":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
