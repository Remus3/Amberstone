"""Guard: the P2-W2 slice-B test cites by symbol, not line (RM-1053).

Measured 2026-10-28 at ENGINE 1.290.0. tests/test_p2w2_ds_b.py (a6b3a0ba9)
carried 4 line cites into two DS modules, and all 4 had drifted (cited line
-> line before this edit): the Gwen P registry row ``antitank.py:274`` (twice)
-> 493, inside ``_build_antitank_registry``; ``engine.py:26 ResolvedStats``
-> 32; ``engine.py:43 .get`` -> 49. The text now names the symbol alone.

The prose claims were re-read against the engine and all hold; the tests
below pin the ones the test file's comments lean on, so a refactor that
drops a guard or adds a second Gwen row turns this red rather than leaving
the prose stale.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DS = REPO / "agents" / "daemon_slayer"
TARGET = REPO / "tests" / "test_p2w2_ds_b.py"

# ``(antitank.py:274)``, ``engine.py:26 ResolvedStats``, and the bare
# continuation ``:43 .get`` that leaned on the previous cite's module.
_LINE_CITE = re.compile(
    r"(?<![A-Za-z_])(?:antitank|engine)\.py:\d|(?<![\w.]):\d+ \.get\b")

_GWEN_ROW = (
    'add("Gwen", "P", "MAX_HP", "SUSTAINED", magnitude=0.85, '
    'ap_ratio=0.0005)'
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
        "    antitank.py:274).",
        "  agents/daemon_slayer/engine.py:26 ResolvedStats, :43 .get(key)",
        "# Gwen P: MAX_HP / SUSTAINED, magnitude 0.85 (antitank.py:274).",
    ):
        assert _LINE_CITE.search(sample), sample
    for sample in (
        "  agents/daemon_slayer/engine.py: ResolvedStats, ResolvedStats.get",
        "agents/daemon_slayer/antitank.py:_effective_magnitude, _finite_float,",
        "``stats.get(\"ap\"/\"ad\")``",
        "dps.py:274",
        "test_engine.py:12",
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


def test_every_named_symbol_resolves():
    text = TARGET.read_text(encoding="utf-8")
    for module, dotted in (
        ("antitank", "_effective_magnitude"),
        ("antitank", "_finite_float"),
        ("antitank", "compute_antitank"),
        ("antitank", "AntiTankEntry"),
        ("antitank", "_build_antitank_registry"),
        ("engine", "ResolvedStats"),
        ("engine", "ResolvedStats.get"),
    ):
        assert dotted in text, (module, dotted)
        _resolve(module, dotted)


def test_gwen_p_is_the_sole_gwen_row_with_the_cited_numbers():
    # The prose: magnitude 0.85, ap_ratio 0.0005, and "no other Gwen rows",
    # so the static score is that one row's 0.85.
    seg = _segment("antitank", "_build_antitank_registry")
    assert _GWEN_ROW in seg
    assert seg.count('add("Gwen"') == 1


def test_effective_magnitude_still_guards_the_stat_read():
    # The prose: ap / ad coerced through _finite_float, and the static base
    # is the fallback when the scaled magnitude is non-finite.
    seg = _segment("antitank", "_effective_magnitude")
    assert '_finite_float(stats.get("ap", 0.0))' in seg
    assert '_finite_float(stats.get("ad", 0.0))' in seg
    assert "scaled = s if math.isfinite(s) else base" in seg
