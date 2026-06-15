"""P3 cycle-23 token-equivalence proof (DS-engine comment+docstring sweep).

For every changed agents/daemon_slayer/*.py file, prove that the working-tree
edit changed ONLY comment tokens and docstring STRING tokens: every other token
(code, operators, NAME, NUMBER, and crucially every NON-docstring STRING literal
- the emitted/regex-matched arrows) must be byte-identical to HEAD.

PASS == the sweep is a provable zero-behavior-change edit. Exit 0 on PASS.
"""
from __future__ import annotations

import ast
import io
import subprocess
import sys
import tokenize
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


def head_bytes(rel: str) -> bytes:
    return subprocess.run(
        ["git", "show", f"HEAD:{rel}"], cwd=REPO, capture_output=True, check=True
    ).stdout


def docstring_spans(text: str):
    tree = ast.parse(text)
    spans = set()

    def _doc(node):
        body = getattr(node, "body", None)
        if (
            body
            and isinstance(body[0], ast.Expr)
            and isinstance(body[0].value, ast.Constant)
            and isinstance(body[0].value.value, str)
        ):
            c = body[0].value
            spans.add((c.lineno, c.end_lineno or c.lineno))

    _doc(tree)
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            _doc(node)
    return spans


def code_tokens(data: bytes):
    """(type, string) for every token that is NOT a comment and NOT a docstring."""
    text = data.decode("utf-8")
    spans = docstring_spans(text)
    out = []
    for tok in tokenize.tokenize(io.BytesIO(data).readline):
        if tok.type == tokenize.COMMENT:
            continue
        if tok.type == tokenize.STRING and any(
            a <= tok.start[0] and tok.end[0] <= b for a, b in spans
        ):
            continue
        out.append((tok.type, tok.string))
    return out


def changed_ds_files():
    out = subprocess.run(
        ["git", "diff", "--name-only", "--", "agents/daemon_slayer"],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    return [f for f in out.splitlines() if f.endswith(".py")]


def main() -> int:
    files = changed_ds_files()
    if not files:
        print("NO CHANGED DS FILES - nothing to prove")
        return 1
    ok = True
    for rel in files:
        pre = code_tokens(head_bytes(rel))
        post = code_tokens((REPO / rel).read_bytes())
        same = pre == post
        ok = ok and same
        print(f"  {'PASS' if same else 'FAIL'}  {rel}  ({len(pre)} code tokens)")
        if not same:
            for i, (a, b) in enumerate(zip(pre, post)):
                if a != b:
                    print(f"    first diff @tok{i}: HEAD={a!r}  WORK={b!r}")
                    break
    print(f"\n{'PROOF PASS' if ok else 'PROOF FAIL'}: {len(files)} files")
    return 0 if ok else 2


if __name__ == "__main__":
    sys.exit(main())
