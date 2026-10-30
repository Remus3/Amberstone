"""Guard: ``_resist_damage_coupling.py`` cites by symbol, not line (RM-1053 part).

Measured 2026-10-30 at ENGINE 1.290.0. All seven of its line cites had rotted:

- It cited ``ehp.py:1926-1927`` for the ``eff_armor`` / ``eff_mr`` resist sum,
  ``ehp.py:1984-1986`` for the per-type EHP expressions and
  ``ehp.py:2095-2099`` for the ``blended_ehp`` enemy-share blend. Those lines
  now sit in the rune health grant call, an HSP comment and the rune flat
  mitigation comment of ``compute_ehp``; the code they named is 352 lines
  lower.
- It cited ``_passive_damage_overrides.py:839-843`` / ``:844-849`` for the
  K'Sante P All Out Bonus and Rammus W documented rejects, ``:852-861`` for
  the Taric P Bravado row and ``:867-874`` for the Galio P Colossal Smash row.
  Those lines are now the Jhin Whisper / K'Sante Dauntless Instinct /
  Sejuani rows; the rejects live in the GAP-2 CASTER-DEFENSIVE-STAT header
  comment, and the K'Sante All Out Bonus is now modelled as its own
  default-OFF bilinear seam (``_ALL_OUT_BONUS_OVERRIDES``), still not a
  linear resist term.
- The old prose said the resist is divided "in the three per-type
  numerators"; ``true_ehp`` reads no resist, so only two divide by it.
- Sibling sweep: ``test_item_resist_grants_terminus_r67.py`` cites the same
  ``eff_armor`` sum as ``ehp.py:1927-1928`` (also rotted). Its two other line
  cites point elsewhere and are out of this slice.

The tests below pin the cites and the claims they carried by symbol instead.
"""
from __future__ import annotations

import inspect
import re
from pathlib import Path

import pytest

from agents.daemon_slayer import _passive_damage_overrides, ehp

REPO = Path(__file__).resolve().parent.parent
DS = REPO / "agents" / "daemon_slayer"
_LINE_CITE = re.compile(r"(?<![\w.])\w+\.py:\d|``:\d|\blines \d")

TARGETS = {
    "_resist_damage_coupling.py": (
        "``eff_armor`` / ``eff_mr`` (the resist sum of ``compute_ehp``)",
        "in the ``physical_ehp`` / ``magical_ehp`` expressions of "
        "``compute_ehp`` (``true_ehp`` reads no resist)",
        "(the ``blended_ehp`` enemy-share sum)",
        "documented reject in the ``_passive_damage_overrides`` GAP-2 "
        "CASTER-DEFENSIVE-STAT header comment",
        "``_passive_damage_overrides._ALL_OUT_BONUS_OVERRIDES``",
        "already rejected in that same GAP-2 header comment",
        "the ``(\"Taric\", \"P\", 0)`` row of "
        "``_passive_damage_overrides._PASSIVE_DAMAGE_OVERRIDES``",
        "The ``(\"Galio\", \"P\", 0)`` row of "
        "``_passive_damage_overrides._PASSIVE_DAMAGE_OVERRIDES``",
    ),
}

_SAME_TARGET = re.compile(r"(?:_passive_damage_overrides|ehp)\.py:\d")
SIBLINGS = {
    "tests/test_item_resist_grants_terminus_r67.py": (
        "(the resist sum of ``compute_ehp``: ``eff_armor = armor + bonus_armor "
        "+ ext_armor + item_resist_armor + rune_resist_armor``)",
    ),
}


def _flat(text: str) -> str:
    return " ".join(text.replace("#", " ").split())


def _compute_ehp_line(prefix: str) -> str:
    src = inspect.getsource(ehp.compute_ehp)
    hits = [ln.strip() for ln in src.splitlines() if ln.strip().startswith(prefix)]
    assert len(hits) == 1, (prefix, hits)
    return hits[0]


def test_pattern_matches_the_old_shapes():
    for sample in (
        "(``ehp.py:1926-1927``), divides by it exactly once in the three per-type",
        "numerators (``ehp.py:1984-1986``), and blends exactly once",
        "(``ehp.py:2095-2099``). No term is counted twice anywhere.",
        "    ``_passive_damage_overrides.py:839-843``: it is BILINEAR (caster bonus",
        "    # _passive_damage_overrides.py:852-861) is the WEAKER peer source and is",
        "    # _passive_damage_overrides.py:867-874, Galio P \"Colossal Smash\":",
    ):
        assert _LINE_CITE.search(sample), sample
    for symbols in TARGETS.values():
        for sample in symbols:
            assert not _LINE_CITE.search(sample), sample


@pytest.mark.parametrize("name", sorted(TARGETS))
def test_no_line_cite_left(name):
    text = (DS / name).read_text(encoding="utf-8")
    hits = [
        f"{name}:{n}: {line.strip()}"
        for n, line in enumerate(text.splitlines(), 1)
        if _LINE_CITE.search(line)
    ]
    assert not hits, "cite by symbol, not line:\n" + "\n".join(hits)


@pytest.mark.parametrize("name", sorted(TARGETS))
def test_names_the_symbols(name):
    flat = _flat((DS / name).read_text(encoding="utf-8"))
    for symbol in TARGETS[name]:
        assert symbol in flat, f"{name}: {symbol}"
    assert "the three per-type numerators" not in flat


def test_same_target_pattern_matches_the_old_shape():
    assert _SAME_TARGET.search(
        "        (``ehp.py:1927-1928``: ``eff_armor = armor + bonus_armor + ext_armor +"
    )
    for symbols in SIBLINGS.values():
        for sample in symbols:
            assert not _SAME_TARGET.search(sample), sample


@pytest.mark.parametrize("name", sorted(SIBLINGS))
def test_siblings_drop_the_same_targets(name):
    text = (DS / name).read_text(encoding="utf-8")
    hits = [
        f"{name}:{n}: {line.strip()}"
        for n, line in enumerate(text.splitlines(), 1)
        if _SAME_TARGET.search(line)
    ]
    assert not hits, "cite by symbol, not line:\n" + "\n".join(hits)
    flat = _flat(text)
    for symbol in SIBLINGS[name]:
        assert symbol in flat, f"{name}: {symbol}"


def test_each_resist_is_summed_once():
    assert _compute_ehp_line("eff_armor = armor") == (
        "eff_armor = armor + bonus_armor + ext_armor + item_resist_armor "
        "+ rune_resist_armor"
    )
    assert _compute_ehp_line("eff_mr = mr") == (
        "eff_mr = mr + bonus_mr + ext_mr + item_resist_mr + rune_resist_mr"
    )


def test_two_per_type_expressions_divide_by_the_resist_once():
    phys = _compute_ehp_line("physical_ehp = (")
    mag = _compute_ehp_line("magical_ehp = (")
    true = _compute_ehp_line("true_ehp = (")
    assert phys.count("_armor_factor(eff_armor)") == 1 and "eff_mr" not in phys
    assert mag.count("_armor_factor(eff_mr)") == 1 and "eff_armor" not in mag
    assert "eff_armor" not in true and "eff_mr" not in true


def test_blended_ehp_is_one_enemy_share_sum():
    src = inspect.getsource(ehp.compute_ehp)
    assert (
        "blended_ehp = (\n"
        "        physical_ehp * enemy_ad_share\n"
        "        + magical_ehp * enemy_ap_share\n"
        "        + true_ehp * enemy_true_share\n"
        "    )"
    ) in src


def test_gap2_header_comment_holds_both_rejects():
    src = inspect.getsource(_passive_damage_overrides)
    start = src.index("# GAP-2 CASTER-DEFENSIVE-STAT passives")
    header = _flat(src[start : src.index('("Taric", "P", 0)', start)])
    assert "K'Sante P All Out Bonus" in header and "bilinear" in header
    assert "Rammus W Defensive Ball Curl" in header
    assert "reactive on-being-hit reflect" in header


def test_all_out_bonus_is_its_own_bilinear_seam():
    pdo = _passive_damage_overrides
    entry = pdo._ALL_OUT_BONUS_OVERRIDES[("KSante", "P", 0)]
    assert len(entry.bilinear_terms) == 2
    assert entry.conditional_probability == 0.5
    assert ("KSante", "P", 0) in pdo._PASSIVE_DAMAGE_OVERRIDES
    assert pdo._PASSIVE_DAMAGE_OVERRIDES[("KSante", "P", 0)] is not entry


def test_taric_and_galio_rows_hold():
    pdo = _passive_damage_overrides
    taric = pdo._PASSIVE_DAMAGE_OVERRIDES[("Taric", "P", 0)]
    galio = pdo._PASSIVE_DAMAGE_OVERRIDES[("Galio", "P", 0)]
    assert taric.bonus_armor_pct == 15.0 and taric.attribute == "Bravado"
    assert galio.bonus_mr_pct == 60.0 and galio.damage_type == "MAGIC"
    assert galio.cadence == "on_hit" and galio.attribute == "Colossal Smash"
    assert "NOT AA-routed: periodic gate" in galio.note
    assert ("Taric", "P", 0) not in pdo._AA_ROUTED_ON_HIT_KEYS
    assert ("Galio", "P", 0) not in pdo._AA_ROUTED_ON_HIT_KEYS
