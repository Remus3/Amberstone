"""S144-D-310..313 - the DS spell-shield and ally-grant registries match the live text they cite.

WHY. Two hand-authored EHP registries copy a duration, a magnitude or a
parsed ``damage_blocks`` series out of quoted ability text:
``_champion_spell_shield_overrides`` (the self block-one CC sub-axis) and
``_passive_ally_grant_overrides`` (resist / revive / flat-HP grants a
champion confers on a teammate). Their own tests pin the literals against
the patch each was seeded at (16.11.1 or 16.12.1), so a patch that rewrites
one of these abilities would move the real value while every guard stays
green.

* S144-D-310: every spell-shield entry (Sivir E, Nocturne W, Fiora W,
  Morgana E) quotes a live sentence, and the window its note states (1.5 s,
  1.5 s, 0.75 s, 5 s) is the live one.
* S144-D-311: every ally resist / revive entry (Orianna E, Braum W, Taric
  W, Renata W) equals its live block series or sentence, with the live unit.
* S144-D-312: every ally flat-HP entry (Janna E, Lulu E, Karma E, Yuumi E,
  Seraphine W, Soraka W, Nami W) equals its live base series, and the AP
  ratio its note says it omits is the live ratio.
* S144-D-313: three prose defects against the live text. The ally-grant
  docstring said the Zilean R heal "is absent from the parsed Meraki
  block"; the live block carries it (600/850/1100 +200% AP), so the only
  deferral reason left is the protected ally's max-HP dependency. The
  spell-shield registry files the Morgana E ALLY cast under the ally-grant
  domain, but the ally-grant docstring did not list it among its
  exclusions. Yuumi E's ally shield is the live "Attached Bonus" (Zoomies
  affects the Anchor instead of Yuumi); the comment and note did not say
  the grant only reaches an ally while she is attached.

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

from agents.daemon_slayer import _champion_spell_shield_overrides as shield_mod
from agents.daemon_slayer import _passive_ally_grant_overrides as ally_mod
from agents.daemon_slayer._champion_spell_shield_overrides import (
    _CHAMPION_SPELL_SHIELD_OVERRIDES as SHIELD,
)
from agents.daemon_slayer._champion_spell_shield_overrides import (
    _SPELL_SHIELD_DURATION_PROB,
    _SPELL_SHIELD_PARRY_PROB,
    _SPELL_SHIELD_REACTIVE_PROB,
)
from agents.daemon_slayer._passive_ally_grant_overrides import (
    _ALLY_FLAT_HP_GRANT_OVERRIDES as FLAT_HP,
)
from agents.daemon_slayer._passive_ally_grant_overrides import (
    _ALLY_REVIVE_PROB,
    _ALLY_SHIELD_HEAL_PROB,
)
from agents.daemon_slayer._passive_ally_grant_overrides import (
    _PASSIVE_ALLY_GRANT_OVERRIDES as ALLY,
)
from agents.daemon_slayer._passive_resist_overrides import _ACTIVE_RESIST_PROB

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


def test_every_row_has_a_live_text_test_here() -> None:
    """A new row lands red here until it gets its own live-text test below."""
    assert set(SHIELD) == {
        ("Sivir", "E", 0),
        ("Nocturne", "W", 0),
        ("Fiora", "W", 0),
        ("Morgana", "E", 0),
    }
    assert set(ALLY) == {
        ("Orianna", "E", 0),
        ("Braum", "W", 0),
        ("Taric", "W", 0),
        ("Renata", "W", 0),
    }
    assert set(FLAT_HP) == {
        ("Janna", "E", 0),
        ("Lulu", "E", 0),
        ("Karma", "E", 0),
        ("Yuumi", "E", 0),
        ("Seraphine", "W", 0),
        ("Soraka", "W", 0),
        ("Nami", "W", 0),
    }


@pytest.mark.parametrize("row", sorted(set(SHIELD) | set(ALLY) | set(FLAT_HP)))
def test_every_key_is_a_live_form_named_by_its_attribute(row: tuple[str, str, int]) -> None:
    champion, key, form_index = row
    form = _form(champion, key, form_index)
    entry = SHIELD.get(row) or ALLY.get(row) or FLAT_HP[row]
    assert entry.attribute == form["name"], f"{row}: attribute {entry.attribute!r} != live name"


# --- S144-D-310: spell shields ------------------------------------------------


@pytest.mark.parametrize("champion,key", [("Sivir", "E"), ("Nocturne", "W")])
def test_reactive_spell_shield_window_matches_live_text(champion: str, key: str) -> None:
    m = _one_match(
        _form(champion, key),
        rf"^Active: {champion} gains a spell shield for ([\d.]+) seconds\. "
        r"Upon successfully blocking a hostile effect",
    )
    e = SHIELD[(champion, key, 0)]
    assert _f(m[1]) == 1.5 and "reactive 1.5s block of the next hostile effect" in e.note
    assert e.block_pct == 100.0
    assert e.conditional_probability == _SPELL_SHIELD_REACTIVE_PROB


def test_fiora_riposte_parry_matches_live_text() -> None:
    form = _form("Fiora", "W")
    m = _one_match(
        form,
        r"^Active: Fiora enters a defensive stance for ([\d.]+) seconds, during which she is unable "
        r"to act, prevents all incoming non- ?turret damage, and gains debuff immunity and crowd "
        r"control immunity\.",
    )
    _one_match(form, r"If Riposte negates at least one hostile immobilizing effect, Fiora stuns")
    e = SHIELD[("Fiora", "W", 0)]
    assert _f(m[1]) == 0.75 and "0.75s pre-timed parry" in e.note
    assert e.block_pct == 100.0
    assert e.conditional_probability == _SPELL_SHIELD_PARRY_PROB


def test_morgana_black_shield_matches_live_text() -> None:
    form = _form("Morgana", "E")
    m = _one_match(
        form,
        r"^Active: Morgana grants a shield to the target allied champion or herself for ([\d.]+) "
        r"seconds, which absorbs incoming magic damage and grants crowd control immunity while it "
        r"holds\.$",
    )
    e = SHIELD[("Morgana", "E", 0)]
    assert _f(m[1]) == 5.0 and "5s magic-gated CC-immunity shield" in e.note
    assert e.block_pct == 100.0
    assert e.conditional_probability == _SPELL_SHIELD_DURATION_PROB
    # The magic-only shield amount is a block of its own (not on this axis).
    assert _series(form, "Magic Shield Strength") == [
        ([100.0, 155.0, 210.0, 265.0, 320.0], ""),
        ([70.0] * 5, "% AP"),
    ]


# --- S144-D-311: ally resist and revive ---------------------------------------


def test_orianna_command_protect_matches_live_block() -> None:
    form = _form("Orianna", "E")
    _one_match(
        form,
        r"^Passive: The Ball grants bonus armor and bonus magic resistance to the unit it is attached to\.$",
    )
    m = _one_match(form, r"granting the target a shield for ([\d.]+) seconds upon arrival")
    e = ALLY[("Orianna", "E", 0)]
    ((vals, unit),) = _series(form, "Bonus Resistances")
    assert unit == "" and tuple(vals) == e.armor == e.mr == (6.0, 12.0, 18.0, 24.0, 30.0)
    assert e.rank_scaled and e.conditional_probability == 1.0
    assert _f(m[1]) == 2.5 and "2.5s shield is ability_hps throughput" in e.note


def test_braum_stand_behind_me_ally_series_matches_live_block() -> None:
    form = _form("Braum", "W")
    m = _one_match(
        form,
        r"grants himself and the ally bonus armor and bonus magic resistance for ([\d.]+) seconds",
    )
    e = ALLY[("Braum", "W", 0)]
    (a_base, a_unit), (a_pct, a_pct_unit) = _series(form, "Ally Bonus Armor")
    (m_base, m_unit), (m_pct, m_pct_unit) = _series(form, "Ally Bonus Magic Resistance")
    assert a_unit == m_unit == ""
    assert tuple(a_base) == e.armor == tuple(m_base) == e.mr == (20.0, 25.0, 30.0, 35.0, 40.0)
    # The omitted second series: 12, unit "% bonus armor" / "% bonus magic
    # resistance" (whose bonus resist it reads is S144-D-309, unresolved).
    assert set(a_pct) == set(m_pct) == {12.0}
    assert (a_pct_unit, m_pct_unit) == ("% bonus armor", "% bonus magic resistance")
    assert e.armor_pct == e.mr_pct == 0.0
    assert "+12%-of-bonus second series omitted" in e.note
    assert _f(m[1]) == 3.0 and "3s active" in e.note
    assert e.conditional_probability == _ACTIVE_RESIST_PROB and e.rank_scaled


def test_taric_bastion_ally_armor_matches_live_block() -> None:
    form = _form("Taric", "W")
    _one_match(form, r"While the tether persists, the ally also gains the bonus armor")
    e = ALLY[("Taric", "W", 0)]
    ((vals, unit),) = _series(form, "Bonus Armor")
    assert unit == "% of Taric's armor" and e.pct_base == "total"
    assert tuple(vals) == e.armor_pct == (6.0, 7.0, 8.0, 9.0, 10.0)
    assert e.mr_pct == 0.0 and e.armor == e.mr == 0.0
    assert not any("magic resist" in b["attribute"].lower() for b in form["damage_blocks"])
    assert e.conditional_probability == 1.0 and e.rank_scaled


def test_renata_bailout_revive_matches_live_text() -> None:
    m = _one_match(
        _form("Renata", "W"),
        r"If the target takes fatal damage while Bailout is active, they are restored to (\d+)% of "
        r"their maximum health but suffer a true damage burn",
    )
    e = ALLY[("Renata", "W", 0)]
    assert _f(m[1]) / 100.0 == e.revived_hp_fraction == 1.0
    assert "100% max health" in e.note
    assert e.conditional_probability == _ALLY_REVIVE_PROB


# --- S144-D-312: ally flat-HP shields and heals -------------------------------

# row -> (block attribute, entry field, live AP ratio the note says it omits)
_FLAT_HP_BLOCKS = {
    ("Janna", "E", 0): ("Shield Strength", "shield_hp", 55.0),
    ("Lulu", "E", 0): ("Shield Strength", "shield_hp", 55.0),
    ("Karma", "E", 0): ("Shield Strength", "shield_hp", 60.0),
    ("Yuumi", "E", 0): ("Shield", "shield_hp", 30.0),
    ("Seraphine", "W", 0): ("Shield Strength", "shield_hp", 20.0),
    ("Soraka", "W", 0): ("Heal", "heal_hp", 50.0),
    ("Nami", "W", 0): ("Heal", "heal_hp", 40.0),
}


def test_flat_hp_block_table_covers_the_registry() -> None:
    assert set(_FLAT_HP_BLOCKS) == set(FLAT_HP)


@pytest.mark.parametrize("row", sorted(_FLAT_HP_BLOCKS))
def test_flat_hp_base_series_and_omitted_ratio_match_live_block(row: tuple[str, str, int]) -> None:
    attribute, field, ratio = _FLAT_HP_BLOCKS[row]
    form = _form(*row)
    e = FLAT_HP[row]
    (base, base_unit), (ap, ap_unit) = _series(form, attribute)
    assert base_unit == "" and ap_unit == "% AP"
    assert tuple(base) == getattr(e, field), f"{row}: {field} != live {attribute}"
    other = "heal_hp" if field == "shield_hp" else "shield_hp"
    assert getattr(e, other) == 0.0
    assert set(ap) == {ratio}
    assert f"+{ratio:g}% AP omitted" in e.note
    assert e.conditional_probability == _ALLY_SHIELD_HEAL_PROB and e.rank_scaled


def test_nami_minimum_heal_band_is_the_live_second_block() -> None:
    form = _form("Nami", "W")
    (base, _), _ap = _series(form, "Minimum Heal")
    assert base == [44.0, 64.0, 84.0, 104.0, 124.0]
    assert "Minimum Heal band variant omitted" in FLAT_HP[("Nami", "W", 0)].note


def test_seraphine_heal_half_is_target_relative_live() -> None:
    form = _form("Seraphine", "W")
    ((vals, unit),) = _series(form, "Heal Per Ally")
    assert unit == "% of target's missing health" and vals == [3.0, 3.5, 4.0, 4.5, 5.0]
    assert "missing-HP heal half is target-relative" in FLAT_HP[("Seraphine", "W", 0)].note


# --- S144-D-313: prose against the live text ----------------------------------


def test_zilean_chronoshift_heal_is_in_the_live_block_and_the_docstring_says_so() -> None:
    form = _form("Zilean", "R")
    assert _series(form, "Heal") == [([600.0, 850.0, 1100.0], ""), ([200.0] * 3, "% AP")]
    akshan = _form("Akshan", "W")
    assert not [b for b in akshan["damage_blocks"] if "heal" in b["attribute"].lower()]
    doc = ally_mod.__doc__ or ""
    assert "absent from the parsed Meraki block" not in doc
    assert "600/850/1100 (+200% AP)" in doc
    test_src = (Path(__file__).parent / "test_passive_ally_grant_overrides_item289.py").read_text(encoding="utf-8")
    assert "AND the value is absent from the parsed block" not in test_src


def test_morgana_ally_cast_is_a_documented_ally_grant_exclusion() -> None:
    _one_match(_form("Morgana", "E"), r"grants a shield to the target allied champion or herself")
    assert "ally cast is the ally-grant domain" in SHIELD[("Morgana", "E", 0)].note
    doc = " ".join((ally_mod.__doc__ or "").split())
    assert "Morgana E Black Shield" in doc
    assert ("Morgana", "E", 0) not in ALLY and ("Morgana", "E", 0) not in FLAT_HP


def test_yuumi_zoomies_ally_shield_is_the_attached_bonus() -> None:
    form = _form("Yuumi", "E")
    _one_match(form, r"^Active: Yuumi grants herself a shield")
    _one_match(form, r"^Attached Bonus: Zoomies affects the Anchor instead of Yuumi")
    e = FLAT_HP[("Yuumi", "E", 0)]
    assert "Attached Bonus" in e.note and "Anchor" in e.note
    src = inspect.getsource(ally_mod)
    assert "# Yuumi E Zoomies: shield 65/90/115/140/165 (+30% AP) by E rank.\n" not in src


def test_spell_shield_module_quotes_stay_live() -> None:
    src = " ".join(inspect.getsource(shield_mod).split())
    for quote in (
        "Sivir gains a spell shield for 1.5 seconds",
        "Nocturne gains a spell shield for 1.5",
        "Fiora enters a defensive stance for 0.75 seconds",
        "for 5 seconds, which absorbs incoming magic damage and grants crowd control immunity",
    ):
        assert quote in src, quote
