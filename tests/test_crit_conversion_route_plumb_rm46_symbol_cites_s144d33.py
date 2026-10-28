"""Guard: the RM-46 crit-conversion route-plumb test cites by symbol (RM-1053).

Measured 2026-10-28 at ENGINE 1.290.0. The module docstring of
``agents/daemon_slayer/tests/test_crit_conversion_route_plumb_rm46.py``
carried five engine line cites, all rotted at HEAD:
- ``dps.py:747`` (``def compute_dps``) now sits at 769, and its gate ``:890``
  (the ``if apply_crit_conversion:`` branch) at 1017.
- ``rank.py:1091`` (the ``baseline`` ``compute_dps`` call in ``rank_items``)
  now sits at 1235, and ``:1206`` (the per-candidate ``scored`` call) at 1361.
- ``server.py:421`` (``_route_rank``) now sits at 603.
The archive cite ``OPEN_ITEMS_REVIEW_2026-07-25.md:451-457`` is a dated,
never-edited artifact and was still true, so it stays.

The tests below pin the claims by symbol instead.
"""
from __future__ import annotations

import ast
import inspect
import re
from pathlib import Path

from agents.daemon_slayer import dps, rank

REPO = Path(__file__).resolve().parent.parent
DS = REPO / "agents" / "daemon_slayer"
TARGET = DS / "tests" / "test_crit_conversion_route_plumb_rm46.py"
_LINE_CITE = re.compile(
    r"(?<![\w.])(?:dps|rank|server)\.py:\d|(?:at|and) :\d+"
)


def _target() -> str:
    return TARGET.read_text(encoding="utf-8")


def _func(name: str, module: str) -> ast.FunctionDef:
    tree = ast.parse((DS / module).read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(f"{module} has no top-level def {name}")


def _compute_dps_assigns(func: ast.FunctionDef) -> dict[str, ast.Call]:
    out: dict[str, ast.Call] = {}
    for node in ast.walk(func):
        if (
            isinstance(node, ast.Assign)
            and isinstance(node.value, ast.Call)
            and isinstance(node.value.func, ast.Name)
            and node.value.func.id == "compute_dps"
        ):
            for tgt in node.targets:
                out[ast.unparse(tgt)] = node.value
    return out


def _forwards_flag(call: ast.Call) -> bool:
    return any(
        kw.arg == "apply_crit_conversion"
        and isinstance(kw.value, ast.Name)
        and kw.value.id == "apply_crit_conversion"
        for kw in call.keywords
    )


def test_pattern_matches_the_rotted_shape():
    for sample in (
        "apply_crit_conversion: bool = False)`` - dps.py:747, gate at :890.",
        "``compute_dps`` at rank.py:1091 (baseline) and :1206 (candidate).",
        "builds the ``rank_items`` call - server.py:421.",
    ):
        assert _LINE_CITE.search(sample), sample
    for sample in (
        "``server._route_rank`` builds the ``rank_items`` call.",
        "drives the shipped build tables through ``:8860``",
        "OPEN_ITEMS_REVIEW_2026-07-25.md:451-457",
        "a test_dps.py:9 cite is not this pattern",
    ):
        assert not _LINE_CITE.search(sample), sample


def test_no_line_cite_left():
    hits = [
        f"{TARGET.name}:{n}: {line.strip()}"
        for n, line in enumerate(_target().splitlines(), 1)
        if _LINE_CITE.search(line)
    ]
    assert not hits, "cite by symbol, not line:\n" + "\n".join(hits)


def test_target_names_every_site_by_symbol():
    text = _target()
    for symbol in (
        "``dps.compute_dps``",
        "``if apply_crit_conversion:``",
        "``rank.rank_items``",
        "``baseline``",
        "``scored``",
        "``server._route_rank``",
    ):
        assert symbol in text, symbol


def test_flag_is_default_off_on_both_python_entry_points():
    for fn in (dps.compute_dps, rank.rank_items):
        param = inspect.signature(fn).parameters["apply_crit_conversion"]
        assert param.default is False, fn.__name__


def test_compute_dps_gates_on_the_flag():
    func = _func("compute_dps", "dps.py")
    assert any(
        isinstance(node, ast.If)
        and isinstance(node.test, ast.Name)
        and node.test.id == "apply_crit_conversion"
        for node in ast.walk(func)
    )


def test_rank_items_forwards_flag_to_baseline_and_scored():
    calls = _compute_dps_assigns(_func("rank_items", "rank.py"))
    for name in ("baseline", "scored"):
        assert name in calls, sorted(calls)
        assert _forwards_flag(calls[name]), name


def test_route_rank_parses_and_forwards_the_flag():
    src = ast.unparse(_func("_route_rank", "server.py"))
    assert "_opt_bool(body, 'apply_crit_conversion', False)" in src
    assert "apply_crit_conversion=apply_crit_conversion" in src
