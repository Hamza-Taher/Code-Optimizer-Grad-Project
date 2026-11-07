"""
models.py - the data shapes produced by phase 1 (filter and fingerprint).

Every phase returns a pydantic model instead of a loose dict. That gives you:
  * a clear contract between phases (and between teammates),
  * automatic validation,
  * free JSON output (`model.model_dump_json()`).
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

# --------------------------------------------------------------------------- #
# Phase 1: Filter and fingerprint
# --------------------------------------------------------------------------- #

# Why a path was NOT analyzed. Keeping the reason (not just dropping the file) lets a human
# audit the filter and lets later phases explain themselves.
SkipReason = Literal[
    "ignored_dir",   # caches, VCS data, build output (fixed list of folder names)
    "virtualenv",    # a Python virtual environment (folder contains pyvenv.cfg, or is named venv/.venv)
    "vendor",        # third-party code copied into the repo (vendor/, node_modules/, ...)
    "nested_repo",   # a folder with its own .git: a submodule or a vendored checkout
    "gitignored",    # matched by a .gitignore rule
    "user_ignored",  # matched by .analyzerignore or an --exclude pattern
    "symlink",       # symbolic links are never followed
    "binary",        # images, archives, compiled files, or content with NUL bytes
    "generated",     # machine-written code (protobuf output, "DO NOT EDIT" headers, minified files)
    "too_large",     # bigger than the size limit
    "unreadable",    # permission or I/O error
]


class FileEntry(BaseModel):
    """A file that passed the filter and will be analyzed."""
    path: str      # relative to the repo root, always with "/" separators
    size: int      # bytes
    sha256: str    # hash of the file content (feeds the fingerprint)
    suffix: str    # lower-case extension, e.g. ".py" ("" if none)


class SkippedEntry(BaseModel):
    path: str
    reason: SkipReason
    is_dir: bool   # a skipped directory counts once; its contents are not listed


class FilterResult(BaseModel):
    """Output of phase 1."""
    root: str
    files: list[FileEntry] = Field(default_factory=list)
    skipped: list[SkippedEntry] = Field(default_factory=list)   # may be truncated (see warnings)
    skipped_counts: dict[str, int] = Field(default_factory=dict)  # exact counts per reason
    total_bytes: int = 0
    fingerprint: str = ""    # SHA-256 over every kept file's path and content hash
    warnings: list[str] = Field(default_factory=list)
