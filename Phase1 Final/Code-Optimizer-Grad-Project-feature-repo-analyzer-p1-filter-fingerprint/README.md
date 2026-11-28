# Code-Optimizer-Grad-Project

An enterprise multi-agent system for autonomous source-code refactoring, complexity reduction, and sandboxed test validation.

This repository currently contains **Phase 1 of the repo analyzer: filter and fingerprint**. There is no user interface and no backend yet. Later phases of the same agent are added as new modules inside `repo_analyzer/`, not as new top-level folders.

## Where Phase 1 sits

The platform walks a repository through a repo analyzer, then hands the result to the Step 0 baseline agent. The repo analyzer has six phases. Phase 1 is the first and it is **read-only**: it lists and reads files. It never runs the project, never calls a model, never follows symbolic links, and never opens anything that is not a regular file.

```
Repository source code
    |
    v
Phase 1  Filter and fingerprint            <-- this code
    |
Phase 2  Discovery and structuring (languages, manifests, sub-projects)
    |
Phase 3  Static code analysis
    |
Phase 4  Recipe extraction (install, test, environment)
    |
Phase 5  Sandbox verification
    |
Phase 6  Profile generation
    |
    v
Hand-off to the Step 0 baseline agent
```

Phase 1 has to run first. If vendored code, virtual environments, generated files, or binaries were still visible, a `pyproject.toml` inside `node_modules` or `vendor` would look like one of the project's own sub-projects, and every later phase would waste time (and model calls) on code nobody wrote.

## What Phase 1 does

`filter_repo()` walks the repository from the root and returns three things:

1. **Kept files.** Source and text that later phases are allowed to analyze.
2. **Skipped paths, each with a reason.** A skipped directory is recorded once. Its children are not listed and are not entered.
3. **A fingerprint** of exactly the files that were kept.

The fingerprint is a SHA-256 over each kept file's path and content hash, sorted by path. Changing, renaming, or adding a kept file changes the fingerprint. Changing a file that was skipped does not. An empty result still has a fingerprint, plus the warning `No files left after filtering`.

```python
from repo_analyzer import filter_repo, FilterOptions

result = filter_repo("path/to/repo")                      # defaults
result = filter_repo("path/to/repo", FilterOptions(extra_ignore=("docs/",), max_bytes=500_000))
print(result.fingerprint, len(result.files), result.skipped_counts)
print(result.model_dump_json(indent=2))
```

Command line:

```
python -m repo_analyzer PATH [--exclude PATTERN ...] [--max-bytes N] [--no-gitignore] [-o result.json] [--json]
```

Exit code 2 (with a one-line message) when `PATH` is not a readable directory.

## Repository layout

```
repo_analyzer/
  __init__.py          public exports
  __main__.py          command line
  models.py            pydantic models for each phase
  phase1_filter.py     the walk and the skip rules
tests/
  helpers.py           builds tiny fake repositories for tests
  test_phase1.py       Phase 1 tests
requirements.txt
pytest.ini
```

Every phase returns a pydantic model instead of a plain dictionary. That is the contract between phases and between teammates. `result.model_dump_json()` is the JSON form.

`phase1_filter.py` reads top to bottom in four sections: **1. Settings** (every list and limit you may want to tune), **2. Ignore rules**, **3. Decisions** (small functions answering "skip this folder / file?"), **4. `filter_repo()`** (the walk). Most edits touch only section 1 or one function in section 3.

## How a path is decided

Directories are judged before the walk enters them. The first matching reason wins:

| Order | Reason | What matches |
|---|---|---|
| 1 | `ignored_dir` | `.git`, `.hg`, `.svn`, `__pycache__`, `.tox`, `.nox`, `.mypy_cache`, `.pytest_cache`, `.ruff_cache`, `.hypothesis`, `htmlcov`, `.eggs`, `__pypackages__`, `.ipynb_checkpoints`, `build`, `dist`, `.idea`, `.vscode`, `.next`, `.nuxt`, `.svelte-kit`, `.parcel-cache`, `.turbo`, `.nyc_output`, `.yarn`, `.pnpm-store`, `.gradle`, `.terraform`, `.dart_tool`, `.cache`, a name ending in `.egg-info`, or `target` **when a `Cargo.toml` or `pom.xml` sits next to it** |
| 2 | `virtualenv` | Named `venv` or `.venv`, or the folder contains `pyvenv.cfg` or a `conda-meta` folder (so an environment with any other name is still found) |
| 3 | `vendor` | `vendor`, `vendors`, `third_party`, `third-party`, `thirdparty`, `node_modules`, `bower_components`, `site-packages` (compared in lower case) |
| 4 | `nested_repo` | The folder has its own `.git` file or directory (a submodule or a copied checkout). The repository root's own `.git` is not treated as a nested repo |
| 5 | `gitignored` | Matched by a `.gitignore` that applies to this folder |
| 6 | `user_ignored` | Matched by `.analyzerignore` or by `--exclude` |

Symbolic links and Windows junctions are never followed: a link to a folder is recorded as `symlink` and not entered (this is checked before everything above). A folder named `env` is not a virtualenv unless it contains `pyvenv.cfg`. `build` and `dist` are always skipped by name, including a real source package that happens to use one of those names. Name-based skips cannot be overridden by an ignore file; if you need one of those folders analyzed, edit `SKIP_DIR_NAMES` (or `VENDOR_DIR_NAMES`) at the top of `phase1_filter.py`.

Files inside a folder that was not skipped are judged in this order:

| Order | Reason | What matches |
|---|---|---|
| 1 | `unreadable` | The name is not valid Unicode (it could not be stored in JSON or hashed) |
| 2 | `symlink` | Symbolic link or junction. The target is not read |
| 3 | `gitignored` | Matched by `.gitignore` |
| 4 | `user_ignored` | Matched by `.analyzerignore` or `--exclude` |
| 5 | `binary` | Extension is in the binary list below |
| 6 | `generated` | Name matches a generated-file pattern |
| 7 | `unreadable` | Not a regular file (named pipe, socket, device), or `stat`/read failed |
| 8 | `too_large` | Larger than `max_bytes` (default 1,000,000) |
| 9 | `binary` | A NUL byte appears in the first 8 KB, even if the extension looks like source |
| 10 | `generated` | A source file whose first 5 lines say it was machine-generated |

A folder that cannot be listed (for example permission denied) is recorded once as `unreadable`; it is never silently dropped. If the **root** itself cannot be read, `filter_repo` raises the error.

Anything that survives is kept. Each kept file is stored as a `FileEntry`:

| Field | Meaning |
|---|---|
| `path` | Path relative to the repo root, always with `/` separators |
| `size` | Size in bytes (of the bytes that were hashed) |
| `sha256` | SHA-256 of the raw file bytes |
| `suffix` | Lower-case extension, such as `.py`. Empty string when there is no extension |

### Binary extensions

`.png .jpg .jpeg .gif .bmp .ico .webp .svgz .tif .tiff .heic .avif .psd .pdf` ·
`.zip .gz .tgz .bz2 .xz .7z .tar .rar .whl .egg .iso .dmg .apk .ipa .deb .rpm .msi .nupkg .gem` ·
`.so .dll .dylib .exe .bin .o .a .lib .obj .pdb .node .wasm .pyc .pyo .pyd .class .jar .war .ear` ·
`.woff .woff2 .ttf .otf .eot` · `.mp3 .mp4 .mov .avi .wav .mkv .flac .ogg .webm .m4a` ·
`.sqlite .sqlite3 .db .pkl .pickle .npy .npz .parquet .h5 .hdf5 .onnx .pt .pth .ckpt .safetensors` ·
`.doc .docx .xls .xlsx .ppt .pptx .odt`.

SVG is text, so `.svg` is kept. `.svgz` is compressed and is skipped.

### Generated files

**By file name:** protobuf output (`*_pb2.py`, `*_pb2.pyi`, `*_pb2_grpc.py`, `*.pb.go`, `*.pb.cc`, `*.pb.h`), minified assets and source maps (`*.min.js`, `*.min.css`, `*.js.map`, `*.css.map`), `*.generated.*`, `*.g.cs`, `*.g.dart`, `*.freezed.dart`, `*.designer.cs`, and Kubernetes-style `zz_generated.*`.

**By header,** and only for source extensions (`.py .pyi .js .jsx .ts .tsx .java .go .rs .c .h .cpp .hpp .cs .rb .php .kt .swift .scala .dart .m .mm`): the first 5 lines match `generated by`, `do not edit`, `@generated`, `code generated`, `auto-generated`, or `automatically generated`. A README that says "generated by" is kept, because prose is not in that extension list. A marker past line 5 is ignored.

## Ignore rules

`.gitignore` files are honored by default, including a `.gitignore` in a subfolder. Pass `--no-gitignore` to turn this off.

**Scope.** A pattern is applied relative to the folder that contains its ignore file, so `/only_here.py` inside `sub/.gitignore` ignores `sub/only_here.py` and does not ignore `only_here.py` at the root. Directory patterns such as `out/` match directories.

**Precedence follows git.** The ignore file closest to the path decides. If a deeper file has a rule for the path (ignore *or* `!` re-include), that rule wins over every parent file. So a `!keep.log` in `sub/.gitignore` brings back `sub/keep.log` even though the root `.gitignore` says `*.log`. As in git, a path inside an ignored *folder* cannot be brought back, because the folder is never entered.

**User rules** come from two places, both applied from the repository root:

- a file named `.analyzerignore` in the repo root
- extra patterns passed to `FilterOptions.extra_ignore` or to `--exclude` (the file's lines come last, so its `!` lines can override `--exclude`)

**Hostile input is tolerated.** Ignore files that are symlinks are not read. A UTF-8 BOM is dropped, undecodable bytes are replaced, and one malformed pattern line is skipped with a warning (`Ignored invalid pattern '[z-a]' in ...`) instead of aborting the scan.

**Verified against git.** The ignore logic was compared with real `git ls-files --others --exclude-standard` on randomly generated trees with nested `.gitignore` files and `!` rules: 0 differences in 700 trees built from typical patterns (`*.log`, `build/`, `!keep.log`, `/docs/_build/` ...), and about 0.5% differences in 2,500 trees built from deliberately hostile pattern mixes (`*`, `/*`, `!dir/` combined with other rules across files). The known gap: a `!folder/` rule in a nested `.gitignore` can re-include files inside that folder that a rule in a *parent* `.gitignore` still ignores in git. Fix it by putting both rules in the same file.

Not supported: `.git/info/exclude`, the global git ignore file, and `.gitignore` files above the folder you pass in. Files that git already tracks despite an ignore rule are still treated as ignored, because Phase 1 never talks to git.

## The result

`FilterResult` is the whole output of Phase 1:

| Field | Meaning |
|---|---|
| `root` | Absolute path of the repository that was scanned |
| `files` | Kept `FileEntry` values, sorted by path |
| `skipped` | `SkippedEntry` values: `path` (folders end in `/`), `reason`, `is_dir`. Capped at 500 entries by default |
| `skipped_counts` | Exact count per reason, even when `skipped` was capped |
| `total_bytes` | Sum of the sizes of kept files |
| `fingerprint` | SHA-256 described above |
| `warnings` | Human-readable notes: skipped list truncated, nothing kept, invalid ignore pattern |

`read_text(root, relative_path)` reads a kept file as UTF-8 and replaces bytes that are not valid UTF-8. Later phases use it for manifests and source. It does not re-check the filter, so callers should pass a path that Phase 1 kept.

A path that is not a directory raises `NotADirectoryError`.

## Performance and limits

- Single pass, no recursion (depth is limited only by the operating system's path length). About **0.65 s for 20,000 files** with a 60-pattern `.gitignore` on the development machine; most of that is pattern matching, so very long `.gitignore` files cost proportionally more.
- Each kept file is read once (for the NUL check, the header check and the hash), at most `max_bytes`.
- Line endings are not normalized: the fingerprint hashes raw bytes, so a CRLF checkout and an LF checkout of the same repo have different fingerprints.
- Phase 1 is a heuristic filter, not a security boundary: a file that does not say it is generated, or a vendored folder with an unusual name, will be kept. Use `.analyzerignore` for those.

## Development

```
pip install -r requirements.txt
python -m pytest -q
```
