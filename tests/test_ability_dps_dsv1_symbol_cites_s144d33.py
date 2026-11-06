"""Guard: the DSV1 proc-fold comment in ability_dps cites by symbol (RM-1053).

Measured 2026-10-28 at ENGINE 1.290.0. ``compute_ability_dps``'s DSV1 block
(dc4d1de69, above ``proc_ctx``) said "The amp + pen layers above (lines
~950-995) already mirror compute_dps". At dc4d1de69 that range was the AP-amp
chain after ``collect_effects``, the ``damage_amp`` / ``magic_amp`` folds and
the ``effective_target_armor`` / ``effective_target_mr`` resists; at HEAD
those layers sit about 270 lines lower, so the range named unrelated code.

The same block also said the "other every_n_seconds AP procs (Malignance,
Stormsurge, Luden's, spellblades)" are folded. That was false when written:
the same commit passed ``ability_dot_only=True``, and ``_periodic_proc_dps``
skips every proc not tagged ``ability_dot`` - only the three burns (Torment,
Baleful Blaze, Azakana's Gaze) carry the tag. The new prose says so, and each
claim is pinned below so a moved gate or a newly tagged proc fails here.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DS = REPO / "agents" / "daemon_slayer"
ABILITY_DPS = DS / "ability_dps.py"
DPS = DS / "dps.py"

# ``(lines ~950-995)``, ``line 950``, ``lines 950-995``.
_RANGE_CITE = re.compile(r"\blines? ~?\d")

# The amp + pen helpers the DSV1 prose says both scorers share.
_MIRRORED = frozenset({
    "total_bonus_ap_from_hp",
    "total_stacked_ap",
    "total_ap_amp_multiplier",
    "total_caster_hp_scaled_ap_amp",
    "total_damage_amp_multiplier",
    "total_target_bonus_hp_amp_multiplier",
    "total_giant_slayer_multiplier",
    "total_magic_amp_multiplier",
    "effective_target_armor",
    "effective_target_mr",
})

_NEW_PROSE = (
    "The amp + pen layers above (the AP-amp chain after\n"
    "    # ``collect_effects``, the ``damage_amp`` / ``magic_amp`` folds and\n"
    "    # ``effective_target_armor`` / ``effective_target_mr``)",
    "``ability_dot_only=True`` keeps ONLY the procs tagged\n"
    "    # ``ability_dot`` (those three burns)",
    "Luden's Echo, Stormsurge Squall,\n"
    "    # Malignance Hatefog and the spellblades are NOT tagged",
)

_OLD_FOLD_CLAIM = "plus\n    # the other every_n_seconds AP procs"


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _function(path: Path, name: str) -> ast.FunctionDef:
    for node in ast.parse(_text(path)).body:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(f"{path.name} has no def {name}")


def _called_names(fn: ast.AST) -> set[str]:
    return {
        n.func.id
        for n in ast.walk(fn)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
    }


def _proc_fold_call(fn: ast.FunctionDef) -> ast.Call:
    calls = [
        n for n in ast.walk(fn)
        if isinstance(n, ast.Call)
        and isinstance(n.func, ast.Name)
        and n.func.id == "_periodic_proc_dps"
    ]
    assert len(calls) == 1, f"expected one _periodic_proc_dps call, got {len(calls)}"
    return calls[0]


def test_no_line_range_cite_left_in_ability_dps():
    hits = [
        f"{i}: {line.strip()}"
        for i, line in enumerate(_text(ABILITY_DPS).splitlines(), 1)
        if line.lstrip().startswith("#") and _RANGE_CITE.search(line)
    ]
    assert hits == [], "line-number cite left in ability_dps.py:\n" + "\n".join(hits)


def test_replacement_prose_present():
    text = _text(ABILITY_DPS)
    missing = [p for p in _NEW_PROSE if p not in text]
    assert missing == [], f"replacement prose missing: {missing}"


def test_false_fold_claim_removed():
    assert _OLD_FOLD_CLAIM not in _text(ABILITY_DPS)


def test_both_scorers_call_the_mirrored_amp_and_pen_helpers():
    ability = _called_names(_function(ABILITY_DPS, "compute_ability_dps"))
    assert ability >= _MIRRORED, sorted(_MIRRORED - ability)
    # compute_dps reaches several of these through module helpers, so the
    # mirror is measured over dps.py as a whole.
    dps = _called_names(ast.parse(_text(DPS)))
    assert dps >= _MIRRORED, sorted(_MIRRORED - dps)


def test_proc_fold_passes_ability_dot_only_true():
    call = _proc_fold_call(_function(ABILITY_DPS, "compute_ability_dps"))
    kw = {k.arg: k.value for k in call.keywords}
    assert isinstance(kw.get("ability_dot_only"), ast.Constant)
    assert kw["ability_dot_only"].value is True


def test_periodic_proc_dps_skips_untagged_procs_under_ability_dot_only():
    fn = _function(DPS, "_periodic_proc_dps")
    assert "if ability_dot_only and (not proc.ability_dot):" in ast.unparse(fn)


def test_only_the_three_burns_carry_ability_dot():
    from agents.daemon_slayer.effects import ITEM_EFFECTS

    tagged = {
        p.name
        for ie in ITEM_EFFECTS.values()
        for p in ie.periodics
        if p.ability_dot
    }
    assert tagged == {"Torment", "Baleful Blaze", "Azakana's Gaze"}
    untagged = {
        p.name
        for ie in ITEM_EFFECTS.values()
        for p in ie.periodics
        if not p.ability_dot and p.every_n_seconds > 0
    }
    assert {"Echo", "Squall", "Hatefog", "Spellblade"} <= untagged
