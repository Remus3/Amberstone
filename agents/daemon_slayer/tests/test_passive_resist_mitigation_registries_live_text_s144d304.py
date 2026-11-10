"""S144-D-304..307 - the DS resist and damage-reduction registries match the live text they cite.

WHY. Three hand-authored EHP registries copy a magnitude out of quoted
ability text or a parsed ``damage_blocks`` series:
``_passive_resist_overrides`` (bonus armor / MR, the EHP denominator),
``_passive_mitigation_overrides`` (flat-percent damage reduction) and
``_passive_flat_mitigation_overrides`` (per-instance flat reduction). Their
tests pin the literals against the patch each was seeded at (16.11.1 or
16.12.1), so a patch that rewrites one of these abilities would move the real
value while every guard stays green.

* S144-D-304: every resist entry whose value is INLINE in the effects text
  (Garen, Wukong, Shyvana, Sejuani, Gwen, Pantheon, Poppy, Rell, Jayce,
  Thresh) equals its live sentence, and every duration its note states equals
  the live one.
* S144-D-305: every resist entry whose value lives in a parsed block (Olaf,
  Nasus, Kennen, Hecarim, Rammus, Malphite, Taric, Graves, Singed, Braum,
  Leona, Jax) equals the live series, with the live unit. Two omission
  reasons were wrong against the live block labels: Braum W's 36% is the
  second series of the "Self Bonus Armor" / "Self Bonus Magic Resistance"
  blocks, unit "% bonus armor" (a percent of Braum's own bonus resist on his
  own grant), not "36% of the ALLY's bonus resist (cross-champion)"; Leona
  W's 20% is the second series of her own "Bonus Armor" block, unit "% bonus
  armor", so "attribution uncertain - own-bonus not confirmed" no longer
  holds. Both stay OMITTED (seeding them is a Tier-2 value change); the
  module docstring, the item-270 comment, both comments and both notes now
  give the measured reason. The same comment said Singed R carries a
  separate "% MS" block; the live form has no movement-speed block.
* S144-D-306: every percent-DR entry (Kassadin, Nilah, K'Sante, Briar,
  Irelia) equals its live sentence; the Nilah comment called the ability
  "Slipstream" (her E) though the entry and the live form are Jubilant Veil.
* S144-D-307: every flat-DR entry (Fizz, Amumu, Leona) equals its live
  sentence or block, and Leona's stated "10-14s cooldown" is the live range.

MEASURED 2026-11-09 (``data/daemon_slayer/current.txt`` = 16.22.1): every
literal matched its live text. Guards plus comment / note fixes; no registry
value changes, so the scorer output is byte-identical.
"""

from __future__ import annotations

import inspect
import json
import re
from functools import cache
from pathlib import Path
from typing import Any

import pytest

from agents.daemon_slayer import _passive_mitigation_overrides as pct_mod
from agents.daemon_slayer import _passive_resist_overrides as resist_mod
from agents.daemon_slayer._passive_flat_mitigation_overrides import (
    _PASSIVE_FLAT_MITIGATION_OVERRIDES as FLAT,
)
from agents.daemon_slayer._passive_mitigation_overrides import ANY, MAG, PHYS
from agents.daemon_slayer._passive_mitigation_overrides import (
    _PASSIVE_MITIGATION_OVERRIDES as PCT,
)
from agents.daemon_slayer._passive_resist_overrides import (
    _ASSUMED_SOUL_COUNT,
    _FORM_OCCUPANCY_PROB,
)
from agents.daemon_slayer._passive_resist_overrides import (
    _PASSIVE_RESIST_OVERRIDES as RESIST,
)

_REPO_ROOT = Path(__file__).resolve().parents[3]
_DATA = _REPO_ROOT / "data" / "daemon_slayer"


def _patch_dir() -> Path:
    return _DATA / (_DATA / "current.txt").read_text(encoding="utf-8").strip()


@cache
def _abilities() -> dict[str, Any]:
    raw = json.loads((_patch_dir() / "champion_abilities.json").read_text(encoding="utf-8"))
    return raw.get("data", raw)


def _form(champion: str, key: str, form_index: int = 0) -> dict[str, Any]:
    hits = [f for f in _abilities()[champion][key] if f.get("form_index", 0) == form_index]
    assert len(hits) == 1, f"{champion} {key}[{form_index}]: {len(hits)} forms"
    return hits[0]


def _one_match(form: dict[str, Any], pattern: str) -> re.Match[str]:
    rx = re.compile(pattern)
    hits = [m for s in form["effects_descriptions"] if (m := rx.search(s))]
    assert len(hits) == 1, f"{form['name']}: {len(hits)} sentences match {pattern}"
    return hits[0]


def _series(form: dict[str, Any], attribute: str) -> list[tuple[list[float], str]]:
    """Every value series of the ONE block named ``attribute``, with its unit."""
    blocks = [b for b in form.get("damage_blocks", []) if b.get("attribute") == attribute]
    assert len(blocks) == 1, f"{form['name']}: {len(blocks)} '{attribute}' blocks"
    out = []
    for mod in blocks[0]["raw_modifiers"]:
        units = set(mod["units"])
        assert len(units) == 1, f"{form['name']} {attribute}: mixed units {units}"
        out.append(([float(v) for v in mod["values"]], units.pop()))
    return out


def _f(text: str) -> float:
    return float(text)


# --- registry anchors ---------------------------------------------------------

_RESIST_INLINE = {
    ("Garen", "W", 0),
    ("MonkeyKing", "P", 0),
    ("Shyvana", "P", 0),
    ("Sejuani", "P", 0),
    ("Gwen", "W", 0),
    ("Pantheon", "E", 0),
    ("Poppy", "W", 0),
    ("Rell", "W", 1),
    ("Jayce", "R", 1),
    ("Thresh", "P", 0),
}
_RESIST_BLOCK = {
    ("Olaf", "R", 0),
    ("Nasus", "R", 0),
    ("Kennen", "R", 0),
    ("Hecarim", "W", 0),
    ("Rammus", "W", 0),
    ("Malphite", "W", 0),
    ("Taric", "W", 0),
    ("Graves", "E", 0),
    ("Singed", "R", 0),
    ("Braum", "W", 0),
    ("Leona", "W", 0),
    ("Jax", "R", 0),
}


def test_every_row_has_a_live_text_test_here() -> None:
    """A new row lands red here until it gets its own live-text test below."""
    assert _RESIST_INLINE.isdisjoint(_RESIST_BLOCK)
    assert set(RESIST) == _RESIST_INLINE | _RESIST_BLOCK
    assert len(RESIST) == 22
    assert set(PCT) == {
        ("Kassadin", "P", 0),
        ("Nilah", "W", 0),
        ("KSante", "W", 0),
        ("Briar", "E", 0),
        ("Irelia", "W", 0),
    }
    assert set(FLAT) == {("Fizz", "P", 0), ("Amumu", "E", 0), ("Leona", "W", 0)}


@pytest.mark.parametrize("row", sorted(set(RESIST) | set(PCT) | set(FLAT)))
def test_every_key_is_a_live_form_named_by_its_attribute(row: tuple[str, str, int]) -> None:
    champion, key, form_index = row
    form = _form(champion, key, form_index)
    entry = RESIST.get(row) or PCT.get(row) or FLAT[row]
    text = " ".join([form["name"], *form["effects_descriptions"]])
    assert entry.attribute in text, f"{row}: attribute {entry.attribute!r} not in live form"


# --- S144-D-304: resist values inline in the effects text ---------------------


def test_garen_courage_cap_matches_live_text() -> None:
    m = _one_match(
        _form("Garen", "W"),
        r"gains ([\d.]+) bonus armor and ([\d.]+) bonus magic resistance, up to a maximum of (\d+) bonus resistances each",
    )
    e = RESIST[("Garen", "W", 0)]
    assert (_f(m[1]), _f(m[2])) == (0.2, 0.2)
    assert e.armor == e.mr == _f(m[3]) == 30.0
    assert e.conditional_probability == 1.0


def test_wukong_stone_skin_matches_live_text() -> None:
    form = _form("MonkeyKing", "P")
    m = _one_match(form, r"^Innate: Wukong gains (\d+) : (\d+) \(based on level\) bonus armor")
    e = RESIST[("MonkeyKing", "P", 0)]
    assert len(e.armor) == 18 and e.level_scaled
    assert (e.armor[0], e.armor[-1]) == (_f(m[1]), _f(m[2])) == (6.0, 10.0)
    assert e.mr == 0.0
    cap = _one_match(form, r"up to a maximum of (\d+) : (\d+) \(based on level\) bonus armor")
    assert (_f(cap[1]), _f(cap[2])) == (36.0, 60.0), "comment: Strength of Stone 36:60 cap omitted"
    assert "Strength of Stone combat stacks omitted" in e.note


def test_shyvana_fury_base_matches_live_text() -> None:
    m = _one_match(
        _form("Shyvana", "P"),
        r"gains (\d+) bonus armor and (\d+) bonus magic resistance, which are each increased by (\d+) for every elemental drake",
    )
    e = RESIST[("Shyvana", "P", 0)]
    assert (e.armor, e.mr) == (_f(m[1]), _f(m[2])) == (5.0, 5.0)
    assert "per-drake +5" in e.note and _f(m[3]) == 5.0


def test_sejuani_frost_armor_matches_live_text() -> None:
    form = _form("Sejuani", "P")
    m = _one_match(
        form,
        r"(\d+) \(\+ (\d+)% bonus armor\) bonus armor, and (\d+) \(\+ (\d+)% bonus magic resistance\) bonus magic resistance",
    )
    e = RESIST[("Sejuani", "P", 0)]
    assert (e.armor, e.mr) == (_f(m[1]), _f(m[3])) == (10.0, 10.0)
    assert (_f(m[2]), _f(m[4])) == (75.0, 75.0), "note: +75% bonus-resist sub-terms omitted"
    linger = _one_match(form, r"lingers for (\d+) seconds after taking damage")
    assert f"lingers {linger[1]}s" in e.note


def test_gwen_hallowed_mist_matches_live_text() -> None:
    m = _one_match(_form("Gwen", "W"), r"gains (\d+) \(\+ (\d+)% AP\) bonus armor and bonus magic resistance")
    e = RESIST[("Gwen", "W", 0)]
    assert (e.armor, e.mr) == (_f(m[1]), _f(m[1])) == (22.0, 22.0)
    assert f"+{m[2]}% AP omitted" in e.note


def test_pantheon_mortal_will_matches_live_text() -> None:
    m = _one_match(
        _form("Pantheon", "E"),
        r"gains (\d+) : (\d+) \(based on level\) \(\+ ([\d.]+)% bonus health\) bonus armor and bonus magic resistance for (\d+) seconds",
    )
    e = RESIST[("Pantheon", "E", 0)]
    for series in (e.armor, e.mr):
        assert len(series) == 18
        assert (series[0], series[-1]) == (_f(m[1]), _f(m[2])) == (5.0, 30.0)
    assert f"+{m[3]}% bonus HP omitted" in e.note
    assert f"for {m[4]}s after recast" in e.note


def test_poppy_stubborn_to_a_fault_matches_live_text() -> None:
    m = _one_match(
        _form("Poppy", "W"),
        r"increases her total armor and total magic resistance by (\d+)%, doubled to (\d+)% while she is below (\d+)% maximum health",
    )
    e = RESIST[("Poppy", "W", 0)]
    assert e.armor_pct == e.mr_pct == _f(m[1]) == 12.0
    assert e.pct_base == "total"
    assert e.armor_pct + e.low_hp_pct_armor == e.mr_pct + e.low_hp_pct_mr == _f(m[2]) == 24.0
    assert e.low_hp_threshold == _f(m[3]) / 100.0 == 0.40


def test_rell_dismounted_matches_live_text() -> None:
    m = _one_match(
        _form("Rell", "W", 1),
        r"While Rell is Dismounted, she gains (\d+)% bonus armor, (\d+)% bonus magic resistance",
    )
    e = RESIST[("Rell", "W", 1)]
    assert (e.armor_pct, e.mr_pct) == (_f(m[1]), _f(m[2])) == (15.0, 15.0)
    assert e.pct_base == "bonus"


def test_jayce_hammer_stance_matches_live_text() -> None:
    m = _one_match(
        _form("Jayce", "R", 1),
        r"gaining (\d+) / (\d+) / (\d+) / (\d+) \(based on level\) \(\+ ([\d.]+)% bonus AD\) bonus armor and bonus magic resistance",
    )
    tiers = [_f(m[i]) for i in range(1, 5)]
    assert tiers == [5.0, 15.0, 25.0, 35.0]
    e = RESIST[("Jayce", "R", 1)]
    for series in (e.armor, e.mr):
        assert len(series) == 18
        assert sorted(set(series)) == tiers
        assert list(series) == sorted(series)
    assert e.conditional_probability == _FORM_OCCUPANCY_PROB
    assert f"+{m[5]}% bonus AD omitted" in e.note
    # Cannon stance (form 0) carries no self resist grant, the reason the row is form-gated.
    cannon = " ".join(_form("Jayce", "R", 0)["effects_descriptions"])
    assert "bonus armor and bonus magic resistance" not in cannon


def test_thresh_damnation_matches_live_text() -> None:
    form = _form("Thresh", "P")
    m = _one_match(form, r"For each stack, Thresh gains (\d+) ability power and (\d+) bonus armor\.")
    e = RESIST[("Thresh", "P", 0)]
    assert e.per_stack_armor == _f(m[2]) == 1.0
    assert e.per_stack_mr == 0.0
    assert e.assumed_stacks == _ASSUMED_SOUL_COUNT
    _one_match(form, r"armor does not increase through growth")


# --- S144-D-305: resist values in a parsed block -------------------------------


@pytest.mark.parametrize(
    ("row", "attribute"),
    [
        (("Olaf", "R", 0), "Bonus Resistances"),
        (("Nasus", "R", 0), "Bonus Resistances"),
        (("Kennen", "R", 0), "Bonus Resistances"),
        (("Hecarim", "W", 0), "Bonus Resistances"),
        (("Singed", "R", 0), "Bonus Stats"),
    ],
)
def test_single_series_block_rows_match_the_live_block(row: tuple[str, str, int], attribute: str) -> None:
    ((values, unit),) = _series(_form(*row), attribute)
    e = RESIST[row]
    assert unit == ""
    assert e.rank_scaled
    assert list(e.armor) == list(e.mr) == values


@pytest.mark.parametrize(
    ("row", "seconds"),
    [
        (("Nasus", "R", 0), 15),
        (("Kennen", "R", 0), 3),
        (("Hecarim", "W", 0), 4),
        (("Singed", "R", 0), 25),
        (("Rammus", "W", 0), 7),
        (("Leona", "W", 0), 3),
    ],
)
def test_stated_active_duration_matches_live_text(row: tuple[str, str, int], seconds: int) -> None:
    m = _one_match(_form(*row), r"for (\d+) seconds")
    assert int(m[1]) == seconds
    assert f"{seconds}s active" in RESIST[row].note


def test_singed_insanity_potion_has_no_movement_speed_block() -> None:
    attrs = [b["attribute"] for b in _form("Singed", "R")["damage_blocks"]]
    assert not [a for a in attrs if "movement" in a.lower() or "MS" in a.split()]
    assert "% MS + the two regen blocks" not in inspect.getsource(resist_mod)


def test_rammus_flat_and_percent_halves_match_the_live_blocks() -> None:
    form = _form("Rammus", "W")
    e = RESIST[("Rammus", "W", 0)]
    for attribute, flat, pct, unit in (
        ("Bonus Armor", e.armor, e.armor_pct, "% total armor"),
        ("Bonus Magic Resistance", e.mr, e.mr_pct, "% total magic resistance"),
    ):
        (fv, fu), (pv, pu) = _series(form, attribute)
        assert (list(flat), fu) == (fv, "")
        assert (list(pct), pu) == (pv, unit)
    assert e.pct_base == "total"


@pytest.mark.parametrize(
    ("row", "unit"),
    [(("Malphite", "W", 0), "% armor"), (("Taric", "W", 0), "% of Taric's armor")],
)
def test_percent_of_total_armor_rows_match_the_live_block(row: tuple[str, str, int], unit: str) -> None:
    ((values, live_unit),) = _series(_form(*row), "Bonus Armor")
    e = RESIST[row]
    assert (list(e.armor_pct), live_unit) == (values, unit)
    assert e.pct_base == "total"
    assert e.mr_pct == 0.0 and e.armor == 0.0


def test_malphite_granite_shield_tier_is_the_omitted_triple() -> None:
    form = _form("Malphite", "W")
    ((base, _),) = _series(form, "Bonus Armor")
    ((tripled, _),) = _series(form, "Increased Bonus Armor")
    assert tripled == [3 * v for v in base]
    _one_match(form, r"tripled while Granite Shield is active")


def test_graves_true_grit_is_the_eight_stack_cap() -> None:
    form = _form("Graves", "E")
    ((per_stack, _),) = _series(form, "Bonus Armor")
    ((cap, _),) = _series(form, "Maximum Bonus Armor")
    e = RESIST[("Graves", "E", 0)]
    assert list(e.armor) == cap == [8 * v for v in per_stack]
    assert e.mr == 0.0


@pytest.mark.parametrize(
    ("row", "armor_attr", "mr_attr", "pct"),
    [
        (("Braum", "W", 0), "Self Bonus Armor", "Self Bonus Magic Resistance", 36.0),
        (("Leona", "W", 0), "Bonus Armor", "Bonus Magic Resistance", 20.0),
    ],
)
def test_two_series_rows_seed_series0_and_the_omitted_series1_is_own_bonus(
    row: tuple[str, str, int], armor_attr: str, mr_attr: str, pct: float
) -> None:
    form = _form(*row)
    e = RESIST[row]
    for attribute, seeded, unit in (
        (armor_attr, e.armor, "% bonus armor"),
        (mr_attr, e.mr, "% bonus magic resistance"),
    ):
        (base, base_unit), (coeff, coeff_unit) = _series(form, attribute)
        assert (list(seeded), base_unit) == (base, "")
        assert set(coeff) == {pct}
        assert coeff_unit == unit
    # The omitted series is a percent of the caster's OWN bonus resist on the
    # caster's own grant, so the omission reason must not call it an ally term
    # or an uncertain attribution.
    assert e.armor_pct == e.mr_pct == 0.0
    assert "% bonus armor" in e.note
    for stale in ("ALLY bonus", "cross-champion", "uncertain"):
        assert stale not in e.note, f"{row}: note still says {stale!r}"


def test_two_series_omission_reasons_are_gone_from_the_module_source() -> None:
    src = inspect.getsource(resist_mod)
    for stale in (
        "ALLY's bonus resist",
        "36% of ALLY bonus",
        "Leona 20% uncertain",
        "attribution uncertain",
        "own-bonus not confirmed",
    ):
        assert stale not in src, f"stale omission reason {stale!r}"


def test_jax_grandmaster_base_and_omitted_series_match_the_live_blocks() -> None:
    form = _form("Jax", "R")
    e = RESIST[("Jax", "R", 0)]
    (armor, au), (armor_ad, aau) = _series(form, "Bonus Armor")
    (mr, mu), (mr_ad, mau) = _series(form, "Bonus Magic Resistance")
    assert (list(e.armor), au) == (armor, "")
    assert (list(e.mr), mu) == (mr, "")
    assert (set(armor_ad), aau, set(mr_ad), mau) == ({40.0}, "% bonus AD", {24.0}, "% bonus AD")
    assert e.mr == tuple(round(0.6 * a, 6) for a in e.armor), "live: MR equal to 60% of the armor"
    _one_match(form, r"bonus magic resistance equal to 60% of that amount")


# --- S144-D-306: percent damage reduction --------------------------------------


def test_kassadin_void_stone_matches_live_text() -> None:
    m = _one_match(_form("Kassadin", "P"), r"takes (\d+)% reduced magic damage")
    assert PCT[("Kassadin", "P", 0)].terms == ((_f(m[1]), MAG),)


def test_nilah_jubilant_veil_matches_live_text_and_comment_names_it() -> None:
    form = _form("Nilah", "W")
    m = _one_match(form, r"for ([\d.]+) seconds, .*reduces all incoming magic damage taken by (\d+)%")
    e = PCT[("Nilah", "W", 0)]
    assert e.terms == ((_f(m[2]), MAG),)
    assert f"the {m[1]}s active" in e.note
    assert form["name"] == e.attribute == "Jubilant Veil"
    src = inspect.getsource(pct_mod)
    assert "Nilah W Slipstream" not in src
    assert "Nilah W Jubilant Veil" in src


@pytest.mark.parametrize(
    ("row", "pattern"),
    [
        (("KSante", "W", 0), r"displacement immunity and (\d+)% damage reduction"),
        (("Briar", "E", 0), r"gains (\d+)% damage reduction"),
    ],
)
def test_all_type_dr_rows_match_live_text(row: tuple[str, str, int], pattern: str) -> None:
    m = _one_match(_form(*row), pattern)
    assert PCT[row].terms == ((_f(m[1]), ANY),)


def test_ksante_all_out_tier_is_the_omitted_75() -> None:
    m = _one_match(_form("KSante", "W"), r"damage reduction is increased to (\d+)%")
    assert m[1] == "75" and "All Out 75%" in PCT[("KSante", "W", 0)].note


def test_irelia_defiant_dance_matches_live_text() -> None:
    m = _one_match(
        _form("Irelia", "W"),
        r"charges for up to ([\d.]+) seconds, .*physical damage by (\d+)% : (\d+)% \(based on level\) "
        r"\(\+ (\d+)% per 100 AP\) and incoming magic damage by (\d+)% : (\d+)% \(based on level\)",
    )
    (phys, pt), (mag, mt) = PCT[("Irelia", "W", 0)].terms
    assert (pt, mt) == (PHYS, MAG)
    assert len(phys) == len(mag) == 18
    assert (phys[0], phys[-1]) == (_f(m[2]), _f(m[3])) == (40.0, 70.0)
    assert (mag[0], mag[-1]) == (_f(m[5]), _f(m[6])) == (20.0, 35.0)
    assert f"the {m[1]}s channel" in PCT[("Irelia", "W", 0)].note


# --- S144-D-307: per-instance flat damage reduction ----------------------------


def test_fizz_nimble_fighter_matches_live_text() -> None:
    m = _one_match(
        _form("Fizz", "P"),
        r"reduces every instance of incoming damage by (\d+) \(\+ (\d+)% AP\), up to a maximum of (\d+)% reduction",
    )
    e = FLAT[("Fizz", "P", 0)]
    assert e.terms == ((_f(m[1]), ANY),)
    assert e.cap_frac == _f(m[3]) / 100.0
    assert m[0].split(", up to")[0][len("reduces ") :] in e.note


def test_amumu_tantrum_matches_the_live_block() -> None:
    form = _form("Amumu", "E")
    (flat, fu), (ar, aru), (mr, mru) = _series(form, "Physical Damage Reduction")
    e = FLAT[("Amumu", "E", 0)]
    assert e.terms == ((tuple(flat), PHYS),) and fu == ""
    assert (set(ar), aru, set(mr), mru) == ({3.0}, "% bonus armor", {3.0}, "% bonus magic resistance")
    m = _one_match(form, r"capped at (\d+)% of the damage instance")
    assert e.cap_frac == _f(m[1]) / 100.0


def test_leona_eclipse_flat_dr_matches_the_live_block_and_cooldown() -> None:
    form = _form("Leona", "W")
    ((flat, fu),) = _series(form, "Flat Damage Reduction")
    e = FLAT[("Leona", "W", 0)]
    assert e.terms == ((tuple(flat), ANY),) and fu == ""
    m = _one_match(form, r"flat damage reduction of up to (\d+)% of the damage instance")
    assert e.cap_frac == _f(m[1]) / 100.0
    cds = [float(v) for v in form["cooldown"]]
    assert f"{min(cds):g}-{max(cds):g}s cooldown" in e.note
