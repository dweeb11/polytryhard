import ast
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
CORE_ROOT = REPO_ROOT / "core"
WRITER_PATH = CORE_ROOT / "ledger" / "writer.py"


def _assign_targets(node: ast.AST) -> list[str]:
    if isinstance(node, ast.Assign):
        targets = node.targets
    elif isinstance(node, ast.AugAssign):
        targets = [node.target]
    else:
        return []
    names: list[str] = []
    for target in targets:
        if isinstance(target, ast.Attribute) and target.attr == "bankroll_cents":
            names.append("bankroll_cents")
        if isinstance(target, ast.Name) and target.id == "bankroll_cents":
            names.append("bankroll_cents")
    return names


def test_bankroll_cents_assignments_only_in_writer() -> None:
    violations: list[str] = []
    for path in CORE_ROOT.rglob("*.py"):
        if path == WRITER_PATH:
            continue
        source = path.read_text(encoding="utf-8")
        if "bankroll_cents" in source and path != WRITER_PATH:
            if "UPDATE" in source and "bankroll_cents" in source:
                violations.append(f"{path}: SQL UPDATE mentions bankroll_cents")
        tree = ast.parse(source, filename=str(path))
        for node in ast.walk(tree):
            if _assign_targets(node):
                violations.append(f"{path}: bankroll_cents assignment")
    assert violations == []
