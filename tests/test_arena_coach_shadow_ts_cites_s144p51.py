"""RM-1295 (third family) - the arena coach's D-class cites into
core/coaching_timestamps.py and core/augment_shadow.py name the symbol, not
the line.

Two D-class handlers in coaches/arena_coach.py (broad excepts the callee
already makes unreachable) explained themselves by line:

  the coaching-timestamp write after a coaching write
      "callee already swallows (core/coaching_timestamps.py:73-74 returns
      None)"
  the augment-select shadow row in _handle_augment_select
      "callee already swallows (core/augment_shadow.py:112-113)"

Both were written by 7797264e2 (the silent no-op handler program). What they
meant at 7797264e2^:

  core/coaching_timestamps.py:73-74 -> write_coaching_ts, the last line of
      its try body (ts_tmp.replace) and its `except Exception` handler,
      which logs at DEBUG and falls through to an implicit None
  core/augment_shadow.py:112-113    -> log_augment_advice, the end of its
      docstring ("Never raises") and the `try:` that wraps the whole body,
      whose `except Exception` returns None

At HEAD the numbers still land near the same code only by chance: RM-258
(7a45bb921) rewrote write_coaching_ts onto core.polled_json and shifted its
handler up by one line, so :73-74 now names the handler and its log line
instead of the old replace + handler. A line cite that is right by accident
is still a line cite.

This guard pins:

(a) no coaching_timestamps.py / augment_shadow.py line cite in
    coaches/arena_coach.py;
(b) each named callee still exists, still catches Exception, holds no raise
    statement, and log_augment_advice's body is still one try statement
    (so nothing it runs sits outside the handler) whose handler returns
    None;
(c) each D-class comment block names its callee by dotted symbol;
(d) at 7797264e2^ every old cite landed inside the symbol named for it
    (skipped only when that commit is absent from the clone).

Out of scope on purpose, still open under RM-1295: the
vision_server/_inference.py:36 cites (arena_coach and aram_coach), the
core/feature_policy.py:305-350 cite and the two line cites into
aram_coach.py itself (:839 in aram_coach.py, :552 in
tests/test_aram_vision_cadence_fastpoll.py).
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
CITER = "coaches/arena_coach.py"
WRITING_PARENT = "7797264e2^"

TS = "core/coaching_timestamps.py"
SHADOW = "core/augment_shadow.py"

# (callee module, function, dotted name the D-class comment must carry)
CALLEES = (
    (TS, "write_coaching_ts", "core.coaching_timestamps.write_coaching_ts"),
    (SHADOW, "log_augment_advice", "core.augment_shadow.log_augment_advice"),
)

BANNED = re.compile(r"\b(?:coaching_timestamps|augment_shadow)\.py:\d")

# (module, old line at the writing parent, function it sat in, text on it)
OLD_CITES = (
    (TS, 73, "write_coaching_ts", "ts_tmp.replace(ts_file)"),
    (TS, 74, "write_coaching_ts", "except Exception"),
    (SHADOW, 112, "log_augment_advice", "Never raises"),
    (SHADOW, 113, "log_augment_advice", "try:"),
)


def _src(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def _func(src: str, name: str) -> ast.FunctionDef:
    for node in ast.parse(src).body:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(f"{name} not found - the arena D-class prose "
                         "names it (RM-1295)")


def _comment_blocks(rel: str) -> list[str]:
    """Runs of comment tokens on consecutive lines, each joined into one
    whitespace-collapsed string."""
    blocks: list[list[str]] = []
    last = -2
    toks = tokenize.generate_tokens(io.StringIO(_src(rel)).readline)
    for tok in toks:
        if tok.type != tokenize.COMMENT:
            continue
        row = tok.start[0]
        if row == last + 1 and blocks:
            blocks[-1].append(tok.string.lstrip("#"))
        else:
            blocks.append([tok.string.lstrip("#")])
        last = row
    return [" ".join(" ".join(b).split()) for b in blocks]


def _have(rev: str) -> bool:
    probe = subprocess.run(["git", "cat-file", "-e", f"{rev}{{commit}}"],
                           cwd=ROOT, capture_output=True)
    return probe.returncode == 0


def _git_show(spec: str) -> str:
    out = subprocess.run(["git", "show", spec], cwd=ROOT,
                         capture_output=True, check=True)
    return out.stdout.decode("utf-8")


def _catches_exception(handler: ast.ExceptHandler) -> bool:
    return isinstance(handler.type, ast.Name) and handler.type.id == "Exception"


def test_citer_carries_no_callee_line_cite():
    hits = [(n, line.strip()) for n, line in enumerate(_src(CITER).splitlines(), 1)
            if BANNED.search(line)]
    assert not hits, (
        f"{CITER} cites coaching_timestamps.py / augment_shadow.py by line "
        f"again; cite the symbol (RM-1295): {hits}")


@pytest.mark.parametrize(("rel", "func", "dotted"), CALLEES,
                         ids=[f for _, f, _ in CALLEES])
def test_dclass_comment_names_its_callee(rel, func, dotted):
    blocks = [b for b in _comment_blocks(CITER)
              if "D-class: callee already swallows" in b and dotted in b]
    assert len(blocks) == 1, (
        f"{CITER}: expected one D-class comment block naming {dotted}, "
        f"found {len(blocks)} (RM-1295)")


@pytest.mark.parametrize(("rel", "func", "dotted"), CALLEES,
                         ids=[f for _, f, _ in CALLEES])
def test_callee_swallows_and_never_raises(rel, func, dotted):
    fn = _func(_src(rel), func)
    raises = [n.lineno for n in ast.walk(fn) if isinstance(n, ast.Raise)]
    assert not raises, (
        f"{rel} {func} now raises (lines {raises}); the arena D-class prose "
        "that relies on it swallowing must be re-checked (RM-1295)")
    handlers = [h for n in ast.walk(fn) if isinstance(n, ast.Try)
                for h in n.handlers if _catches_exception(h)]
    assert handlers, (
        f"{rel} {func} no longer catches Exception; re-check the arena "
        "D-class prose that names it (RM-1295)")


def test_log_augment_advice_body_is_one_try_returning_none():
    fn = _func(_src(SHADOW), "log_augment_advice")
    body = fn.body
    if (body and isinstance(body[0], ast.Expr)
            and isinstance(body[0].value, ast.Constant)
            and isinstance(body[0].value.value, str)):
        assert "Never raises" in body[0].value.value
        body = body[1:]
    assert len(body) == 1 and isinstance(body[0], ast.Try), (
        f"{SHADOW} log_augment_advice runs code outside its try; the arena "
        "D-class prose says nothing it does can raise (RM-1295)")
    outer = body[0].handlers
    assert len(outer) == 1 and _catches_exception(outer[0])
    last = outer[0].body[-1]
    assert (isinstance(last, ast.Return) and isinstance(last.value, ast.Constant)
            and last.value.value is None), (
        f"{SHADOW} log_augment_advice's handler no longer returns None")


def test_banned_pattern_still_bites():
    for sample in ("(core/coaching_timestamps.py:73-74 returns None)",
                   "(core/augment_shadow.py:112-113),",
                   "augment_shadow.py:99"):
        assert BANNED.search(sample), sample
    for other in ("core.coaching_timestamps.write_coaching_ts",
                  "core.augment_shadow.log_augment_advice",
                  "vision_server/_inference.py:36"):
        assert not BANNED.search(other), other


@pytest.mark.parametrize(("rel", "line", "func", "text"), OLD_CITES,
                         ids=[f"{r.rsplit('/', 1)[-1]}:{n}"
                              for r, n, _, _ in OLD_CITES])
def test_old_cite_meant_the_named_symbol(rel, line, func, text):
    if not _have(WRITING_PARENT):
        pytest.skip(f"{WRITING_PARENT} absent from this clone (shallow)")
    src = _git_show(f"{WRITING_PARENT}:{rel}")
    node = _func(src, func)
    assert node.lineno <= line <= node.end_lineno, (
        f"{rel}:{line} at {WRITING_PARENT} is outside {func} "
        f"({node.lineno}-{node.end_lineno})")
    assert text in src.splitlines()[line - 1], (
        f"{rel}:{line} at {WRITING_PARENT} does not carry {text!r}")
