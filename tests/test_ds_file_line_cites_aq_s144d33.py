"""Guard: the P1-L11 DS pick consumption test cites its coaches by symbol (RM-1053).

Measured 2026-10-31 at ENGINE 1.290.0. tests/test_ds_pick_consumption_p1l11.py
(written 2026-05-19 at 7362f0992) cited the two inline DS-picks splices it
mirrors by line, in two helper docstrings, under a comment that called
"keeping this next to the source line numbers" deliberate:

- ``coach_integration/_coach.py:327-328`` - the conditional append
  (``if _ds_picks_str != "unavailable":`` then ``user += f"...DS top
  items..."``) in ``CoachIntegration._run``. Exact when written; now 26
  lines lower.
- ``coaches/brawl_coach.py:417-434`` - the ``user = (...)`` prompt
  expression in ``Coach._run_coach`` whose last term is the unconditional
  DS top items f-string. Exact when written; now 58 lines lower.

The tests below ratchet the file to zero line cites, pin the symbol cites,
re-derive both restated splice shapes by AST, and confirm the original
cites were exact at the authoring commit.
"""
from __future__ import annotations

import ast
import re
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

_PY_LINE = re.compile(r"(?<![\w./])[\w/]+\.py:\s?\d")
_PROSE_LINE = re.compile(r"\blines? ~?\d{2,}")

TARGET = "tests/test_ds_pick_consumption_p1l11.py"
SR = "coach_integration/_coach.py"
BRAWL = "coaches/brawl_coach.py"
AUTHORED_SHA = "7362f0992"
DS_LINE = "DS top items ("

NEEDLES = (
    "# next to the source symbols is deliberate: if a coach changes how",
    '    """coach_integration._coach.CoachIntegration._run - conditional',
    '    """coaches.brawl_coach.Coach._run_coach - the ``user = (...)``',
)


def _text(rel: str) -> str:
    return (REPO / rel).read_text(encoding="utf-8")


def _method(rel: str, cls: str, name: str) -> ast.FunctionDef:
    for node in ast.parse(_text(rel)).body:
        if isinstance(node, ast.ClassDef) and node.name == cls:
            for sub in node.body:
                if isinstance(sub, ast.FunctionDef) and sub.name == name:
                    return sub
    raise AssertionError(f"{cls}.{name} not defined in {rel}")


def _has_ds_fstring(node: ast.AST) -> bool:
    return any(
        isinstance(sub, ast.JoinedStr) and DS_LINE in ast.unparse(sub)
        for sub in ast.walk(node)
    )


def test_patterns_match_the_rotted_shapes():
    for sample in (
        '    """coach_integration/_coach.py:327-328 - conditional append, the',
        '    """coaches/brawl_coach.py:417-434 - inline f-string, the DS line is',
    ):
        assert _PY_LINE.search(sample), sample
    for needle in NEEDLES:
        assert not _PY_LINE.search(needle), needle
        assert not _PROSE_LINE.search(needle), needle


def test_target_cites_by_symbol():
    text = _text(TARGET)
    hits = [
        i for i, line in enumerate(text.splitlines(), 1)
        if _PY_LINE.search(line) or _PROSE_LINE.search(line)
    ]
    assert hits == [], hits
    for needle in NEEDLES:
        assert needle in text, needle


def test_sr_run_appends_the_ds_line_only_when_available():
    func = _method(SR, "CoachIntegration", "_run")
    guarded = [
        node for node in ast.walk(func)
        if isinstance(node, ast.If)
        and ast.unparse(node.test) == "_ds_picks_str != 'unavailable'"
    ]
    assert len(guarded) == 1, len(guarded)
    body = guarded[0].body
    assert len(body) == 1 and isinstance(body[0], ast.AugAssign)
    assert ast.unparse(body[0].target) == "user"
    assert _has_ds_fstring(body[0].value)
    appends = [
        node for node in ast.walk(func)
        if isinstance(node, (ast.Assign, ast.AugAssign)) and _has_ds_fstring(node)
    ]
    assert appends == [body[0]]


def test_brawl_run_coach_splices_the_ds_line_unconditionally():
    func = _method(BRAWL, "Coach", "_run_coach")
    assigns = [
        node for node in ast.walk(func)
        if isinstance(node, ast.Assign) and _has_ds_fstring(node)
    ]
    assert len(assigns) == 1, len(assigns)
    node = assigns[0]
    assert [ast.unparse(t) for t in node.targets] == ["user"]
    assert isinstance(node.value, ast.BinOp) and isinstance(node.value.op, ast.Add)
    last = node.value.right
    assert isinstance(last, ast.JoinedStr) and DS_LINE in ast.unparse(last)
    guards = [
        n for n in ast.walk(func)
        if isinstance(n, (ast.If, ast.IfExp)) and node in ast.walk(n)
        and "_ds_picks_str" in ast.unparse(n.test)
    ]
    assert guards == []


def _at(sha: str, rel: str) -> list[str] | None:
    out = subprocess.run(
        ["git", "show", f"{sha}:{rel}"],
        cwd=REPO, capture_output=True, text=True, encoding="utf-8", check=False,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    if out.returncode != 0:
        return None
    return out.stdout.splitlines()


def test_original_cites_were_exact_at_the_authoring_commit():
    sr = _at(AUTHORED_SHA, SR)
    if sr is None:
        return  # shallow clone without that commit: the live halves above still run
    assert sr[326].strip() == 'if _ds_picks_str != "unavailable":'
    assert sr[327].strip().startswith("user += f") and DS_LINE in sr[327]
    brawl = _at(AUTHORED_SHA, BRAWL)
    assert brawl is not None
    assert brawl[416].strip() == "user = ("
    assert brawl[433].strip() == ")"
    assert DS_LINE in brawl[432] and brawl[432].strip().startswith("+ f")
    authored = _at(AUTHORED_SHA, TARGET)
    assert authored is not None
    assert any("coach_integration/_coach.py:327-328" in ln for ln in authored)
    assert any("coaches/brawl_coach.py:417-434" in ln for ln in authored)
