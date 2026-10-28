"""Guard: the P2-W2 slice-A test cites by symbol, not line (RM-1053).

Measured 2026-10-28 at ENGINE 1.290.0. tests/test_p2w2_ds_a.py (a6b3a0ba9)
listed 8 symbols with line cites into five DS modules, and 6 had drifted
(cited line -> line before this edit): ``DataSnapshot.load`` 67 -> 156,
``spell_travel_time`` 112 -> 113, ``compute_dps_sweep`` 151 -> 152,
``SweepResult`` 88 -> 90, ``ObjDamageEntry`` 112 -> 113, ``_armor_factor``
196 -> 274 (``compute_objdamage`` 719 and ``_mechanism_value`` 132 still
matched). The list now names the symbol alone.

The prose claims were re-read against the engine and all hold; the tests
below pin the ones the test file's comments lean on, so a refactor that
drops a guard turns this red rather than leaving the prose stale.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DS = REPO / "agents" / "daemon_slayer"
TARGET = REPO / "tests" / "test_p2w2_ds_a.py"

# ``(data_loader.py:67)``, ``(dps.py:196)``.
_LINE_CITE = re.compile(
    r"(?<![A-Za-z_])(?:data_loader|missile|dps_sweep|objdamage|dps)\.py:\d")

# (module, dotted name) in the symbol list; a dotted name is Class.method.
_SYMBOLS = (
    ("data_loader", "DataSnapshot.load"),
    ("missile", "spell_travel_time"),
    ("dps_sweep", "compute_dps_sweep"),
    ("dps_sweep", "SweepResult"),
    ("objdamage", "compute_objdamage"),
    ("objdamage", "_mechanism_value"),
    ("objdamage", "ObjDamageEntry"),
    ("dps", "_armor_factor"),
)


def _source(module: str) -> str:
    return (DS / f"{module}.py").read_text(encoding="utf-8")


def _resolve(module: str, dotted: str) -> ast.AST:
    body = ast.parse(_source(module)).body
    node: ast.AST | None = None
    for part in dotted.split("."):
        node = next(
            (n for n in body
             if isinstance(n, (ast.FunctionDef, ast.ClassDef))
             and n.name == part),
            None,
        )
        if node is None:
            raise AssertionError(f"{module}.py has no {dotted}")
        body = node.body
    assert node is not None
    return node


def _segment(module: str, dotted: str) -> str:
    return ast.get_source_segment(
        _source(module), _resolve(module, dotted)) or ""


def test_pattern_matches_the_rotted_shapes():
    for sample in (
        "  data_loader.DataSnapshot.load        (data_loader.py:67)",
        "  dps._armor_factor                    (dps.py:196)",
        "  dps_sweep.SweepResult                (dps_sweep.py:88)",
    ):
        assert _LINE_CITE.search(sample), sample
    for sample in (
        "  dps_sweep.compute_dps_sweep",
        "agents/daemon_slayer/objdamage.py",
        "burst.py:124",
        "_passive_dps.py:12",
    ):
        assert not _LINE_CITE.search(sample), sample


def test_no_line_cite_left_in_target():
    hits = [
        f"{n}: {line.strip()}"
        for n, line in enumerate(
            TARGET.read_text(encoding="utf-8").splitlines(), 1)
        if _LINE_CITE.search(line)
    ]
    assert not hits, "cite by symbol, not line:\n" + "\n".join(hits)


def test_every_listed_symbol_resolves():
    text = TARGET.read_text(encoding="utf-8")
    for module, dotted in _SYMBOLS:
        assert f"{module}.{dotted}" in text, (module, dotted)
        _resolve(module, dotted)


def test_travel_time_still_rejects_a_non_finite_distance():
    # The prose: inf / NaN distance falls back to geometry / _DEFAULT_DISTANCE.
    seg = _segment("missile", "spell_travel_time")
    assert "math.isfinite(distance) and distance > 0" in seg
    assert "or _DEFAULT_DISTANCE" in seg


def test_sweep_still_finite_filters_both_axes():
    # The prose: level axis (int(inf) OverflowError) AND resist axes (NaN x).
    seg = _segment("dps_sweep", "compute_dps_sweep")
    assert "tuple(int(v) for v in axis_values if math.isfinite(v))" in seg
    assert "[float(v) for v in axis_values if math.isfinite(v)]" in seg


def test_objdamage_sentinel_edge_the_prose_names():
    # The prose: a 0-magnitude entry must never set top_kind on a zero-total
    # champion "(the -1.0 sentinel edge)". It beats -1.0, so the guard is the
    # total > 0.0 gate on top_kind.
    seg = _segment("objdamage", "compute_objdamage")
    assert "best_value = -1.0" in seg
    assert 'top_kind=best_kind if total > 0.0 else ""' in seg
