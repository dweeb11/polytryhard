import ast
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
STRATEGIES_ROOT = REPO_ROOT / "core" / "strategies"

FORBIDDEN_IMPORT_ROOTS = frozenset(
    {
        "sqlalchemy",
        "httpx",
        "core.db",
        "core.ledger",
        "core.sources",
        "core.scheduler",
    }
)


def _strategy_modules() -> list[Path]:
    paths: list[Path] = []
    for path in STRATEGIES_ROOT.rglob("*.py"):
        if path.name in {"registry.py", "weather_utils.py", "__init__.py"}:
            continue
        paths.append(path)
    return paths


def _import_violations(tree: ast.AST, path: Path) -> list[str]:
    violations: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                root = alias.name.split(".")[0]
                if root in FORBIDDEN_IMPORT_ROOTS or alias.name.startswith("core.db"):
                    violations.append(f"{path}: forbidden import {alias.name}")
        elif isinstance(node, ast.ImportFrom):
            if node.module is None:
                continue
            root = node.module.split(".")[0]
            if root in FORBIDDEN_IMPORT_ROOTS or node.module.startswith("core.db"):
                violations.append(f"{path}: forbidden import from {node.module}")
    return violations


def test_strategy_modules_avoid_forbidden_imports() -> None:
    violations: list[str] = []
    for path in _strategy_modules():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        violations.extend(_import_violations(tree, path))
    assert violations == []
