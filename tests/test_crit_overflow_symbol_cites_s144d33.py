"""Guard: the R212 crit-overflow test cites by symbol, not line (RM-1053).

Measured 2026-10-28 at ENGINE 1.290.0. The pinned-ground-truth file
agents/daemon_slayer/tests/test_crit_overflow_saturation_rm176.py (45bd85949)
carried line cites on 11 lines into engine.py, dps.py and
_crit_chance_overrides.py. The engine.py and dps.py cites had drifted: the
engine crit clamp moved from 217-218 to 222-223, the binding ``crit_total``
clamp in dps.py from 1148 to 1208, and the R212 note from 1197-1203 to about
1282-1290. The Senna "structurally 0" prose still sits on
_crit_chance_overrides.py:264-267 because no commit since 45bd85949 has
touched that file; it is named by symbol too, so the next edit cannot strand
it. Each claim was re-read by symbol at HEAD and still holds; the prose now
names the function that carries each one, and the tests below pin those
claims so a moved or deleted construct fails here instead of leaving a cite
that resolves to SOME line forever.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DS = REPO / "agents" / "daemon_slayer"
TARGET = DS / "tests" / "test_crit_overflow_saturation_rm176.py"

# ``engine.py:217-218``, ``dps.py:1148``, ``_crit_chance_overrides.py:264-267``.
_LINE_CITE = re.compile(
    r"(?<![A-Za-z_])(?:engine|dps|_crit_chance_overrides)\.py:\d"
)

# Phrases only the replacement prose carries, so deleting the prose fails here.
_NAMED_IN_PROSE = (
    '``out["crit"]`` clamp in ``engine._combine_items``',
    "``crit_total = min(raw_crit + crit_from_effects, 1.0)`` in\n"
    "     ``dps.compute_dps``",
    "``overflow_lifesteal_pct`` docstring in ``_crit_chance_overrides.py``",
    "the R212 ``crit_chance_note`` in ``dps.compute_dps``",
)


def _segment(path: Path, fn: str) -> str:
    src = path.read_text(encoding="utf-8")
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, ast.FunctionDef) and node.name == fn:
            return ast.get_source_segment(src, node) or ""
    raise AssertionError(f"{path.name} has no {fn}")


def test_pattern_matches_the_rotted_shapes():
    for sample in (
        "clamp at ``engine.py:217-218``. That",
        "``dps.py:1148``, which runs AFTER",
        "``_crit_chance_overrides.py:264-267``, where",
        "R212 note (``dps.py:1197-1203``), so",
    ):
        assert _LINE_CITE.search(sample), sample
    for sample in (
        "``engine._combine_items``",
        "agents/daemon_slayer/dps.py",
        "ability_dps.py:1378",
        "burst.py:522",
    ):
        assert not _LINE_CITE.search(sample), sample


def test_no_line_cite_left_in_target():
    hits = [
        f"{TARGET.name}:{n}: {line.strip()}"
        for n, line in enumerate(
            TARGET.read_text(encoding="utf-8").splitlines(), 1)
        if _LINE_CITE.search(line)
    ]
    assert not hits, "cite by symbol, not line:\n" + "\n".join(hits)


def test_replacement_prose_present():
    text = TARGET.read_text(encoding="utf-8")
    missing = [p for p in _NAMED_IN_PROSE if p not in text]
    assert not missing, missing


def test_engine_clamp_lives_in_combine_items():
    body = _segment(DS / "engine.py", "_combine_items")
    assert 'if out.get("crit", 0.0) > 1.0:\n        out["crit"] = 1.0' in body


def test_binding_clamp_precedes_the_overflow_helper_in_compute_dps():
    body = _segment(DS / "dps.py", "compute_dps")
    clamp = body.index("crit_total = min(raw_crit + crit_from_effects, 1.0)")
    helper = body.index("crit_overflow_ad = overflow_bonus_ad(_cx_entry, crit_total)")
    assert clamp < helper


def test_overflow_magnitude_is_reported_in_the_crit_chance_note():
    body = _segment(DS / "dps.py", "compute_dps")
    assert 'f", overflow bonus AD +{crit_overflow_ad:.1f}"' in body
    assert "notes.append(crit_chance_note)" in body


def test_senna_structurally_zero_prose_is_in_overflow_lifesteal_pct():
    src = (DS / "_crit_chance_overrides.py").read_text(encoding="utf-8")
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, ast.FunctionDef) and node.name == "overflow_lifesteal_pct":
            doc = " ".join((ast.get_docstring(node) or "").split())
            break
    else:
        raise AssertionError("no overflow_lifesteal_pct")
    assert "clamps resolved crit chance at 1.0" in doc
    assert "overflow is structurally 0 on the shipped engine" in doc
