from __future__ import annotations

import ast
from pathlib import Path
from .models import AstFact, FileAnalysisResult, SecurityRisk, StaticAnalysisResult
from .phase1_filter import read_text

class _CodeVisitor(ast.NodeVisitor):
    def __init__(self) -> None:
        self.facts: list[AstFact] = []
        self.risks: list[SecurityRisk] = []

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self.facts.append(AstFact(
            node_type="FunctionDef",
            name=node.name,
            lineno=node.lineno,
            col_offset=node.col_offset
        ))
        self.generic_visit(node)

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self.facts.append(AstFact(
            node_type="ClassDef",
            name=node.name,
            lineno=node.lineno,
            col_offset=node.col_offset
        ))
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        if isinstance(node.func, ast.Name):
            if node.func.id in {"eval", "exec"}:
                self.risks.append(SecurityRisk(
                    risk_type="Dangerous Execution",
                    message=f"Usage of dangerous built-in function '{node.func.id}' detected.",
                    lineno=node.lineno
                ))
        self.generic_visit(node)

def analyze_file(repo_root: Path, rel_path: str) -> FileAnalysisResult:
    try:
        source_code = read_text(repo_root, rel_path)
    except Exception:
        return FileAnalysisResult(file_path=rel_path)

    try:
        tree = ast.parse(source_code, filename=rel_path)
    except SyntaxError as e:
        return FileAnalysisResult(
            file_path=rel_path,
            risks=[SecurityRisk(risk_type="SyntaxError", message=str(e), lineno=e.lineno or 1)]
        )

    visitor = _CodeVisitor()
    visitor.visit(tree)

    return FileAnalysisResult(
        file_path=rel_path,
        ast_facts=visitor.facts,
        risks=visitor.risks
    )

def analyze_repository(discovery_result) -> StaticAnalysisResult:
    repo_root = Path(discovery_result.root)
    file_results: list[FileAnalysisResult] = []
    warnings: list[str] = []

    all_files = []
    for sp in discovery_result.sub_projects:
        for f in sp.files:
            if f.endswith(".py"):
                all_files.append(f)

    if not all_files:
        warnings.append("No Python files found for static analysis.")

    for rel_path in sorted(set(all_files)):
        file_results.append(analyze_file(repo_root, rel_path))

    return StaticAnalysisResult(
        root=discovery_result.root,
        file_results=file_results,
        warnings=warnings
    )