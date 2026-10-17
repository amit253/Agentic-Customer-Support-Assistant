"""Scan tracked files and recordings for common credential patterns."""

from __future__ import annotations

import re
import subprocess
import sys
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PATTERNS = (
    re.compile(rb"gsk_[A-Za-z0-9_-]{20,}"),
    re.compile(rb"sk-[A-Za-z0-9]{20,}"),
    re.compile(rb"gh[pousr]_[A-Za-z0-9]{20,}"),
    re.compile(rb"github_pat_[A-Za-z0-9_]{20,}"),
    re.compile(rb"AKIA[A-Z0-9]{16}"),
    re.compile(rb"(?i)bearer\s+[A-Za-z0-9._~+/=-]{24,}"),
)
SAFE_TEST_PLACEHOLDERS = {
    b"gsk_primary_fake_value",
    b"gsk_secondary_fake_value",
}


def _contents(path: Path) -> list[bytes]:
    if zipfile.is_zipfile(path):
        with zipfile.ZipFile(path) as archive:
            return [
                archive.read(member)
                for member in archive.namelist()
                if not member.endswith("/")
            ]
    return [path.read_bytes()]


def main() -> int:
    tracked = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=ROOT,
        check=True,
        capture_output=True,
    ).stdout.decode("utf-8").split("\0")
    untracked = subprocess.run(
        ["git", "ls-files", "--others", "--exclude-standard", "-z"],
        cwd=ROOT,
        check=True,
        capture_output=True,
    ).stdout.decode("utf-8").split("\0")
    candidates = {
        ROOT / name for name in (*tracked, *untracked) if name
    }
    recordings = ROOT / "recordings"
    if recordings.is_dir():
        candidates.update(path for path in recordings.rglob("*") if path.is_file())

    findings: list[str] = []
    placeholder_matches = 0
    scanned = 0
    for path in sorted(candidates):
        if not path.is_file():
            continue
        scanned += 1
        matches = {
            match.group(0)
            for content in _contents(path)
            for pattern in PATTERNS
            for match in pattern.finditer(content)
        }
        placeholder_matches += len(matches & SAFE_TEST_PLACEHOLDERS)
        if matches - SAFE_TEST_PLACEHOLDERS:
            findings.append(str(path.relative_to(ROOT)))

    print(
        {
            "files_scanned": scanned,
            "allowlisted_synthetic_test_placeholder_shapes": placeholder_matches,
            "secret_pattern_files": findings,
        }
    )
    if findings:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
