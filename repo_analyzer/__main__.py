"""Command line:  python -m repo_analyzer PATH [--exclude PATTERN ...] [-o phase1.json] [--json]"""
from __future__ import annotations

import argparse
from pathlib import Path

from .phase1_filter import FilterOptions, filter_repo


def _summary(result) -> str:
    """Short text overview of a FilterResult (phase 1 only)."""
    lines = [
        f"Repository : {result.root}",
        f"Fingerprint: {result.fingerprint[:16]}...  ({len(result.files)} files kept, {result.total_bytes:,} bytes)",
        "Skipped    : " + (", ".join(f"{k}={v}" for k, v in result.skipped_counts.items()) or "nothing"),
    ]
    lines += [f"Warning    : {w}" for w in result.warnings]
    return "\n".join(lines)


def main() -> None:
    ap = argparse.ArgumentParser(prog="repo_analyzer", description="Phase 1: filter and fingerprint.")
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
    result = filter_repo(args.repo, options)
    if args.out:
        args.out.write_text(result.model_dump_json(indent=2), encoding="utf-8")
    print(result.model_dump_json(indent=2) if args.json else _summary(result))


if __name__ == "__main__":
    main()
