"""Validate the Step 7 recording manifest without exposing audio or secrets."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from agentic_support.voice import AudioValidationError, validate_input_wav


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST = ROOT / "audio" / "manifest.json"


def validate_manifest(manifest_path: Path, *, require_recorded: bool) -> dict[str, Any]:
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    clips = payload.get("clips")
    if not isinstance(clips, list):
        raise ValueError("manifest clips must be a list")

    errors: list[dict[str, str]] = []
    recorded = 0
    pending = 0
    for clip in clips:
        clip_id = clip.get("id", "unknown")
        relative_path = clip.get("file")
        status = clip.get("status")
        if not isinstance(relative_path, str) or status not in {
            "pending_recording",
            "recorded",
        }:
            errors.append({"id": str(clip_id), "reason": "invalid_manifest_entry"})
            continue
        audio_path = ROOT / relative_path
        if status == "pending_recording":
            pending += 1
            if require_recorded:
                errors.append({"id": str(clip_id), "reason": "recording_pending"})
            continue
        recorded += 1
        try:
            validate_input_wav(audio_path)
        except (AudioValidationError, OSError) as exc:
            errors.append({"id": str(clip_id), "reason": str(exc)})

    return {
        "manifest": str(manifest_path),
        "clip_count": len(clips),
        "recorded_count": recorded,
        "pending_count": pending,
        "error_count": len(errors),
        "errors": errors,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--require-recorded", action="store_true")
    args = parser.parse_args()
    result = validate_manifest(args.manifest, require_recorded=args.require_recorded)
    print(json.dumps(result, indent=2, sort_keys=True))
    if result["error_count"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
