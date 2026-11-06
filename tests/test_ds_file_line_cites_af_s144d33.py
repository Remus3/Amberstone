"""Guard: the last ``line ~N`` cites in the DS package become symbol cites (RM-1053).

Measured 2026-10-31 at ENGINE 1.290.0. Four DS files still cited code as
``line ~N`` / ``lines ~N`` (the tilde shape the earlier ``\\w+\\.py:\\d``
sweeps did not match), and every cite had drifted:

- ``agents/daemon_slayer/_item_general_dr.py``: "``ehp.py`` lines ~1688 /
  ~1822" for where the R77 / R80 / R86 multipliers enter EHP. At HEAD they
  enter ``compute_ehp``'s ``physical_ehp`` denominator (near 2336) and its
  nested ``_blend_with_heal`` mirror (near 2482). The claim - PHYSICAL only -
  still holds.
- ``agents/daemon_slayer/_item_lowhp_magic_crit.py``: "lines ~1035 / ~3778"
  in ``_effects_data.py`` for the Shadowflame "low-HP gate not modeled" note
  "on both ids". At HEAD only ``ITEM_EFFECTS["4645"]`` (near 1093) carries
  that note; the Arena ``ITEM_EFFECTS["224645"]`` note now records only its
  own 10 flat magic pen (R161 doctrine B). The prose now says so.
- ``agents/daemon_slayer/tests/test_ehp_heal_phase6.py`` and
  ``agents/daemon_slayer/tests/test_ehp_shield_amp_phase65.py``:
  "``compute_ehp`` line ~590" for the shield amp and "line ~583" for the
  heal amp. At HEAD those are ``compute_ehp``'s ``shield_*_amped = shield_*
  * shield_amp_mult`` block (near 2001) and ``heal_total = (...) *
  heal_amp_mult`` (near 1951). The claims - each pool amped once, both
  summed into the EHP numerators - still hold.

The tests below pin the new symbol cites and every restated claim, and a
ratchet keeps the DS package free of ``line ~N`` and ``<file>.py:<n>`` cites.
"""
from __future__ import annotations

import ast
import re
import subprocess
from pathlib import Path

import pytest

from agents.daemon_slayer._effects_data import ITEM_EFFECTS

REPO = Path(__file__).resolve().parent.parent
DS = REPO / "agents" / "daemon_slayer"
EHP = DS / "ehp.py"

_TILDE_LINE = re.compile(r"\blines? ~\d")
_PY_LINE = re.compile(r"(?<![\w./])[\w/]+\.py:\d")

TARGETS = {
    "_item_general_dr.py": (
        "``physical_ehp`` denominator",
        "``_blend_with_heal`` mirror's",
    ),
    "_item_lowhp_magic_crit.py": (
        '``ITEM_EFFECTS["4645"]``',
        '``ITEM_EFFECTS["224645"]``',
    ),
    "tests/test_ehp_heal_phase6.py": (
        "``shield_*_amped = shield_* * shield_amp_mult``",
    ),
    "tests/test_ehp_shield_amp_phase65.py": (
        "``shield_*_amped = shield_* * shield_amp_mult``",
        "``heal_total = (...) * heal_amp_mult``",
    ),
}

_PHYS_ONLY = {"item_crit_dr_mult", "item_aa_dr_mult", "item_enemy_as_slow_mult"}


def _ds_python_files() -> list[Path]:
    out = subprocess.run(
        ["git", "ls-files", "--", "agents/daemon_slayer/*.py"],
        cwd=REPO, capture_output=True, text=True, check=True,
    ).stdout.split()
    return [REPO / p for p in out]


def _compute_ehp() -> ast.FunctionDef:
    tree = ast.parse(EHP.read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == "compute_ehp":
            return node
    raise AssertionError("compute_ehp not found in ehp.py")


def _assign_values(func: ast.AST, name: str) -> list[ast.expr]:
    out = []
    for node in ast.walk(func):
        if isinstance(node, ast.Assign):
            for tgt in node.targets:
                if isinstance(tgt, ast.Name) and tgt.id == name:
                    out.append(node.value)
    return out


def _names(expr: ast.AST) -> set[str]:
    return {n.id for n in ast.walk(expr) if isinstance(n, ast.Name)}


def _nested(func: ast.AST, name: str) -> ast.FunctionDef:
    for node in ast.walk(func):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(f"{name} not nested in compute_ehp")


def test_patterns_match_the_rotted_shapes():
    for sample in (
        "(``ehp.py`` lines ~1688 /",
        'not modeled)", lines ~1035 / ~3778)',
        "``compute_ehp`` line ~590 applies",
        "(Phase 6 wire at line ~583)",
    ):
        assert _TILDE_LINE.search(sample), sample
    for sample in (
        "line 1 column 2",
        "travel-line 1.0/1.5/2.0",
        "the Arena line 40 -> 45",
    ):
        assert not _TILDE_LINE.search(sample), sample
    for sample in ("(``rank.py:1146``)", "core/daemon_slayer_client.py:95-112"):
        assert _PY_LINE.search(sample), sample
    for sample in ("test_beam.py::Test", "``beam.beam_search_build``", "1%:2%"):
        assert not _PY_LINE.search(sample), sample


@pytest.mark.parametrize("rel", sorted(TARGETS))
def test_target_cites_by_symbol(rel):
    text = (DS / rel).read_text(encoding="utf-8")
    assert not _TILDE_LINE.search(text), rel
    for needle in TARGETS[rel]:
        assert needle in text, (rel, needle)


def test_ds_package_carries_no_line_cites():
    files = _ds_python_files()
    assert len(files) > 100, len(files)
    hits = []
    for path in files:
        for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if _TILDE_LINE.search(line) or _PY_LINE.search(line):
                hits.append(f"{path.relative_to(REPO).as_posix()}:{i}")
    assert hits == [], hits


def test_phys_only_multipliers_enter_only_the_physical_denominators():
    func = _compute_ehp()
    (phys,) = _assign_values(func, "physical_ehp")
    (mag,) = _assign_values(func, "magical_ehp")
    (true,) = _assign_values(func, "true_ehp")
    assert _names(phys) >= _PHYS_ONLY
    assert not _PHYS_ONLY & (_names(mag) | _names(true))
    for name in ("physical_ehp", "magical_ehp", "true_ehp"):
        (expr,) = _assign_values(func, name)
        assert "item_general_dr_mult" in _names(expr), name
    blend = _nested(func, "_blend_with_heal")
    (p,) = _assign_values(blend, "p")
    (m,) = _assign_values(blend, "m")
    (t,) = _assign_values(blend, "t")
    assert _names(p) >= _PHYS_ONLY
    assert not _PHYS_ONLY & (_names(m) | _names(t))


def test_only_the_sr_shadowflame_note_records_the_unmodeled_gate():
    assert "low-HP gate not modeled" in ITEM_EFFECTS["4645"].note
    assert "low-HP gate not modeled" not in ITEM_EFFECTS["224645"].note
    assert ITEM_EFFECTS["224645"].magic_pen_flat == 10.0


def test_heal_and_shield_pools_are_amped_once_and_summed():
    func = _compute_ehp()
    (heal,) = _assign_values(func, "heal_total")
    assert isinstance(heal, ast.BinOp) and isinstance(heal.op, ast.Mult)
    assert isinstance(heal.right, ast.Name) and heal.right.id == "heal_amp_mult"
    assert "heal_amp_mult" not in _names(heal.left)
    for pool in ("shield_any", "shield_phys", "shield_mag", "shield_true"):
        (expr,) = _assign_values(func, f"{pool}_amped")
        assert _names(expr) == {pool, "shield_amp_mult"}, pool
    for name, typed in (
        ("physical_ehp", "shield_phys_amped"),
        ("magical_ehp", "shield_mag_amped"),
        ("true_ehp", "shield_true_amped"),
    ):
        (expr,) = _assign_values(func, name)
        names = _names(expr)
        assert {"shield_any_amped", typed, "heal_total"} <= names, name
        assert not {"heal_amp_mult", "shield_amp_mult"} & names, name
