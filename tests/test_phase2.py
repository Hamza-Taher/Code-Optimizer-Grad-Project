"""Phase 2 tests: discovery on top of Phase 1."""
from helpers import write

from repo_analyzer import discover, filter_repo


def _discover(tmp_path):
    return discover(filter_repo(tmp_path))


def _sp(discovery, path: str):
    for sp in discovery.sub_projects:
        if sp.path == path:
            return sp
    raise KeyError(path)


def test_single_python_project(tmp_path):
    write(tmp_path, "pyproject.toml", "[project]\nname = 'x'\n")
    write(tmp_path, "src/app.py", "x = 1\n")
    d = _discover(tmp_path)
    root = _sp(d, "")
    assert root.manifests == ["pyproject.toml"]
    assert "src/app.py" in root.files
    assert any(c.language == "Python" and c.count >= 1 for c in d.languages)


def test_monorepo_nested_manifests(tmp_path):
    write(tmp_path, "README.md", "# mono\n")
    write(tmp_path, "pyproject.toml", "[project]\n")
    write(tmp_path, "backend/app.py", "x = 1\n")
    write(tmp_path, "apps/web/package.json", '{"name":"web"}\n')
    write(tmp_path, "apps/web/src/index.ts", "export {};\n")
    d = _discover(tmp_path)
    assert _sp(d, "").files == ["README.md", "backend/app.py", "pyproject.toml"]
    web = _sp(d, "apps/web")
    assert web.manifests == ["apps/web/package.json"]
    assert web.files == ["apps/web/package.json", "apps/web/src/index.ts"]
    assert any(c.language == "TypeScript" for c in web.languages)


def test_node_modules_manifest_not_seen(tmp_path):
    write(tmp_path, "package.json", '{"name":"root"}\n')
    write(tmp_path, "index.js", "console.log(1)\n")
    write(tmp_path, "node_modules/pkg/package.json", '{"name":"dep"}\n')
    d = _discover(tmp_path)
    root = _sp(d, "")
    assert root.manifests == ["package.json"]
    assert "node_modules/pkg/package.json" not in root.files
    assert len(d.sub_projects) == 1


def test_no_manifest_still_one_root_subproject(tmp_path):
    write(tmp_path, "main.py", "print('hi')\n")
    write(tmp_path, "lib/util.py", "def f(): pass\n")
    d = _discover(tmp_path)
    assert len(d.sub_projects) == 1
    assert _sp(d, "").path == ""
    assert any("No manifest" in w for w in d.warnings)


def test_lockfile_is_not_a_manifest(tmp_path):
    write(tmp_path, "package.json", '{"name":"app"}\n')
    write(tmp_path, "package-lock.json", '{}\n')
    write(tmp_path, "poetry.lock", "# lock\n")
    d = _discover(tmp_path)
    root = _sp(d, "")
    assert root.manifests == ["package.json"]
    assert "package-lock.json" in root.files
    assert len(d.sub_projects) == 1


def test_nested_requirements_does_not_create_subproject(tmp_path):
    write(tmp_path, "pyproject.toml", "[project]\n")
    write(tmp_path, "services/api/requirements.txt", "flask\n")
    write(tmp_path, "services/api/app.py", "x = 1\n")
    d = _discover(tmp_path)
    paths = {sp.path for sp in d.sub_projects}
    assert "services/api" not in paths
    root = _sp(d, "")
    assert "services/api/app.py" in root.files
    assert "services/api/requirements.txt" in root.manifests


def test_npm_workspaces_expand_packages(tmp_path):
    write(tmp_path, "package.json", '{"name":"mono","workspaces":["packages/*"]}\n')
    write(tmp_path, "packages/a/package.json", '{"name":"a"}\n')
    write(tmp_path, "packages/a/index.js", "module.exports = 1;\n")
    write(tmp_path, "packages/b/package.json", '{"name":"b"}\n')
    d = _discover(tmp_path)
    a = _sp(d, "packages/a")
    assert "packages/a/index.js" in a.files
    assert "packages/a/package.json" in a.manifests


def test_pnpm_workspace_yaml(tmp_path):
    write(tmp_path, "package.json", '{"name":"mono"}\n')
    write(tmp_path, "pnpm-workspace.yaml", "packages:\n  - 'packages/*'\n")
    write(tmp_path, "packages/web/src/main.ts", "export const x = 1;\n")
    write(tmp_path, "packages/web/package.json", '{"name":"web"}\n')
    d = _discover(tmp_path)
    web = _sp(d, "packages/web")
    assert "packages/web/src/main.ts" in web.files


def test_cargo_workspace_members(tmp_path):
    write(tmp_path, "Cargo.toml", '[workspace]\nmembers = ["crate-a", "crate-b"]\n')
    write(tmp_path, "crate-a/Cargo.toml", '[package]\nname = "a"\n')
    write(tmp_path, "crate-a/src/lib.rs", "pub fn f() {}\n")
    d = _discover(tmp_path)
    ca = _sp(d, "crate-a")
    assert "crate-a/src/lib.rs" in ca.files


def test_deepest_subproject_wins(tmp_path):
    write(tmp_path, "pyproject.toml", "[project]\n")
    write(tmp_path, "services/api/pyproject.toml", "[project]\n")
    write(tmp_path, "services/api/handlers.py", "x = 1\n")
    write(tmp_path, "services/shared/util.py", "y = 2\n")
    d = _discover(tmp_path)
    api = _sp(d, "services/api")
    assert "services/api/handlers.py" in api.files
    assert "services/api/pyproject.toml" in api.manifests
    root = _sp(d, "")
    assert "services/shared/util.py" in root.files
    assert "services/api/handlers.py" not in root.files
