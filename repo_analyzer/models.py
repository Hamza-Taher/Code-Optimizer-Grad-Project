"""
models.py - data shapes produced by each repo-analyzer phase.

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


# --------------------------------------------------------------------------- #
# Phase 2: Discovery and structuring
# --------------------------------------------------------------------------- #


class LanguageCount(BaseModel):
    """How many kept source files use a given language label."""
    language: str
    count: int


class SubProject(BaseModel):
    """One buildable unit inside the repository (the repo root counts as one)."""
    path: str = ""  # relative directory; "" is the repository root
    languages: list[LanguageCount] = Field(default_factory=list)
    manifests: list[str] = Field(default_factory=list)  # kept manifest paths in this unit
    files: list[str] = Field(default_factory=list)      # all kept paths assigned here


class DiscoveryResult(BaseModel):
    """Output of phase 2."""
    root: str
    fingerprint: str = ""  # copied from phase 1 so later phases can correlate snapshots
    languages: list[LanguageCount] = Field(default_factory=list)       # whole repo
    sub_projects: list[SubProject] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


# from __future__ import annotations
from dataclasses import dataclass, field

@dataclass
class AstFact:
    node_type: str
    name: str
    lineno: int
    col_offset: int = 0

@dataclass
class SecurityRisk:
    risk_type: str
    message: str
    lineno: int

@dataclass
class FileAnalysisResult:
    file_path: str
    ast_facts: list[AstFact] = field(default_factory=list)
    risks: list[SecurityRisk] = field(default_factory=list)

@dataclass
class StaticAnalysisResult:
    root: str
    file_results: list[FileAnalysisResult] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


    

# --------------------------------------------------------------------------- #
# Phase 4: Recipe extraction
# --------------------------------------------------------------------------- #


class Recipe(BaseModel):
    """How to install and test one sub-project."""
    sub_project: str = ""   # relative directory; "" is the repository root
    ecosystem: str          # e.g. "python"
    install_commands: list[str] = Field(default_factory=list)
    test_commands: list[str] = Field(default_factory=list)
    confidence: Literal["high", "medium", "low"] = "low"
    evidence: list[str] = Field(default_factory=list)  # why we think so


class RecipeResult(BaseModel):
    """Output of phase 4."""
    root: str
    fingerprint: str = ""
    recipes: list[Recipe] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)