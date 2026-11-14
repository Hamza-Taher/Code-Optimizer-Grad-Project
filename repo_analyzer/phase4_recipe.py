"""Phase 4: Recipe extraction.

Read-only. Looks at the kept files of each sub-project and works out
which commands install and test it. Python only for now.
"""
from __future__ import annotations

import posixpath

from .models import DiscoveryResult, Recipe, RecipeResult, SubProject


def _is_test_file(path: str) -> bool:
    name = posixpath.basename(path)
    folders = path.split("/")[:-1]
    if name.endswith(".py") and (name.startswith("test_") or name.endswith("_test.py")):
        return True
    return "tests" in folders or "test" in folders


def _python_recipe(sp: SubProject) -> Recipe | None:
    # names = {posixpath.basename(f) for f in sp.files}
    prefix = f"{sp.path}/" if sp.path else ""
    names = {f[len(prefix):] for f in sp.files if f.startswith(prefix) and "/" not in f[len(prefix):]}
    is_python = any(lang.language == "Python" for lang in sp.languages)
    if not is_python:
        return None

    install: list[str] = []
    test: list[str] = []
    evidence: list[str] = []

    if "requirements.txt" in names:
        install.append("pip install -r requirements.txt")
        evidence.append("found requirements.txt")
    if "pyproject.toml" in names or "setup.py" in names:
        install.append("pip install .")
        evidence.append("found pyproject.toml or setup.py")

    if any(_is_test_file(f) for f in sp.files):
        test.append("pytest")
        evidence.append("found test files")

    if install and test:
        confidence = "high"
    elif install or test:
        confidence = "medium"
    else:
        confidence = "low"
        evidence.append("no install file and no tests found")

    return Recipe(
        sub_project=sp.path,
        ecosystem="python",
        install_commands=install,
        test_commands=test,
        confidence=confidence,
        evidence=evidence,
    )


def extract_recipes(discovery: DiscoveryResult) -> RecipeResult:
    recipes: list[Recipe] = []
    warnings: list[str] = []

    for sp in discovery.sub_projects:
        recipe = _python_recipe(sp)
        if recipe is None:
            warnings.append(f"No recipe support yet for sub-project '{sp.path or '(root)'}'")
        else:
            recipes.append(recipe)

    return RecipeResult(
        root=discovery.root,
        fingerprint=discovery.fingerprint,
        recipes=recipes,
        warnings=warnings,
    )