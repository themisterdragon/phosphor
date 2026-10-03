#!/usr/bin/env python3
"""Phosphor supports Python 3.8+. Parse every source file as 3.8 would, and look for the newer
syntax the parser's feature_version setting doesn't catch: f-strings that reuse their own quote
character, or hold a backslash or a line break, inside {} (3.12+), and parenthesized
multi-item `with` statements (3.10+)."""
import ast
import pathlib
import sys

root = pathlib.Path(__file__).resolve().parent.parent
problems = []


def where(path, node):
    return f"{path.relative_to(root)}:{node.lineno}"


for path in sorted((root / "src").rglob("*.py")):
    source = path.read_text(encoding="utf-8")
    try:
        tree = ast.parse(source, str(path), feature_version=(3, 8))
    except SyntaxError as e:
        problems.append(f"{path.relative_to(root)}:{e.lineno}: {e.msg}")
        continue
    for node in ast.walk(tree):
        if isinstance(node, ast.JoinedStr):
            whole = ast.get_source_segment(source, node) or ""
            body = whole.lstrip("rRbBuUfF")
            quote = body[:3] if body[:3] in ('"""', "'''") else body[:1]
            for part in node.values:
                if isinstance(part, ast.FormattedValue):
                    inner = ast.get_source_segment(source, part.value) or ""
                    if quote in inner or "\\" in inner or ("\n" in inner and len(quote) == 1):
                        problems.append(f"{where(path, node)}: f-string expression needs Python 3.12: {inner[:40]}")
        elif isinstance(node, ast.With) and len(node.items) > 1:
            text = ast.get_source_segment(source, node) or ""
            if text.startswith("with (") and " as " in text[:text.find(")")]:
                problems.append(f"{where(path, node)}: parenthesized `with` needs Python 3.10")

for p in problems:
    print(p)
print("ok: nothing newer than Python 3.8" if not problems else f"{len(problems)} problem(s)")
sys.exit(1 if problems else 0)
