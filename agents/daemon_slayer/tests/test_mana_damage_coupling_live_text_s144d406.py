"""S144-D-406 - the DS mana -> damage coupling registry matches the live data it cites.

WHY. ``_mana_damage_coupling`` seeds Blitzcrank R "Static Field" from a
machine census of ``champion_abilities.json`` and rejects Kassadin and Ryze by
archetype route. Its tests (``test_mana_damage_coupling_rm118.py``,
``test_mana_coupling_transport_rm118.py``) pin the arithmetic and the wiring,
never the cited data, so a patch that moved the census, the 2 percent or the
cooldown would leave every guard green.

Checked against the CURRENT patch (``data/daemon_slayer/current.txt``):

* the census: every ``caster_max_mp_pct`` / ``caster_bonus_mp_pct`` block is
  exactly the eight the docstring lists, and ``caster_mr_pct`` carries none;
* the seeded row: form name, field, flat value, pool, damage type, the
  "sole mana-scaling block" claim and the 60/40/20 s cooldown;
* the rejects: Kassadin and Ryze tags, Kassadin's 2 + 4 == 6 sub-component
  sum, and Blitzcrank's Tank-primary tag;
* the three coupling registries stay disjoint.

DEFECT FIXED. The docstring said the 2 percent max-mana damage lands "on every
detonation". The mana-scaling block is the R PASSIVE lightning bolt (wiki
``leveling_raw``: 50 to 150 (+ 30 to 50% AP) (+ 2% maximum mana)); the active
detonation (``leveling2_raw``: 275 to 525 (+ 100% AP)) carries no mana term.
The docstring and the comments now say so. No registry value changed, so every
scorer output is byte-identical.
"""

from __future__ import annotations

import json
import re
from functools import cache
from pathlib import Path
from typing import Any

import pytest

from agents.daemon_slayer import _mana_damage_coupling as mana_mod
from agents.daemon_slayer._health_damage_coupling import _CHAMPION_HEALTH_DAMAGE_COUPLING
from agents.daemon_slayer._mana_damage_coupling import (
    _CHAMPION_MANA_DAMAGE_COUPLING,
    _ULTIMATE_CAST_PROB,
)
from agents.daemon_slayer._resist_damage_coupling import _CHAMPION_RESIST_DAMAGE_COUPLING

_REPO_ROOT = Path(__file__).resolve().parents[3]
_DATA = _REPO_ROOT / "data" / "daemon_slayer"
_DOC = " ".join((mana_mod.__doc__ or "").split())
_SOURCE = Path(mana_mod.__file__).read_text(encoding="utf-8")
_SOURCE_FLAT = " ".join(re.sub(r"(?m)^\s*#\s?", " ", _SOURCE).split())

_MANA_FIELDS = ("caster_max_mp_pct", "caster_bonus_mp_pct")

# (champion, slot, form_index, block_index) -> (field, per-rank values), as
# the module docstring's PROVENANCE census lists them.
_EXPECTED_CENSUS = {
    ("Blitzcrank", "R", 0, 0): ("caster_max_mp_pct", [2.0, 2.0, 2.0]),
    ("Kassadin", "R", 0, 0): ("caster_max_mp_pct", [2.0, 2.0, 2.0]),
    ("Kassadin", "R", 0, 1): ("caster_max_mp_pct", [1.0, 1.0, 1.0]),
    ("Kassadin", "R", 0, 2): ("caster_max_mp_pct", [4.0, 4.0, 4.0]),
    ("Kassadin", "R", 0, 3): ("caster_max_mp_pct", [6.0, 6.0, 6.0]),
    ("Ryze", "Q", 0, 0): ("caster_bonus_mp_pct", [2.0] * 5),
    ("Ryze", "W", 0, 0): ("caster_bonus_mp_pct", [4.0] * 5),
    ("Ryze", "E", 0, 0): ("caster_bonus_mp_pct", [2.0] * 5),
}


def _patch_dir() -> Path:
    return _DATA / (_DATA / "current.txt").read_text(encoding="utf-8").strip()


@cache
def _snapshot(name: str) -> Any:
    raw = json.loads((_patch_dir() / name).read_text(encoding="utf-8"))
    return raw.get("data", raw) if isinstance(raw, dict) else raw


def _abilities() -> dict[str, Any]:
    return _snapshot("champion_abilities.json")


def _tags(champion: str) -> list[str]:
    return list(_snapshot("champions.json")[champion]["tags"])


def _blocks():
    for champ, kit in _abilities().items():
        for slot, forms in kit.items():
            for fi, form in enumerate(forms):
                for bi, block in enumerate(form.get("damage_blocks") or []):
                    yield (champ, slot, fi, bi), form, block


def test_census_is_exactly_the_eight_documented_blocks():
    seen = {}
    for key, _form, block in _blocks():
        for field in _MANA_FIELDS:
            if field in block:
                seen[key] = (field, list(block[field]))
    assert seen == _EXPECTED_CENSUS
    assert len({k[0] for k in seen}) == 3
    assert "EIGHT" in _DOC and "THREE champions" in _DOC


def test_caster_mr_pct_still_carries_zero_blocks():
    assert not [k for k, _f, b in _blocks() if "caster_mr_pct" in b]
    assert "``caster_mr_pct`` field is wired in the schema but carries ZERO" in _DOC


def test_registry_is_exactly_blitzcrank():
    assert set(_CHAMPION_MANA_DAMAGE_COUPLING) == {"Blitzcrank"}


def test_blitzcrank_row_matches_live_block():
    entry = _CHAMPION_MANA_DAMAGE_COUPLING["Blitzcrank"]
    form = _abilities()["Blitzcrank"]["R"][0]
    block = form["damage_blocks"][0]
    assert form["name"] == entry.attribute == "Static Field"
    assert form["damage_type"] == "MAGIC" and block["attribute"] == "Magic Damage"
    assert set(block["caster_max_mp_pct"]) == {entry.max_mp_pct} == {2.0}
    assert entry.bonus_mp_pct == 0.0 and entry.pct_base == "total"
    assert entry.conditional_probability == _ULTIMATE_CAST_PROB
    assert "R: 2% TOTAL max mana as MAGIC damage" in entry.note


def test_blitzcrank_mana_block_is_the_only_one_in_his_kit():
    hits = [k for k, _f, b in _blocks() if k[0] == "Blitzcrank" and any(f in b for f in _MANA_FIELDS)]
    assert hits == [("Blitzcrank", "R", 0, 0)]


def test_static_field_cooldown_quoted_in_comment_and_note_is_live():
    cd = _abilities()["Blitzcrank"]["R"][0]["cooldown"]
    assert cd == [60.0, 40.0, 20.0]
    assert "60/40/20 second cooldown" in _SOURCE_FLAT
    assert "(60/40/20s cooldown)" in _CHAMPION_MANA_DAMAGE_COUPLING["Blitzcrank"].note


def test_mana_term_rides_the_passive_bolt_not_the_detonation():
    form = _abilities()["Blitzcrank"]["R"][0]
    passive_block, active_block = form["damage_blocks"]
    assert passive_block["base"] == [50.0, 100.0, 150.0]
    assert active_block["base"] == [275.0, 400.0, 525.0]
    assert not any(f in active_block for f in _MANA_FIELDS)
    wiki = _snapshot("wiki_ability_stats.json")["abilities"]["Blitzcrank/Static Field"]
    assert "50 to 150" in wiki["leveling_raw"] and "2% '''maximum''' mana" in wiki["leveling_raw"]
    assert "275 to 525" in wiki["leveling2_raw"] and "mana" not in wiki["leveling2_raw"]
    descs = " ".join(form["effects_descriptions"])
    assert "Passive: While Static Field is not on cooldown" in descs
    assert "one stack is consumed to deal them magic damage" in descs


def test_docstring_places_the_mana_term_on_the_passive():
    assert "on every detonation" not in _DOC
    assert (
        'Blitzcrank R "Static Field" deals 2 percent of his maximum mana as magic damage '
        "with every lightning bolt of its PASSIVE" in _DOC
    )
    assert "the active detonation's 275 / 400 / 525 block carries no mana term" in _DOC
    assert "The mana term rides the R PASSIVE, which runs only while R is off cooldown" in _SOURCE_FLAT
    assert "This block is the PASSIVE lightning bolt; the active detonation" in _SOURCE_FLAT


@pytest.mark.parametrize(
    ("champion", "tags"),
    [("Blitzcrank", ["Tank", "Support"]), ("Kassadin", ["Assassin", "Mage"]), ("Ryze", ["Mage"])],
)
def test_route_tags_quoted_in_docstring_are_live(champion, tags):
    assert _tags(champion) == tags
    assert f"tags ``{json.dumps(tags)}``" in _DOC


def test_kassadin_sub_components_sum_to_the_maximum():
    blocks = _abilities()["Kassadin"]["R"][0]["damage_blocks"]
    labels = [b["attribute"] for b in blocks]
    assert labels == ["Magic Damage", "Bonus Damage Per Stack", "Maximum Bonus Damage", "Maximum Magic Damage"]
    base, _per, max_bonus, total = (b["caster_max_mp_pct"][0] for b in blocks)
    assert base + max_bonus == total
    assert '"Bonus Damage Per Stack" 1.0' in _DOC and '"Maximum Bonus Damage" 4.0' in _DOC


def test_three_coupling_registries_are_disjoint():
    mana = set(_CHAMPION_MANA_DAMAGE_COUPLING)
    health = set(_CHAMPION_HEALTH_DAMAGE_COUPLING)
    resist = set(_CHAMPION_RESIST_DAMAGE_COUPLING)
    assert not (mana & health) and not (mana & resist) and not (health & resist)
