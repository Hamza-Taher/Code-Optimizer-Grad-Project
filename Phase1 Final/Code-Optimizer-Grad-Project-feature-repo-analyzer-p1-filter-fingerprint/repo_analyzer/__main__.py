"""Command line:  python -m repo_analyzer PATH [--exclude PATTERN ...] [-o result.json] [--json]"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .models import FilterResult
from .phase1_filter import FilterOptions, filter_repo


def _summary(r: FilterResult) -> str:
    """Short text overview of a phase 1 result."""
    lines = [
        f"Repository : {r.root}",
        f"Kept       : {len(r.files)} files, {r.total_bytes:,} bytes",
        f"Fingerprint: {r.fingerprint}",
        "Skipped    : " + (", ".join(f"{k}={v}" for k, v in r.skipped_counts.items()) or "nothing"),
    ]
    lines += [f"Warning    : {w}" for w in r.warnings]
    return "\n".join(lines)


def main() -> None:
    ap = argparse.ArgumentParser(prog="repo_analyzer", description="Repo analyzer, phase 1: filter and fingerprint.")
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
    try:
        result = filter_repo(args.repo, options)
    except OSError as exc:          # not a directory, or the root itself cannot be read
        print(f"error: {exc}", file=sys.stderr)
        sys.exit(2)
    if args.out:
        args.out.write_text(result.model_dump_json(indent=2), encoding="utf-8")
    print(result.model_dump_json(indent=2) if args.json else _summary(result))


if __name__ == "__main__":
    main()
