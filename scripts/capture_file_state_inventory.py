#!/usr/bin/env python3
"""Inventory private field writes and mutation sites before the b2 state refactor."""

import argparse
import ast
import hashlib
import json
from pathlib import Path

from capture_file_state_trace import git_metadata


class Inventory(ast.NodeVisitor):
    def __init__(self):
        self.scope = []
        self.entries = []

    def visit_ClassDef(self, node):
        self.scope.append(node.name)
        self.generic_visit(node)
        self.scope.pop()

    def visit_FunctionDef(self, node):
        self.scope.append(node.name)
        self.generic_visit(node)
        self.scope.pop()

    visit_AsyncFunctionDef = visit_FunctionDef

    def record(self, node, target, kind):
        if any(
            isinstance(part, (ast.Attribute, ast.Name)) for part in ast.walk(target)
        ):
            self.entries.append(
                {
                    "line": node.lineno,
                    "scope": ".".join(self.scope),
                    "kind": kind,
                    "target": ast.unparse(target),
                }
            )

    def visit_Assign(self, node):
        for target in node.targets:
            self.record(node, target, "assignment")
        self.generic_visit(node)

    def visit_AnnAssign(self, node):
        self.record(node, node.target, "annotated assignment")
        self.generic_visit(node)

    def visit_AugAssign(self, node):
        self.record(node, node.target, "augmented assignment")
        self.generic_visit(node)

    def visit_Delete(self, node):
        for target in node.targets:
            self.record(node, target, "deletion")
        self.generic_visit(node)

    def visit_Call(self, node):
        if isinstance(node.func, ast.Attribute) and node.func.attr in {
            "clear",
            "extend",
            "append",
            "discard",
            "set_result",
            "set_exception",
            "cancel",
            "close",
            "_advance_raw",
        }:
            self.record(node, node.func, "mutation/completion call")
        if isinstance(node.func, ast.Name) and node.func.id in {"setattr", "delattr"}:
            self.entries.append(
                {
                    "line": node.lineno,
                    "scope": ".".join(self.scope),
                    "kind": "dynamic attribute mutation",
                    "target": ast.unparse(node),
                }
            )
        self.generic_visit(node)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    root = args.source_root.resolve()
    modules = {}
    for name in ("_binary.py", "_text.py", "_codec_async.py"):
        path = root / "src/aiogzip" / name
        visitor = Inventory()
        visitor.visit(ast.parse(path.read_text(encoding="utf-8")))
        modules[name] = {
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "sites": visitor.entries,
        }
    record = {
        "source": git_metadata(root),
        "harness": git_metadata(Path(__file__).resolve().parents[1]),
        "harness_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "modules": modules,
        "scope": "All attribute and local assignment targets, deletes, common buffer mutations, and completion calls. Local aliases are retained in targets; semantic ownership and mutating helper effects require the design record.",
    }
    with args.output.open("x", encoding="utf-8") as output:
        json.dump(record, output, indent=2)
        output.write("\n")


if __name__ == "__main__":
    main()
