"""
phase2_discovery.py - Phase 2: Discovery and structuring.

Goal: from the files Phase 1 kept, infer languages, find manifests, and split the
repository into sub-projects.

Read-only: uses paths from FilterResult only. It never walks the disk again and
never sees skipped paths (so a package.json inside node_modules cannot appear).

Also reads manifest / workspace file *contents* for kept paths only, to expand
npm/pnpm, Go, Cargo, and .NET monorepos.
"""
from __future__ import annotations

import json
import re
import tomllib
from collections import Counter
from pathlib import Path, PurePosixPath

from .models import DiscoveryResult, FilterResult, LanguageCount, SubProject
from .phase1_filter import read_text

# Exact manifest file names (lockfiles are intentionally absent).
MANIFEST_NAMES: frozenset[str] = frozenset({
    "pyproject.toml", "setup.py", "setup.cfg", "requirements.txt", "Pipfile",
    "package.json",
    "go.mod", "go.work",
    "Cargo.toml",
    "pom.xml", "build.gradle", "build.gradle.kts", "settings.gradle",
    "Gemfile",
    "composer.json",
    "Package.swift",
    "CMakeLists.txt",
    "pnpm-workspace.yaml",
    "nx.json",
})

# Nested requirements.txt does not define its own sub-project root.
WEAK_MANIFEST_NAMES: frozenset[str] = frozenset({"requirements.txt"})

WORKSPACE_FILENAMES: frozenset[str] = frozenset({
    "package.json", "pnpm-workspace.yaml", "go.work", "Cargo.toml",
})

# Manifest basename -> language when no source files are present yet.
MANIFEST_LANGUAGE: dict[str, str] = {
    "pyproject.toml": "Python",
    "setup.py": "Python",
    "setup.cfg": "Python",
    "requirements.txt": "Python",
    "Pipfile": "Python",
    "package.json": "JavaScript",
    "go.mod": "Go",
    "go.work": "Go",
    "Cargo.toml": "Rust",
    "pom.xml": "Java",
    "build.gradle": "Java",
    "build.gradle.kts": "Kotlin",
    "settings.gradle": "Java",
    "Gemfile": "Ruby",
    "composer.json": "PHP",
    "Package.swift": "Swift",
    "CMakeLists.txt": "C/C++",
    "pnpm-workspace.yaml": "JavaScript",
    "nx.json": "JavaScript",
}

# Kept-file suffix -> language (aligned with Phase 1 source extensions).
SUFFIX_LANGUAGE: dict[str, str] = {
    ".py": "Python",
    ".pyi": "Python",
    ".js": "JavaScript",
    ".jsx": "JavaScript",
    ".ts": "TypeScript",
    ".tsx": "TypeScript",
    ".java": "Java",
    ".go": "Go",
    ".rs": "Rust",
    ".c": "C/C++",
    ".h": "C/C++",
    ".cpp": "C/C++",
    ".hpp": "C/C++",
    ".cs": "C#",
    ".rb": "Ruby",
    ".php": "PHP",
    ".kt": "Kotlin",
    ".swift": "Swift",
}

_SLN_PROJECT = re.compile(
    r'Project\("\{[^}]*\}"\)\s*=\s*"[^"]*"\s*,\s*"([^"]+)"\s*,',
    re.IGNORECASE,
)


def _is_manifest(rel_path: str) -> bool:
    name = PurePosixPath(rel_path).name
    if name in MANIFEST_NAMES:
        return True
    lower = name.lower()
    return lower.endswith(".csproj") or lower.endswith(".fsproj") or lower.endswith(".sln")


def _manifest_creates_root(rel_path: str) -> bool:
    """Whether this manifest defines a new sub-project directory."""
    name = PurePosixPath(rel_path).name
    parent = _subproject_root(rel_path)
    if name in WEAK_MANIFEST_NAMES:
        return parent == ""
    return _is_manifest(rel_path)


def _subproject_root(manifest_path: str) -> str:
    parent = PurePosixPath(manifest_path).parent.as_posix()
    return "" if parent == "." else parent


def _assign_subproject(file_path: str, roots: list[str]) -> str:
    """Longest sub-project directory that contains this file (prefix match)."""
    best = ""
    best_len = -1
    for root in roots:
        if root == "":
            continue
        prefix = root + "/"
        if file_path == root or file_path.startswith(prefix):
            if len(root) > best_len:
                best = root
                best_len = len(root)
    return best


def _language_counts(paths: list[str], manifests: list[str]) -> list[LanguageCount]:
    counts: Counter[str] = Counter()
    for rel in paths:
        suffix = PurePosixPath(rel).suffix.lower()
        lang = SUFFIX_LANGUAGE.get(suffix)
        if lang:
            counts[lang] += 1
    for manifest in manifests:
        name = PurePosixPath(manifest).name
        if name.endswith(".csproj") or name.endswith(".fsproj"):
            lang = "C#"
        elif name.endswith(".sln"):
            lang = "C#"
        else:
            lang = MANIFEST_LANGUAGE.get(name)
        if lang and counts[lang] == 0:
            counts[lang] = 1
    return [LanguageCount(language=k, count=v) for k, v in sorted(counts.items())]


def _posix_join(root: str, leaf: str) -> str:
    leaf = leaf.replace("\\", "/").strip().strip("./")
    if not root:
        return leaf
    return f"{root}/{leaf}".strip("/") if leaf else root


def _immediate_child_dirs(prefix: str, kept: list[str]) -> set[str]:
    """Directories one level under prefix that contain kept files."""
    prefix = prefix.replace("\\", "/").strip("./")
    if prefix:
        prefix_slash = prefix + "/"
    else:
        prefix_slash = ""
    out: set[str] = set()
    for p in kept:
        if prefix_slash and not p.startswith(prefix_slash):
            if p != prefix:
                continue
        rest = p[len(prefix_slash):] if prefix_slash else p
        if not rest:
            if prefix:
                out.add(prefix)
            continue
        first = rest.split("/")[0]
        out.add(_posix_join(prefix, first))
    return out


def _dirs_from_workspace_pattern(pattern: str, kept: list[str]) -> set[str]:
    pattern = pattern.replace("\\", "/").strip().strip("'\"").strip()
    if not pattern:
        return set()
    if pattern.endswith("/*"):
        return _immediate_child_dirs(pattern[:-2], kept)
    if pattern.endswith("/**"):
        prefix = pattern[:-3].rstrip("/")
        dirs: set[str] = set()
        prefix_slash = (prefix + "/") if prefix else ""
        for p in kept:
            if prefix_slash and not p.startswith(prefix_slash):
                continue
            if prefix:
                dirs.add(prefix)
            dirs.add(p[: p.rfind("/")] if "/" in p else p)
        return {d for d in dirs if d and (not prefix or d == prefix or d.startswith(prefix_slash))}
    if any(ch in pattern for ch in "*?[]"):
        return _immediate_child_dirs(pattern.split("*")[0].rstrip("/"), kept)
    return {pattern} if any(p == pattern or p.startswith(pattern + "/") for p in kept) else set()


def _read_kept(root: Path, rel: str, kept_set: set[str]) -> str | None:
    if rel not in kept_set:
        return None
    try:
        return read_text(root, rel)
    except OSError:
        return None


def _parse_package_workspaces(text: str) -> list[str]:
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return []
    ws = data.get("workspaces")
    if ws is None:
        return []
    if isinstance(ws, list):
        return [str(x) for x in ws]
    if isinstance(ws, dict):
        packs = ws.get("packages")
        if isinstance(packs, list):
            return [str(x) for x in packs]
    return []


def _parse_pnpm_workspace(text: str) -> list[str]:
    patterns: list[str] = []
    in_packages = False
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("packages:"):
            in_packages = True
            continue
        if in_packages:
            if stripped and not stripped.startswith("-") and ":" in stripped:
                break
            if stripped.startswith("-"):
                patterns.append(stripped.lstrip("-").strip().strip("'\""))
    return patterns


def _parse_go_work(text: str) -> list[str]:
    dirs: list[str] = []
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("use "):
            payload = line[4:].strip()
            if payload.startswith("("):
                continue
            dirs.append(payload.rstrip(")").strip().strip("'\""))
        elif line.startswith("./") or line.startswith("../"):
            dirs.append(line.strip())
    return dirs


def _parse_cargo_workspace(text: str) -> list[str]:
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError:
        return []
    members = data.get("workspace", {}).get("members", [])
    if not isinstance(members, list):
        return []
    return [str(m) for m in members]


def _parse_sln_projects(text: str) -> list[str]:
    paths: list[str] = []
    for m in _SLN_PROJECT.finditer(text):
        raw = m.group(1).replace("\\", "/")
        if raw.lower().endswith((".csproj", ".fsproj", ".vcxproj")):
            paths.append(raw)
    return paths


def _csproj_root(csproj_path: str) -> str:
    return _subproject_root(csproj_path)


def _expand_workspaces(
    repo_root: Path,
    kept: list[str],
    kept_set: set[str],
    manifest_paths: list[str],
) -> set[str]:
    """Extra sub-project directories declared by workspace files (kept paths only)."""
    extra: set[str] = set()
    candidates: list[tuple[str, str]] = []
    for rel in manifest_paths:
        name = PurePosixPath(rel).name
        if name in WORKSPACE_FILENAMES or name.endswith(".sln"):
            candidates.append((name, rel))

    for name, rel in candidates:
        text = _read_kept(repo_root, rel, kept_set)
        if not text:
            continue
        sp_root = _subproject_root(rel)
        patterns: list[str] = []
        if name == "package.json":
            patterns = _parse_package_workspaces(text)
        elif name == "pnpm-workspace.yaml":
            patterns = _parse_pnpm_workspace(text)
        elif name == "go.work":
            patterns = _parse_go_work(text)
        elif name == "Cargo.toml":
            patterns = _parse_cargo_workspace(text)
        elif name.endswith(".sln"):
            for csproj in _parse_sln_projects(text):
                if csproj in kept_set or any(p.endswith(csproj) or p == csproj for p in kept):
                    extra.add(_csproj_root(csproj))
            continue

        for pattern in patterns:
            for d in _dirs_from_workspace_pattern(pattern, kept):
                extra.add(_posix_join(sp_root, d) if sp_root and not d.startswith(sp_root) else d)

    # Normalize: only directories that have kept content or a manifest
    manifest_roots = {_subproject_root(m) for m in manifest_paths if _manifest_creates_root(m)}
    for path in list(extra):
        if not (
            any(p == path or p.startswith(path + "/") for p in kept)
            or path in manifest_roots
            or any(_subproject_root(m) == path for m in manifest_paths)
        ):
            extra.discard(path)
    return extra


def _manifest_home(rel_path: str, nested_roots: list[str]) -> str:
    """Sub-project that owns this manifest for listing (weak manifests nest inside parents)."""
    if _manifest_creates_root(rel_path):
        return _subproject_root(rel_path)
    parent = PurePosixPath(rel_path).parent.as_posix()
    parent = "" if parent == "." else parent
    return _assign_subproject(parent or rel_path, nested_roots)


def discover(filter_result: FilterResult) -> DiscoveryResult:
    """Discover languages, manifests, and sub-projects from a Phase 1 result."""
    repo_root = Path(filter_result.root)
    kept_paths = [e.path for e in filter_result.files]
    kept_set = set(kept_paths)
    manifest_paths = sorted(p for p in kept_paths if _is_manifest(p))

    sp_roots = {_subproject_root(m) for m in manifest_paths if _manifest_creates_root(m)}
    sp_roots |= _expand_workspaces(repo_root, kept_paths, kept_set, manifest_paths)
    sp_roots_sorted = sorted(sp_roots, key=lambda r: (r.count("/"), r))

    warnings: list[str] = []
    if not kept_paths:
        warnings.append("No kept files to discover.")

    projects: dict[str, SubProject] = {}
    if kept_paths:
        projects[""] = SubProject(path="")
    for root in sp_roots_sorted:
        if root and root not in projects:
            projects[root] = SubProject(path=root)

    nested_roots = [r for r in sp_roots_sorted if r]
    for manifest in manifest_paths:
        home = _manifest_home(manifest, nested_roots)
        if home not in projects:
            projects[home] = SubProject(path=home)
        if manifest not in projects[home].manifests:
            projects[home].manifests.append(manifest)
    for sp in projects.values():
        sp.manifests.sort()

    for rel in kept_paths:
        assign = _assign_subproject(rel, nested_roots)
        if assign not in projects:
            projects[assign] = SubProject(path=assign)
        projects[assign].files.append(rel)

    for sp in projects.values():
        sp.files.sort()
        sp.languages = _language_counts(sp.files, sp.manifests)

    sub_projects = []
    for root in sorted(projects.keys(), key=lambda r: (r.count("/"), r)):
        sp = projects[root]
        if root and not sp.files and not sp.manifests:
            continue
        sub_projects.append(sp)

    if kept_paths and not manifest_paths:
        has_source = any(SUFFIX_LANGUAGE.get(PurePosixPath(p).suffix.lower()) for p in kept_paths)
        if has_source:
            warnings.append("No manifest file found among kept files; treating the repository as one root sub-project.")

    repo_langs = _language_counts(kept_paths, manifest_paths)

    return DiscoveryResult(
        root=filter_result.root,
        fingerprint=filter_result.fingerprint,
        languages=repo_langs,
        sub_projects=sub_projects,
        warnings=warnings,
    )
