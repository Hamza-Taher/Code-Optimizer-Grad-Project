"""Command line:  python -m repo_analyzer PATH [--exclude PATTERN ...] [-o out.json] [--json]"""
from __future__ import annotations

import argparse
from pathlib import Path

from pydantic import BaseModel

from .models import DiscoveryResult, FilterResult
from .phase1_filter import FilterOptions, filter_repo
from .phase2_discovery import discover


class AnalyzeOutput(BaseModel):
    phase1: FilterResult
    phase2: DiscoveryResult


def _lang_line(counts) -> str:
    if not counts:
        return "(none)"
    return ", ".join(f"{c.language}={c.count}" for c in counts)


def _summary(phase1, phase2) -> str:
    """Short text overview after Phase 1 and Phase 2."""
    lines = [
        f"Repository : {phase1.root}",
        f"Fingerprint: {phase1.fingerprint[:16]}...  ({len(phase1.files)} files kept, {phase1.total_bytes:,} bytes)",
        "Skipped    : " + (", ".join(f"{k}={v}" for k, v in phase1.skipped_counts.items()) or "nothing"),
        f"Languages  : {_lang_line(phase2.languages)}",
    ]
    for sp in phase2.sub_projects:
        label = sp.path or "(root)"
        mans = ", ".join(sp.manifests) if sp.manifests else "no manifest"
        lines.append(f"Sub-project: {label}  [{mans}]  files={len(sp.files)}  langs={_lang_line(sp.languages)}")
    for w in phase1.warnings + phase2.warnings:
        lines.append(f"Warning    : {w}")
    return "\n".join(lines)


def main() -> None:
    ap = argparse.ArgumentParser(prog="repo_analyzer", description="Repo analyzer phases 1–2.")
    ap.add_argument("repo", type=Path, help="path to the repository")
    ap.add_argument("--exclude", action="append", default=[], metavar="PATTERN",
                    help=".gitignore-style pattern to skip (repeatable)")
    ap.add_argument("--max-bytes", type=int, default=FilterOptions.max_bytes, help="skip files larger than this")
    ap.add_argument("--no-gitignore", action="store_true", help="do not honor .gitignore files")
    ap.add_argument("-o", "--out", type=Path, help="write the full JSON result to this file")
    ap.add_argument("--json", action="store_true", help="print JSON instead of the text summary")
    args = ap.parse_args()

    options = FilterOptions(max_bytes=args.max_bytes, extra_ignore=tuple(args.exclude),
                            use_gitignore=not args.no_gitignore)
    phase1 = filter_repo(args.repo, options)
    phase2 = discover(phase1)
    payload = AnalyzeOutput(phase1=phase1, phase2=phase2)
    text = payload.model_dump_json(indent=2)
    if args.out:
        args.out.write_text(text, encoding="utf-8")
    if args.json:
        print(text)
    else:
        print(_summary(phase1, phase2))


if __name__ == "__main__":
    main()
