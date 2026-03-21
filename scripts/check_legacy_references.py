#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
import re
import sys


REPO_ROOT = Path(__file__).resolve().parents[1]
LEGACY_PATTERN = re.compile(r"Synthia|synthia")

# This guard intentionally focuses on active code and developer-entry docs.
# Historical/archive docs are allowed to retain legacy naming.
SCANNED_PATHS = (
    "src",
    "frontend/src",
    "scripts",
    "tests",
    "README.md",
    "docs/index.md",
)

SKIP_DIR_NAMES = {
    "__pycache__",
    ".git",
    ".venv",
    "node_modules",
    "dist",
    "build",
}

TEXT_SUFFIXES = {
    ".py",
    ".js",
    ".jsx",
    ".ts",
    ".tsx",
    ".sh",
    ".md",
    ".json",
    ".txt",
    ".env",
    ".example",
    ".in",
}

ALLOWED_LINE_PATTERNS = (
    re.compile(r"X-Synthia-(Node-Id|Admin-Token)"),
    re.compile(r"synthia-ai-node-(backend|frontend)\.service"),
    re.compile(r"synthia-ai-node-control-api"),
    re.compile(r"Synthia Core"),
    re.compile(r"Compatibility-sensitive identifiers such as"),
    re.compile(r"synthia_theme"),
    re.compile(r"/home/dan/Projects/SynthiaAiNode"),
    re.compile(r"/path/to/SynthiaCore"),
    re.compile(r"\.\./Synthia"),
    re.compile(r"`Synthia` naming"),
)


def _should_scan(path: Path) -> bool:
    if path.is_dir():
        return False
    if any(part in SKIP_DIR_NAMES for part in path.parts):
        return False
    if path.suffix in TEXT_SUFFIXES:
        return True
    return path.name in {"README.md"}


def _iter_scan_files() -> list[Path]:
    files: list[Path] = []
    for relative_path in SCANNED_PATHS:
        path = REPO_ROOT / relative_path
        if path.is_file():
            files.append(path)
            continue
        if path.is_dir():
            files.extend(candidate for candidate in path.rglob("*") if _should_scan(candidate))
    return sorted(set(files))


def _is_allowed_line(line: str) -> bool:
    return any(pattern.search(line) for pattern in ALLOWED_LINE_PATTERNS)


def main() -> int:
    failures: list[str] = []
    for path in _iter_scan_files():
        relative_path = path.relative_to(REPO_ROOT)
        if relative_path == Path("scripts/check_legacy_references.py"):
            continue
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except UnicodeDecodeError:
            continue
        for line_number, line in enumerate(lines, start=1):
            if not LEGACY_PATTERN.search(line):
                continue
            if _is_allowed_line(line):
                continue
            failures.append(f"{relative_path}:{line_number}: {line.strip()}")
    if failures:
        print("Unexpected legacy Synthia references found in active code/docs:", file=sys.stderr)
        for failure in failures:
            print(f"  {failure}", file=sys.stderr)
        return 1
    print("Legacy reference guard passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
