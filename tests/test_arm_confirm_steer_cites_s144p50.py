"""RM-1294 - _arm_confirm.py and steer.py rationale cites by symbol.

Two files explained a behaviour by citing it by line:

  dashboard/_arm_confirm.py  (module docstring and the target_of docstring)
  ops/loop/steer.py          (the _awrite docstring, RM-250 paragraph)

What the cites meant, in the tree each was written against:

  _arm_confirm.py, written by fbcf8474d against fbcf8474d^ (the commit that
  DELETED web/mc/, so every web/mc cite reads at its parent):
    `web/mc/arm_confirm.js:45`       -> export function createArmController
    `web/mc/mc.js:133`               -> const _mcArm = createArmController(...)
    `web/mc/arm_confirm.js:89-100`   -> arm(), which calls disarm(true) first
    `web/mc/mc.js:285` / `:483`      -> _mcArm.arm(id) / _mcArm.arm(sc.id)
                                        (every web/mc row: a deleted file)
    `web/mc/mc.js:338`               -> _mcArm.arm(_MC_IRQ_ID)
    `web/mc/mc.js:665,668,800,802`   -> the Resume / Stop loop / directive /
                                        Clear buttons, direct _loopControl()
    `:255` / `:467` / `:304`         -> "lane:" + lane / sc.id / _MC_IRQ_ID
    `dashboard/_idempotency.py:12-15` -> the "Deliberately in-process and
                                        non-durable" docstring paragraph
  steer.py, written by 57b76141a against 57b76141a^:
    `STEER.cursor (:243)`            -> _awrite(STEER_CURSOR, ...) in drain()

At HEAD (lane/repo, 2026-10-31) the steer.py cite had drifted to the
pending() docstring (the write is now 43 lines lower), the web/mc cites named
files that no longer exist with no commit to read them at, and the
_idempotency.py range still held but only by luck. Each cite now names its
symbol (and, for the deleted files, the commit to read them at). This guard
pins:

(a) no `<file>.<ext>:<n>` cite and no bare `(:<n>)` / `` `:<n>` `` cite in
    either citer;
(b) every live symbol still exists and still says or does what the
    rationale says it does;
(c) each citer names its symbols in a COMMENT or STRING token, so a code
    reference to the same name cannot satisfy the check;
(d) the web/mc symbols exist at fbcf8474d^ (a commit absent from the clone
    FAILS: tests/test_ci_checkout_history_depth.py keeps these on full clones,
    and a shallow skip would hide on every CI run).
"""

from __future__ import annotations

import ast
import io
import re
import subprocess
import tokenize
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent

ARM = "dashboard/_arm_confirm.py"
STEER = "ops/loop/steer.py"
IDEM = "dashboard/_idempotency.py"
MC_PARENT = "fbcf8474d^"

CITERS = {
    ARM: (
        "createArmController",
        "_mcArm",
        "_mcPaintLanes",
        "_MC_SHORTCUTS",
        "_MC_IRQ_ID",
        "_loopControl",
        "disarm(true)",
        "fbcf8474d^",
        "Deliberately in-process and non-durable",
        "`dashboard/_idempotency.py` module docstring",
    ),
    STEER: ("`STEER_CURSOR`", "`drain()`", "`cursor()`", "`pending()`"),
}

# A file cite (`x.py:12`, `mc.js:665,668`) or a bare line cite (`(:243)`,
# `` `:255` ``).
BANNED = re.compile(
    r"[\w./-]+\.(?:py|js|md|ps1|json|ahk|css|html)\s*:\s*\d"
    r"|\(\s*:\d|`:\d"
)


def _src(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def _prose(rel: str) -> str:
    """Only COMMENT and STRING tokens: the prose a reader follows."""
    toks = tokenize.generate_tokens(io.StringIO(_src(rel)).readline)
    return "\n".join(t.string for t in toks
                     if t.type in (tokenize.COMMENT, tokenize.STRING))


def _func(rel: str, name: str) -> ast.FunctionDef:
    for node in ast.parse(_src(rel)).body:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(f"{rel}: def {name} not found - the rationale "
                         "that names it (RM-1294) is now false")


def _calls(fn: ast.FunctionDef) -> set:
    return {n.func.id for n in ast.walk(fn)
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}


@pytest.mark.parametrize("rel", sorted(CITERS))
def test_citer_carries_no_line_cite(rel):
    hits = [m.group(0) for m in BANNED.finditer(_src(rel))]
    assert not hits, (
        f"{rel} carries line cite(s) {hits}: cite by symbol (RM-1294)")


@pytest.mark.parametrize("rel", sorted(CITERS))
def test_citer_names_its_symbols_in_prose(rel):
    prose = " ".join(_prose(rel).split())
    missing = [s for s in CITERS[rel] if " ".join(s.split()) not in prose]
    assert not missing, f"{rel} prose no longer names {missing} (RM-1294)"


def test_idempotency_paragraph_holds():
    doc = ast.get_docstring(ast.parse(_src(IDEM))) or ""
    flat = " ".join(doc.split())
    assert "Deliberately in-process and non-durable." in flat
    assert "A dashboard restart clearing the table is correct" in flat


def test_drain_advances_the_cursor():
    drain = _func(STEER, "drain")
    writes = [n for n in ast.walk(drain)
              if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
              and n.func.id == "_awrite" and n.args
              and isinstance(n.args[0], ast.Name)
              and n.args[0].id == "STEER_CURSOR"]
    assert len(writes) == 1, "drain() no longer writes STEER_CURSOR via _awrite"


def test_cursor_is_read_on_the_pending_poll():
    cur = _func(STEER, "cursor")
    assert any(isinstance(n, ast.Name) and n.id == "STEER_CURSOR"
               for n in ast.walk(cur)), "cursor() no longer reads STEER_CURSOR"
    assert "cursor" in _calls(_func(STEER, "_unconsumed"))
    assert "_unconsumed" in _calls(_func(STEER, "pending"))


def test_web_mc_is_still_deleted():
    """The cites read web/mc at fbcf8474d^ BECAUSE the tree has none."""
    assert not (ROOT / "web" / "mc").exists()


def _git(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args], cwd=ROOT,
        capture_output=True, text=True, encoding="utf-8", check=False)


def _at_parent(path: str) -> str:
    """`path` at fbcf8474d^. An absent commit and a commit that lacks `path`
    are both failures."""
    probe = _git("cat-file", "-e", f"{MC_PARENT}^{{commit}}")
    assert probe.returncode == 0, f"{MC_PARENT} not in this clone"
    proc = _git("show", f"{MC_PARENT}:{path}")
    assert proc.returncode == 0, f"{path}@{MC_PARENT}: {proc.stderr.strip()}"
    return proc.stdout


@pytest.mark.parametrize("path,text", [
    ("web/mc/arm_confirm.js", "export function createArmController(opts)"),
    ("web/mc/mc.js", "const _mcArm = createArmController("),
    ("web/mc/mc.js", "function _mcPaintLanes()"),
    ("web/mc/mc.js", 'const id = "lane:" + lane;'),
    ("web/mc/mc.js", "_mcArm.arm(id);"),
    ("web/mc/mc.js", "_mcArm.arm(sc.id);"),
    ("web/mc/mc.js", "_MC_SHORTCUTS.forEach("),
    ("web/mc/mc.js", 'const _MC_IRQ_ID = "interrupt";'),
    ("web/mc/mc.js", "_mcArm.arm(_MC_IRQ_ID);"),
    ("web/mc/mc.js", '_loopControl("resume")'),
    ("web/mc/mc.js", '_loopControl("stop"'),
    ("web/mc/mc.js", '_loopControl("set_directive"'),
    ("web/mc/mc.js", '_loopControl("clear_directive")'),
])
def test_web_mc_symbol_at_parent(path, text):
    assert text in _at_parent(path), f"{path}@{MC_PARENT} lacks {text!r}"


def test_arm_disarms_first_at_parent():
    js = _at_parent("web/mc/arm_confirm.js")
    body = js.split("function arm(id, at)", 1)[1].split("\n  }\n", 1)[0]
    assert "disarm(true);" in body


@pytest.mark.parametrize("bad", [
    "`web/mc/arm_confirm.js:45`",
    "`web/mc/mc.js:665,668,800,802`",
    "`dashboard/_idempotency.py:12-15`",
    "STEER.cursor (:243) is polled",
    "a lane by its lane name (`:255`)",
])
def test_banned_pattern_still_bites(bad):
    assert BANNED.search(bad), bad
