# Code-Optimizer-Grad-Project

An enterprise multi-agent system for autonomous source-code refactoring, complexity reduction, and sandboxed test validation.

This repository currently contains **Phases 1 and 2 of the repo analyzer**: filter and fingerprint, then discovery and structuring. There is no user interface and no backend yet. Later phases of the same agent are added as new modules inside `repo_analyzer/`, not as new top-level folders.

## Where Phases 1 and 2 sit

The platform walks a repository through a repo analyzer, then hands the result to the Step 0 baseline agent. The repo analyzer itself has six phases. Phase 1 is the first of those, and it is read-only: it lists and reads files. It never runs the project, never calls a model, and never follows symbolic links.

```
Repository
    |
    v
Phase 1  Filter and fingerprint
    |
    v
Phase 2  Discovery (languages, manifests, sub-projects)   <-- this code
    |
    v
Phases 3–6, then hand-off to the Step 0 baseline agent
```

Phase 1 has to run before discovery. If vendored code, virtual environments, generated files, or binaries were still visible, a `pyproject.toml` inside `node_modules` or `vendor` would look like one of the project's own sub-projects.

Phase 2 only sees paths from `FilterResult.files`. It never walks the disk again.

## What Phase 1 does

`filter_repo()` walks the repository from the root and returns three things:

1. **Kept files.** Source and text that later phases are allowed to analyze.
2. **Skipped paths, each with a reason.** A skipped directory is recorded once. Its children are not listed and are not entered.
3. **A fingerprint** of exactly the files that were kept.

The fingerprint is a SHA-256 over each kept file's path and content hash, sorted by path. Changing, renaming, or adding a kept file changes the fingerprint. Changing a file that was skipped does not. An empty result still has a fingerprint, plus the warning `No files left after filtering.`

## Repository layout

```
repo_analyzer/
  __init__.py          public exports
  __main__.py          command line
  models.py            pydantic models for each phase
  phase1_filter.py     the walk and the skip rules
  phase2_discovery.py  languages, manifests, sub-projects
tests/
  helpers.py           builds tiny fake repositories for tests
  test_phase1.py       Phase 1 tests
  test_phase2.py       Phase 2 tests
requirements.txt
pytest.ini
```

Every phase returns a pydantic model instead of a plain dictionary. That is the contract between phases and between teammates. `result.model_dump_json()` is the JSON form.

## How a path is decided

Directories are judged before the walk enters them. The first matching reason wins:

| Order | Reason | What matches |
| --- | --- | --- |
| 1 | `symlink` | The directory is a symbolic link. It is not followed. |
| 2 | `ignored_dir` | `.git`, `.hg`, `.svn`, `__pycache__`, `.tox`, `.nox`, `.mypy_cache`, `.pytest_cache`, `.ruff_cache`, `.hypothesis`, `htmlcov`, `.eggs`, `build`, `dist`, or a name ending in `.egg-info` |
| 3 | `virtualenv` | Named `venv` or `.venv`, or the folder contains `pyvenv.cfg` (so a virtualenv with any other name is still found) |
| 4 | `vendor` | `vendor`, `vendors`, `third_party`, `third-party`, `thirdparty`, `node_modules`, `bower_components`, `site-packages` (compared in lower case) |
| 5 | `nested_repo` | The folder has its own `.git` file or directory (a submodule or a copied checkout). The repository root's own `.git` is not treated as a nested repo. |
| 6 | `gitignored` | Matched by a `.gitignore` that applies to this folder |
| 7 | `user_ignored` | Matched by `.analyzerignore` or by `--exclude` |

A folder named `env` is not a virtualenv unless it contains `pyvenv.cfg`. `build` and `dist` are always skipped by name, including a real source package that happens to use one of those names.

Files inside a folder that was not skipped are judged in this order:

| Order | Reason | What matches |
| --- | --- | --- |
| 1 | `symlink` | Symbolic link. The target is not read. |
| 2 | `gitignored` | Matched by `.gitignore` |
| 3 | `user_ignored` | Matched by `.analyzerignore` or `--exclude` |
| 4 | `binary` | Extension is in the binary list below |
| 5 | `generated` | Name matches a generated-file pattern |
| 6 | `too_large` | Larger than `max_bytes` (default 1,000,000) |
| 7 | `unreadable` | Stat or read failed |
| 8 | `binary` | A NUL byte appears in the first 8 KB, even if the extension looks like source |
| 9 | `generated` | A source file whose first 5 lines say it was machine-generated |

Anything that survives is kept. Each kept file is stored as a `FileEntry`:

| Field | Meaning |
| --- | --- |
| `path` | Path relative to the repo root, always with `/` separators |
| `size` | Size in bytes |
| `sha256` | SHA-256 of the raw file bytes |
| `suffix` | Lower-case extension, such as `.py`. Empty string when there is no extension |

### Binary extensions

`.png`, `.jpg`, `.jpeg`, `.gif`, `.bmp`, `.ico`, `.webp`, `.svgz`, `.pdf`, `.zip`, `.gz`, `.tgz`, `.bz2`, `.xz`, `.7z`, `.tar`, `.rar`, `.whl`, `.egg`, `.so`, `.dll`, `.dylib`, `.exe`, `.bin`, `.o`, `.a`, `.obj`, `.pyc`, `.pyo`, `.pyd`, `.class`, `.jar`, `.war`, `.woff`, `.woff2`, `.ttf`, `.otf`, `.eot`, `.mp3`, `.mp4`, `.mov`, `.avi`, `.wav`, `.sqlite`, `.db`, `.pkl`, `.npy`, `.parquet`.

SVG is text, so `.svg` is kept. `.svgz` is compressed and is skipped.

### Generated files

By file name: protobuf output (`*_pb2.py`, `*_pb2.pyi`, `*_pb2_grpc.py`), minified assets (`*.min.js`, `*.min.css`), and `*.generated.*`.

By header, and only for source extensions (`.py`, `.pyi`, `.js`, `.jsx`, `.ts`, `.tsx`, `.java`, `.go`, `.rs`, `.c`, `.h`, `.cpp`, `.hpp`, `.cs`, `.rb`, `.php`, `.kt`, `.swift`): the first 5 lines match `generated by`, `do not edit`, `@generated`, `code generated`, `auto-generated`, or `automatically generated`. A README that says "generated by" is kept, because prose is not in that extension list. A marker past line 5 is ignored.

## Ignore rules

`.gitignore` files are honored by default, including a `.gitignore` in a subfolder. A pattern is applied relative to the folder that contains that ignore file, so `/only_here.py` inside `sub/.gitignore` ignores `sub/only_here.py` and does not ignore `only_here.py` at the root. Directory patterns such as `out/` match directories. Pass `--no-gitignore` to turn this off.

User rules come from two places, both applied from the repository root:

- a file named `.analyzerignore` in the repo root
- extra patterns passed to `FilterOptions.extra_ignore` or to `--exclude`

**Known limit:** a `!` rule inside one ignore file can re-include a file. A `!` rule in a nested `.gitignore` cannot bring back a path that a parent ignore file already matched. The first matching ignore file wins.

## The result

`FilterResult` is the whole output of Phase 1:

| Field | Meaning |
| --- | --- |
| `root` | Absolute path of the repository that was scanned |
| `files` | Kept `FileEntry` values |
| `skipped` | `SkippedEntry` values: `path`, `reason`, `is_dir`. Capped at 500 entries by default |
| `skipped_counts` | Exact count per reason, even when `skipped` was capped |
| `total_bytes` | Sum of the sizes of kept files |
| `fingerprint` | SHA-256 described above |
| `warnings` | Human-readable notes. One is added when the skipped list is truncated. Another is added when nothing was kept |

`read_text(root, relative_path)` reads a kept file as UTF-8 and replaces bytes that are not valid UTF-8. Later phases use it for manifests and source. It does not re-check the filter, so callers should pass a path that Phase 1 kept.

A path that is not a directory raises `NotADirectoryError`.

## What Phase 2 does

`discover(filter_result)` takes the `FilterResult` from Phase 1 and returns:

1. **Repo-level languages.** Counts of kept source files by language, inferred from the file extension.
2. **Manifests.** Known project files among the kept paths only.
3. **Sub-projects.** One entry per buildable unit. The repository root is a unit when it has a manifest or when files are not under a nested unit.

### Manifest files (kept paths only)

| Ecosystem | Names |
| --- | --- |
| Python | `pyproject.toml`, `setup.py`, `setup.cfg`, `requirements.txt` (see below), `Pipfile` |
| JavaScript / TypeScript | `package.json`, `pnpm-workspace.yaml`, `nx.json` |
| Go | `go.mod`, `go.work` |
| Rust | `Cargo.toml` (including `[workspace] members`) |
| Java / Kotlin | `pom.xml`, `build.gradle`, `build.gradle.kts`, `settings.gradle` |
| .NET | `*.csproj`, `*.fsproj`, `*.sln` |
| Ruby | `Gemfile` |
| PHP | `composer.json` |
| Swift | `Package.swift` |
| C / C++ | `CMakeLists.txt` |

Lockfiles such as `package-lock.json`, `poetry.lock`, `go.sum`, and `Cargo.lock` are **not** manifests. They stay as ordinary kept files on the root sub-project when Phase 1 kept them.

A directory that contains a **strong** manifest is a sub-project root. Exception: `requirements.txt` only creates a root at the **repository root**; a nested `requirements.txt` is still listed on the owning sub-project but does **not** open a new unit by itself.

**Workspace expansion** (read-only parse of kept files): Phase 2 reads these when they were kept by Phase 1 and adds sub-project directories they declare:

- `package.json` → `workspaces` (array or `packages` list)
- `pnpm-workspace.yaml` → `packages:` globs
- `go.work` → `use` paths
- `Cargo.toml` → `[workspace].members`
- `*.sln` → project paths ending in `.csproj` / `.fsproj`

Each kept file is assigned to the **deepest** sub-project whose folder contains it. Anything else stays on the root sub-project (`path` is `""`).

Languages come from extensions (`.py` → Python, `.ts` / `.tsx` → TypeScript, and so on). If a sub-project has a manifest but no matching source files yet, the manifest still adds its ecosystem language with count `1`.

Phase 2 still does **not** parse dependency versions or scripts inside manifests; that belongs to later phases. It only uses content to find **where** sub-projects live.

If there are kept source files but no manifest, Phase 2 still creates one root sub-project and adds the warning `No manifest file found among kept files; treating the repository as one root sub-project.`

### Phase 2 result

| Field | Meaning |
| --- | --- |
| `root` | Repository root (same as Phase 1) |
| `fingerprint` | Copied from Phase 1 |
| `languages` | Repo-wide `LanguageCount` list |
| `sub_projects` | `SubProject` list |
| `warnings` | Phase 2 notes only |

Each `SubProject` has `path` (`""` for root), `languages`, `manifests`, and `files` (every kept path assigned to that unit).

## Run it

Python 3.11 or newer. From the repository root:

```bash
py -m pip install -r requirements.txt
py -m repo_analyzer PATH
```

Useful flags:

```bash
py -m repo_analyzer PATH --exclude "legacy/" --exclude "*.log"
py -m repo_analyzer PATH --max-bytes 500000
py -m repo_analyzer PATH --no-gitignore
py -m repo_analyzer PATH --json
py -m repo_analyzer PATH -o analyze.json
```

The command always runs Phase 1 and then Phase 2. With `--json`, output is one JSON object with `phase1` and `phase2` keys. `-o` writes that object to a file. Without `--json`, the text summary adds languages and one line per sub-project.

From Python:

```python
from repo_analyzer import FilterOptions, discover, filter_repo, read_text

phase1 = filter_repo("path/to/repo", FilterOptions(extra_ignore=("legacy/",)))
phase2 = discover(phase1)
print(phase2.languages)
print(phase2.sub_projects[0].manifests)
text = read_text(phase1.root, phase1.files[0].path)
```

## Tests

```bash
py -m pytest
```

The tests build a tiny fake repository per case. They cover directory skips, nested `.gitignore` scope, `.analyzerignore` and `--exclude`, virtualenv detection by marker file, vendor and nested repos, binary extension and NUL-byte detection, generated names and headers, the size limit, fingerprint stability, and the skipped-list cap.

Phase 2 tests cover single and nested projects, npm/pnpm/Cargo workspaces, nested `requirements.txt`, vendor paths, lockfiles, and deepest sub-project assignment.

On Windows, two Phase 1 tests are skipped: creating a symlink needs a privilege this environment does not grant, and the unreadable-file case depends on POSIX permissions. Both still run on Linux and macOS. The last full run here was **28 passed, 2 skipped**.

## What is not implemented yet

AST facts, injection filtering, recipe extraction, sandbox installs, and profile generation belong to repo-analyzer phases 3–6. Cleaning, test writing, and optimization belong to later agents. Phases 1–2 only narrow the repository to kept files and describe its structure for those later steps.
