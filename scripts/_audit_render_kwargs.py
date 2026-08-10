"""Detect duplicate keyword arguments in render_template calls."""
import ast
from pathlib import Path


class DupKwargVisitor(ast.NodeVisitor):
    def __init__(self, path):
        self.path = path
        self.issues = []

    def visit_Call(self, node):
        if isinstance(node.func, ast.Name) and node.func.id == "render_template":
            keys = []
            for kw in node.keywords:
                if kw.arg:
                    keys.append(kw.arg)
            seen = set()
            dups = []
            for k in keys:
                if k in seen:
                    dups.append(k)
                seen.add(k)
            if dups:
                self.issues.append((node.lineno, sorted(set(dups))))
        self.generic_visit(node)


issues = []
for p in Path(".").rglob("*.py"):
    if "venv" in p.parts or "__pycache__" in p.parts:
        continue
    try:
        tree = ast.parse(p.read_text(encoding="utf-8"))
    except SyntaxError:
        continue
    v = DupKwargVisitor(p)
    v.visit(tree)
    for lineno, dups in v.issues:
        issues.append((str(p), lineno, dups))

print("=== DUPLICATE render_template KWARGS ===")
for path, lineno, dups in issues:
    print(f"  {path}:{lineno} -> {dups}")
print(f"Total: {len(issues)}")
