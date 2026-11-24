"""
phase5_sandbox.py - Phase 5: Sandbox verification.

Goal: take the recipes from Phase 4 and PROVE them in a locked-down Docker container:
  1. install the project into a fresh virtualenv,
  2. list its tests (pytest --collect-only, nothing is run),
  3. if that fails, ask for ONE revised recipe and try again ("retry once").
Then record what actually happened and give each recipe a measured confidence.

This is the first phase that EXECUTES something (purple in the diagram), so:
  * Only a copy of the files Phase 1 kept is mounted. Never the original repo.
  * Every command must match a tiny allowlist. Anything else is rejected, not run.
  * Commands run as argv lists inside Docker. There is never a shell on the host.
  * Container: non-root, all capabilities dropped, read-only root filesystem,
    CPU / memory / process limits, a timeout, and capped output.
  * Network: ON only for the install step (pip must reach PyPI), OFF for everything else.
"""
from __future__ import annotations

import os
import re
import shlex
import shutil
import subprocess
import tempfile
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Literal

from .models import DiscoveryResult, Recipe, RecipeResult

# =========================================================================== #
# Settings and result types
# =========================================================================== #

# The only command shapes Phase 5 will run. Phase 4 produces exactly these.
_INSTALL_ALLOWED = (
    re.compile(r"pip install -r requirements\.txt"),
    re.compile(r"pip install (-e )?\."),
)
_TEST_ALLOWED = frozenset({"pytest"})

_VENV_PY = "/venv/bin/python"

Status = Literal["verified", "partial", "failed", "skipped"]
Confidence = Literal["high", "medium", "low"]


@dataclass(frozen=True)
class SandboxOptions:
    image: str = "python:3.11-slim"
    install_network: str = "bridge"   # "none" if you use a pre-built wheel cache instead
    install_timeout: int = 600        # seconds
    collect_timeout: int = 120
    memory: str = "1g"
    cpus: str = "1"
    pids_limit: int = 256
    max_output_chars: int = 20_000    # keep the END of the output (that is where errors are)
    max_attempts: int = 2             # first try + ONE retry


@dataclass
class StepResult:
    name: str                 # venv | install | install_pytest | collect
    argv: list[str]
    network: str
    exit_code: int
    timed_out: bool
    duration_s: float
    output: str               # truncated

    @property
    def ok(self) -> bool:
        return self.exit_code == 0 and not self.timed_out


@dataclass
class VerifiedRecipe:
    sub_project: str
    recipe: Recipe                      # the recipe that was actually used (maybe revised)
    status: Status
    confidence: Confidence              # MEASURED, not guessed
    tests_collected: int | None
    attempts: int
    steps: list[StepResult] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


@dataclass
class SandboxResult:
    root: str
    fingerprint: str
    results: list[VerifiedRecipe] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


# A "revise" hook gets the failed recipe and its step results and returns a NEW recipe,
# or None to give up. This is where the Phase 4 "LLM helper" plugs in later.
Revise = Callable[[Recipe, list[StepResult]], "Recipe | None"]


def default_revise(recipe: Recipe, steps: list[StepResult]) -> Recipe | None:
    """Deterministic first retry: switch 'pip install .' to an editable install."""
    if "pip install ." not in recipe.install_commands:
        return None
    cmds = ["pip install -e ." if c == "pip install ." else c for c in recipe.install_commands]
    return Recipe(
        sub_project=recipe.sub_project,
        ecosystem=recipe.ecosystem,
        install_commands=cmds,
        test_commands=list(recipe.test_commands),
        confidence=recipe.confidence,
        evidence=[*recipe.evidence, "retry: switched 'pip install .' to 'pip install -e .'"],
    )


# =========================================================================== #
# Docker helpers
# =========================================================================== #


def docker_available() -> bool:
    if not shutil.which("docker"):
        return False
    try:
        return subprocess.run(["docker", "info"], capture_output=True, timeout=20).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def _docker_run(
    name: str,
    argv: list[str],
    *,
    work: Path,
    venv: str,          # name of a docker volume
    cwd: str,
    network: str,
    timeout: int,
    opts: SandboxOptions,
) -> StepResult:
    container = f"p5-{uuid.uuid4().hex[:12]}"
    cmd = [
        "docker", "run", "--rm", "--name", container,
        "--network", network,
        "--cap-drop", "ALL",
        "--security-opt", "no-new-privileges",
        "--read-only",
        "--tmpfs", "/tmp:rw,size=256m",
        "--pids-limit", str(opts.pids_limit),
        "--memory", opts.memory,
        "--cpus", opts.cpus,
        "-e", "HOME=/tmp",
        "-e", "PIP_DISABLE_PIP_VERSION_CHECK=1",
        "-e", "PYTHONDONTWRITEBYTECODE=1",
    ]
    if hasattr(os, "getuid"):  # run as the current non-root user (not available on Windows)
        cmd += ["--user", f"{os.getuid()}:{os.getgid()}"]
    cmd += [
        "-v", f"{work}:/work",
        "-v", f"{venv}:/venv",
        "-w", f"/work/{cwd}" if cwd else "/work",
        opts.image, *argv,
    ]

    start = time.monotonic()
    timed_out = False
    try:
        proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=timeout)
        code, raw = proc.returncode, proc.stdout
    except subprocess.TimeoutExpired as e:
        timed_out, code, raw = True, -1, e.stdout or b""
        try:
            subprocess.run(["docker", "kill", container], capture_output=True, timeout=30)
        except (OSError, subprocess.TimeoutExpired):
            pass
    except OSError as e:
        code, raw = -1, str(e).encode()

    text = raw.decode("utf-8", errors="replace")[-opts.max_output_chars:]
    return StepResult(
        name=name, argv=argv, network=network, exit_code=code, timed_out=timed_out,
        duration_s=round(time.monotonic() - start, 2), output=text,
    )


@contextmanager
def _venv_volume(opts: SandboxOptions):
    """A throw-away Docker volume that holds the virtualenv.
    A volume (not a host folder) avoids Windows failing on the venv's symlinks."""
    name = f"p5-venv-{uuid.uuid4().hex[:12]}"
    subprocess.run(["docker", "volume", "create", name], capture_output=True, check=True, timeout=30)
    try:
        if hasattr(os, "getuid"):  # Linux/Mac: let the non-root user write into the new volume
            subprocess.run(
                ["docker", "run", "--rm", "--user", "0:0", "-v", f"{name}:/venv", opts.image,
                 "chown", f"{os.getuid()}:{os.getgid()}", "/venv"],
                capture_output=True, timeout=60,
            )
        yield name
    finally:
        subprocess.run(["docker", "volume", "rm", "-f", name], capture_output=True, timeout=60)


def _materialize(root: Path, discovery: DiscoveryResult, dest: Path) -> None:
    """Copy ONLY the files Phase 1 kept. Symlinks and paths that escape `dest` are refused."""
    dest_resolved = dest.resolve()
    seen: set[str] = set()
    for sp in discovery.sub_projects:
        for rel in sp.files:
            if rel in seen:
                continue
            seen.add(rel)
            src = root / rel
            if src.is_symlink() or not src.is_file():
                continue
            target = dest / rel
            if not target.resolve().is_relative_to(dest_resolved):
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, target)


# =========================================================================== #
# One attempt = plan -> run -> judge
# =========================================================================== #


def _plan(recipe: Recipe, opts: SandboxOptions) -> tuple[list[tuple[str, list[str], str, int]], list[str]]:
    """Turn a recipe into (step name, argv, network, timeout) tuples. Reject anything off-list."""
    plan: list[tuple[str, list[str], str, int]] = [
        ("venv", ["python", "-m", "venv", "/venv"], "none", 120),
    ]
    errors: list[str] = []

    for cmd in recipe.install_commands:
        if any(p.fullmatch(cmd) for p in _INSTALL_ALLOWED):
            plan.append(("install", [_VENV_PY, "-m", *shlex.split(cmd)], opts.install_network, opts.install_timeout))
        else:
            errors.append(f"install command rejected by allowlist: {cmd!r}")

    wants_pytest = False
    for cmd in recipe.test_commands:
        if cmd in _TEST_ALLOWED:
            wants_pytest = True
        else:
            errors.append(f"test command rejected by allowlist: {cmd!r}")

    if wants_pytest:
        # Phase 4 never installs pytest, so make sure it exists (no-op if already installed).
        plan.append(("install_pytest", [_VENV_PY, "-m", "pip", "install", "pytest"],
                     opts.install_network, opts.install_timeout))
        # Listing, not running: nothing is executed except collection (which imports test modules).
        plan.append(("collect", [_VENV_PY, "-m", "pytest", "--collect-only", "-q", "-p", "no:cacheprovider"],
                     "none", opts.collect_timeout))
    return plan, errors


def _count_tests(output: str) -> int:
    m = re.search(r"(\d+) tests? collected", output)
    if m:
        return int(m.group(1))
    return sum(1 for line in output.splitlines() if "::" in line and not line.startswith(" "))


def _run_attempt(
    recipe: Recipe, discovery: DiscoveryResult, root: Path, opts: SandboxOptions
) -> tuple[list[StepResult], bool, int | None, list[str]]:
    """Returns (steps, install_ok, tests_collected, notes). Stops at the first failing step."""
    plan, errors = _plan(recipe, opts)
    if errors:
        return [], False, None, errors

    steps: list[StepResult] = []
    notes: list[str] = []
    install_ok = True
    collected: int | None = None

    with tempfile.TemporaryDirectory(prefix="phase5_", ignore_cleanup_errors=True) as tmp, \
            _venv_volume(opts) as venv:
        work = Path(tmp) / "work"
        work.mkdir()
        _materialize(root, discovery, work)

        if recipe.sub_project and not (work / recipe.sub_project).is_dir():
            return [], False, None, [f"sub-project folder not found in the copy: {recipe.sub_project!r}"]

        for name, argv, network, timeout in plan:
            step = _docker_run(name, argv, work=work, venv=venv, cwd=recipe.sub_project,
                               network=network, timeout=timeout, opts=opts)
            steps.append(step)
            if name == "collect":
                if step.ok:
                    collected = _count_tests(step.output)
                elif step.exit_code == 5:       # pytest: "no tests were collected"
                    collected = 0
                else:
                    notes.append(f"test listing failed (exit {step.exit_code}"
                                 f"{', timed out' if step.timed_out else ''})")
                break
            if not step.ok:
                install_ok = False
                notes.append(f"step '{name}' failed (exit {step.exit_code}"
                             f"{', timed out' if step.timed_out else ''})")
                break
    return steps, install_ok, collected, notes


def _judge(recipe: Recipe, install_ok: bool, collected: int | None, errors: bool) -> tuple[Status, Confidence]:
    if errors or not install_ok:
        return "failed", "low"
    if recipe.test_commands and collected and collected > 0:
        return "verified", "high"
    return "partial", "medium"   # installs fine, but tests could not be listed (or none exist)


def verify_recipe(
    recipe: Recipe,
    discovery: DiscoveryResult,
    root: Path,
    opts: SandboxOptions,
    revise: Revise | None = default_revise,
) -> VerifiedRecipe:
    if not recipe.install_commands and not recipe.test_commands:
        return VerifiedRecipe(recipe.sub_project, recipe, "skipped", "low", None, 0,
                              notes=["recipe has no commands, nothing to verify"])

    current = recipe
    all_steps: list[StepResult] = []
    notes: list[str] = []
    attempts = 0

    while True:
        attempts += 1
        steps, install_ok, collected, attempt_notes = _run_attempt(current, discovery, root, opts)
        all_steps += steps
        notes += [f"attempt {attempts}: {n}" for n in attempt_notes]
        has_errors = bool(attempt_notes) and not steps   # rejected before running anything
        status, confidence = _judge(current, install_ok, collected, has_errors)

        if status == "verified" or attempts >= opts.max_attempts or revise is None or has_errors:
            break
        revised = revise(current, steps)
        if revised is None:
            break
        notes.append(f"attempt {attempts} was {status}; retrying with a revised recipe")
        current = revised

    return VerifiedRecipe(recipe.sub_project, current, status, confidence, collected, attempts,
                          steps=all_steps, notes=notes)


# =========================================================================== #
# The phase
# =========================================================================== #


def verify_recipes(
    discovery: DiscoveryResult,
    recipes: RecipeResult,
    options: SandboxOptions | None = None,
    revise: Revise | None = default_revise,
) -> SandboxResult:
    """Verify every Phase 4 recipe in the sandbox and return measured results."""
    opts = options or SandboxOptions()
    root = Path(discovery.root)
    out = SandboxResult(root=discovery.root, fingerprint=discovery.fingerprint)

    if not recipes.recipes:
        out.warnings.append("No recipes to verify.")
        return out

    if not docker_available():
        out.warnings.append("Docker is not available; nothing was executed. Start Docker and re-run.")
        for r in recipes.recipes:
            out.results.append(VerifiedRecipe(r.sub_project, r, "skipped", "low", None, 0,
                                              notes=["docker unavailable"]))
        return out

    for r in recipes.recipes:
        out.results.append(verify_recipe(r, discovery, root, opts, revise))
    return out