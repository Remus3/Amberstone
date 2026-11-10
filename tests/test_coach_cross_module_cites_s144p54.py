"""RM-1298 - coach comments cite core / tft helpers by symbol, not by line.

Three comment / docstring sites in the coaches cited another module by line
number:

- coaches/_base_coach.py ``BaseCoach.__init__``: ``register_coach
  (core/hotkeys.py:24-28)``;
- coaches/_base_coach.py ``BaseCoach._record_coach_call``: ``coach_trace.append
  (core/coach_trace.py:65-77)``;
- coaches/tft_coach.py ``Coach._default_payloads``:
  ``core/feature_policy.py:102 _TFT_LIVE_DISABLED_PAYLOAD`` and ``the live
  producer tft/tft_live_analysis.py:477``.

The last two were already stale when measured (the payload sits at line 128
of core/feature_policy.py, and line 477 of tft/tft_live_analysis.py is an
RM-615 comment block, not the producer). The first two were still right but
would drift on any edit above them. Each site now names the symbol, and this
guard checks two things: the cited claim still holds for the named symbol, and
no ``<module>.py:<n>`` cite has come back into the three enclosing functions.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent

LINE_CITE = re.compile(r"\b[\w./]+\.py:\d+")

SITES = (
    ("coaches/_base_coach.py", "BaseCoach", "__init__"),
    ("coaches/_base_coach.py", "BaseCoach", "_record_coach_call"),
    ("coaches/tft_coach.py", "Coach", "_default_payloads"),
)


def _src(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def _method(src: str, rel: str, cls: str, name: str) -> ast.AST:
    tree = ast.parse(src, filename=rel)
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == cls:
            for sub in node.body:
                if (isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef))
                        and sub.name == name):
                    return sub
    raise AssertionError(f"{rel}: {cls}.{name} not found")


def _func(src: str, rel: str, name: str) -> ast.AST:
    for node in ast.parse(src, filename=rel).body:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(f"{rel}: {name} not found")


def _segment(rel: str, cls: str, name: str) -> str:
    src = _src(rel)
    node = _method(src, rel, cls, name)
    lines = src.splitlines()
    return "\n".join(lines[node.lineno - 1:node.end_lineno])


@pytest.mark.parametrize(("rel", "cls", "name"), SITES,
                         ids=[f"{r}::{c}.{n}" for r, c, n in SITES])
def test_no_line_number_cite_in_site(rel, cls, name):
    hits = LINE_CITE.findall(_segment(rel, cls, name))
    assert not hits, (
        f"{rel} {cls}.{name} carries line-number cite(s) {hits}; cite the "
        "symbol instead (RM-1298)")


@pytest.mark.parametrize(("rel", "cls", "name", "needle"), [
    ("coaches/_base_coach.py", "BaseCoach", "__init__",
     "register_coach (core.hotkeys) is"),
    ("coaches/_base_coach.py", "BaseCoach", "_record_coach_call",
     "coach_trace.append (its rec literal in core.coach_trace) runs"),
    ("coaches/tft_coach.py", "Coach", "_default_payloads",
     "core.feature_policy._TFT_LIVE_DISABLED_PAYLOAD"),
    ("coaches/tft_coach.py", "Coach", "_default_payloads",
     "tft.tft_live_analysis.TftLiveAnalysis._write (its `out` literal holds"),
])
def test_site_names_the_symbol(rel, cls, name, needle):
    seg = " ".join(_segment(rel, cls, name).replace("#", " ").split())
    assert needle in seg, f"{rel} {cls}.{name} no longer names {needle!r}"


def test_register_coach_claim_holds():
    """'an identity `not in` test plus list.append on a module global - it
    cannot raise': no Raise node, one `not in` compare, one append call."""
    rel = "core/hotkeys.py"
    fn = _func(_src(rel), rel, "register_coach")
    nodes = list(ast.walk(fn))
    assert not [n for n in nodes if isinstance(n, ast.Raise)]
    assert any(isinstance(n, ast.Compare)
               and any(isinstance(o, ast.NotIn) for o in n.ops)
               for n in nodes)
    assert any(isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
               and n.func.attr == "append"
               and getattr(n.func.value, "id", None) == "_coaches" for n in nodes)
    # The module global: bound at module level, never rebound in this function
    # (a read-only name needs no `global` statement, so none is asserted).
    tree = ast.parse(_src(rel))
    assert any(isinstance(n, ast.AnnAssign)
               and getattr(n.target, "id", None) == "_coaches" for n in tree.body)
    assert not [n for n in nodes if isinstance(n, ast.Name) and n.id == "_coaches"
                and isinstance(n.ctx, ast.Store)]
    assert not [n for n in nodes if isinstance(n, ast.arg) and n.arg == "_coaches"]
    assert not [a for n in nodes if isinstance(n, (ast.Import, ast.ImportFrom))
                for a in n.names if (a.asname or a.name) == "_coaches"]


def test_coach_trace_append_claim_holds():
    """'runs int() / _truncate over caller-supplied values' in its rec
    literal, so the raise surface is open."""
    rel = "core/coach_trace.py"
    fn = _func(_src(rel), rel, "append")
    recs = [n.value for n in ast.walk(fn)
            if isinstance(n, ast.Assign)
            and any(isinstance(t, ast.Name) and t.id == "rec" for t in n.targets)
            and isinstance(n.value, ast.Dict)]
    assert recs, f"{rel} append has no rec dict literal"
    called = {c.func.id for c in ast.walk(recs[0])
              if isinstance(c, ast.Call) and isinstance(c.func, ast.Name)}
    assert {"int", "_truncate"} <= called, called


def _live_seed_keys() -> set[str]:
    from types import SimpleNamespace

    from coaches.tft_coach import Coach
    fake = SimpleNamespace(_tft_data_file=Path("c.json"),
                           _live_data_file=Path("l.json"))
    return set(dict(Coach._default_payloads(fake))[Path("l.json")])


def test_live_seed_matches_disabled_payload():
    from core.feature_policy import _TFT_LIVE_DISABLED_PAYLOAD
    seed = _live_seed_keys()
    assert len(seed) == 19, sorted(seed)
    assert seed == set(_TFT_LIVE_DISABLED_PAYLOAD)


def test_live_producer_out_literal_holds_the_19_keys_plus_last_round_result():
    """The docstring claims the `out` LITERAL only: _write later stamps
    degraded / degraded_message onto it, which the seed does not carry."""
    rel = "tft/tft_live_analysis.py"
    fn = _method(_src(rel), rel, "TftLiveAnalysis", "_write")
    outs = [n.value for n in ast.walk(fn)
            if isinstance(n, ast.Assign)
            and any(isinstance(t, ast.Name) and t.id == "out" for t in n.targets)
            and isinstance(n.value, ast.Dict)]
    assert outs, f"{rel} TftLiveAnalysis._write has no out dict literal"
    keys = {k.value for k in outs[0].keys if isinstance(k, ast.Constant)}
    assert keys == _live_seed_keys() | {"last_round_result"}, sorted(keys)
