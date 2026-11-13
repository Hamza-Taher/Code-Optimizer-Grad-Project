"""Phase 4 tests: recipe extraction on top of Phases 1 and 2."""
from helpers import write

from repo_analyzer import discover, filter_repo
from repo_analyzer.phase4_recipe import extract_recipes


def _recipes(tmp_path):
    return extract_recipes(discover(filter_repo(tmp_path)))


def _recipe(result, path: str):
    for r in result.recipes:
        if r.sub_project == path:
            return r
    raise KeyError(path)


def test_python_project_with_requirements_and_tests(tmp_path):
    write(tmp_path, "requirements.txt", "flask\n")
    write(tmp_path, "app.py", "x = 1\n")
    write(tmp_path, "tests/test_app.py", "def test_x(): pass\n")
    r = _recipe(_recipes(tmp_path), "")
    assert r.ecosystem == "python"
    assert r.install_commands == ["pip install -r requirements.txt"]
    assert r.test_commands == ["pytest"]
    assert r.confidence == "high"
    assert "found requirements.txt" in r.evidence


def test_pyproject_uses_pip_install_dot(tmp_path):
    write(tmp_path, "pyproject.toml", "[project]\nname = 'x'\n")
    write(tmp_path, "src/app.py", "x = 1\n")
    r = _recipe(_recipes(tmp_path), "")
    assert r.install_commands == ["pip install ."]


def test_install_but_no_tests_is_medium(tmp_path):
    write(tmp_path, "requirements.txt", "flask\n")
    write(tmp_path, "app.py", "x = 1\n")
    r = _recipe(_recipes(tmp_path), "")
    assert r.test_commands == []
    assert r.confidence == "medium"


def test_plain_python_without_manifest_or_tests_is_low(tmp_path):
    write(tmp_path, "main.py", "print('hi')\n")
    r = _recipe(_recipes(tmp_path), "")
    assert r.confidence == "low"
    assert r.install_commands == [] and r.test_commands == []


def test_non_python_project_gets_warning_not_recipe(tmp_path):
    write(tmp_path, "package.json", '{"name":"web"}\n')
    write(tmp_path, "index.js", "console.log(1)\n")
    result = _recipes(tmp_path)
    assert result.recipes == []
    assert any("No recipe support yet" in w for w in result.warnings)


def test_fingerprint_is_copied_from_phase_1(tmp_path):
    write(tmp_path, "app.py", "x = 1\n")
    phase1 = filter_repo(tmp_path)
    result = extract_recipes(discover(phase1))
    assert result.fingerprint == phase1.fingerprint