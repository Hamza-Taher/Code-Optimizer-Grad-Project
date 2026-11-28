"""Shared helper for the tests: build files inside a temporary fake repository."""
from pathlib import Path


def write(root: Path, rel: str, text: str | bytes = "") -> Path:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    # newline="\n" keeps the on-disk bytes identical on Windows and Unix.
    p.write_bytes(text) if isinstance(text, bytes) else p.write_text(text, encoding="utf-8", newline="\n")
    return p
