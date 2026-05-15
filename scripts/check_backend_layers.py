#!/usr/bin/env python3
"""
Check backend layering rules for FastAPI routers.

Routers must not import repositories directly. They should go through services:
router -> service -> repository -> model.
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ROUTERS_DIR = ROOT / "app" / "api" / "v1" / "routers"
FORBIDDEN_PREFIX = "app.repositories"


def _import_name(node: ast.AST) -> str | None:
    if isinstance(node, ast.ImportFrom):
        return node.module
    if isinstance(node, ast.Import):
        for alias in node.names:
            if alias.name.startswith(FORBIDDEN_PREFIX):
                return alias.name
    return None


def find_violations() -> list[tuple[Path, int, str]]:
    violations: list[tuple[Path, int, str]] = []
    for path in sorted(ROUTERS_DIR.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            name = _import_name(node)
            if name and name.startswith(FORBIDDEN_PREFIX):
                violations.append((path, node.lineno, name))
    return violations


def main() -> int:
    violations = find_violations()
    if not violations:
        print("Backend layer check passed: routers do not import app.repositories.")
        return 0

    print("Backend layer check failed: routers import app.repositories directly.")
    for path, line, name in violations:
        print(f"{path.relative_to(ROOT)}:{line}: {name}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
