"""S144-D-407 - the DS health -> damage coupling registry matches the live data it cites.

WHY. ``_health_damage_coupling`` seeds eleven champions from a machine census
of ``champion_abilities.json`` (16.14.1 at authoring), takes ONE block per
champion, names every discarded sub-component, peer ability and variant, and
quotes cooldowns and ability text to justify each cadence tier. Its only test
(``test_health_damage_coupling_rm91.py``) pins the arithmetic and the wiring,
never the cited data, so a patch that moved a percent, a cooldown, a tag or a
quoted sentence would leave every guard green.

Checked against the CURRENT patch (``data/daemon_slayer/current.txt``):

* the census: the champions with a ``caster_max_hp_pct`` /
  ``caster_bonus_hp_pct`` damage block are exactly the fourteen, the eleven
  seeded are all Tank-primary, and the three rejects carry the tags quoted;
* every seeded row: form name, the TAKEN block's label, field and flat value,
  the pool that field implies, and the damage type the note names;
* every DISCARDED block the comments name still exists at the stated value,
  and every sub-component sum the comments state still holds;
* every cooldown range the comments and notes quote is the live one;
* every quoted ability sentence is still in the live effects text;
* the Sett / Sion / Poppy / Leona negative controls still carry no
  caster-health block, at the target-health values quoted.

MEASURED 2026-11-10 (current patch 16.22.1): every check holds, so this is a
guard only; no registry value changed and every scorer output is byte-identical.
"""

from __future__ import annotations

import json
import re
from functools import cache
from pathlib import Path
from typing import Any

import pytest

from agents.daemon_slayer import _health_damage_coupling as health_mod
from agents.daemon_slayer._health_damage_coupling import (
    _ABILITY_CAST_PROB,
    _CHAMPION_HEALTH_DAMAGE_COUPLING,
    _GATED_CAST_PROB,
)

_REPO_ROOT = Path(__file__).resolve().parents[3]
_DATA = _REPO_ROOT / "data" / "daemon_slayer"
_DOC = " ".join((health_mod.__doc__ or "").split())
_SOURCE = Path(health_mod.__file__).read_text(encoding="utf-8")
_SOURCE_FLAT = " ".join(re.sub(r"(?m)^\s*#\s?", " ", _SOURCE).split())

_HP_FIELDS = ("caster_max_hp_pct", "caster_bonus_hp_pct")
_POOL = {"caster_max_hp_pct": "total", "caster_bonus_hp_pct": "bonus"}

_CENSUS = {
    "Braum",
    "Chogath",
    "DrMundo",
    "Gnar",
    "KSante",
    "Maokai",
    "Nunu",
    "Sejuani",
    "Shen",
    "Skarner",
    "TahmKench",
    "Vladimir",
    "Volibear",
    "Zac",
}
_REJECTS = {"Gnar": ["Fighter", "Tank"], "Volibear": ["Fighter", "Tank"], "Vladimir": ["Mage", "Fighter"]}

# champion -> (slot, form_index, TAKEN block label, field, value, damage word, cadence)
_ROWS = {
    "Braum": ("Q", 0, "Magic Damage", "caster_max_hp_pct", 2.5, "MAGIC", _ABILITY_CAST_PROB),
    "Chogath": ("R", 0, "Champion True Damage", "caster_bonus_hp_pct", 10.0, "TRUE", _GATED_CAST_PROB),
    "DrMundo": ("E", 0, "Minimum Bonus Physical Damage", "caster_bonus_hp_pct", 7.0, "PHYSICAL", _ABILITY_CAST_PROB),
    "KSante": ("R", 0, "Total Physical Damage", "caster_bonus_hp_pct", 5.0, "PHYSICAL", _GATED_CAST_PROB),
    "Maokai": ("E", 0, "Magic Damage", "caster_bonus_hp_pct", 5.0, "MAGIC", _ABILITY_CAST_PROB),
    "Nunu": ("Q", 0, "Champion Magic Damage", "caster_bonus_hp_pct", 5.0, "MAGIC", _ABILITY_CAST_PROB),
    "Sejuani": ("W", 0, "Total Physical Damage", "caster_max_hp_pct", 12.0, "PHYSICAL", _ABILITY_CAST_PROB),
    "Shen": ("E", 0, "Physical Damage", "caster_bonus_hp_pct", 11.0, "PHYSICAL", _ABILITY_CAST_PROB),
    "Skarner": ("Q", 0, "Total Bonus Physical Damage", "caster_bonus_hp_pct", 9.0, "PHYSICAL", _ABILITY_CAST_PROB),
    "TahmKench": ("Q", 0, "Magic Damage", "caster_bonus_hp_pct", 4.0, "MAGIC", _ABILITY_CAST_PROB),
    "Zac": ("Q", 0, "Total Magic Damage", "caster_max_hp_pct", 6.0, "MAGIC", _ABILITY_CAST_PROB),
}

# (champion, slot, form_index, block label, field, value) the comments DISCARD.
_DISCARDED = [
    ("DrMundo", "E", 0, "Maximum Bonus Physical Damage", "caster_bonus_hp_pct", [9.8] * 5),
    ("DrMundo", "E", 0, "Bonus Attack Damage", "caster_max_hp_pct", [2.0, 2.2, 2.4, 2.6, 2.8]),
    ("DrMundo", "W", 0, "Magic Damage", "caster_bonus_hp_pct", [7.0] * 5),
    ("KSante", "R", 0, "Strike Physical Damage", "caster_bonus_hp_pct", [5.0] * 3),
    ("Maokai", "E", 0, "Total Enhanced Damage", "caster_bonus_hp_pct", [10.0] * 5),
    ("Maokai", "E", 0, "Enhanced Damage Per Tick", "caster_bonus_hp_pct", [3.33] * 5),
    ("Sejuani", "W", 0, "Physical Damage", "caster_max_hp_pct", [4.0] * 5),
    ("Skarner", "Q", 0, "Bonus Physical Damage per Hit", "caster_bonus_hp_pct", [3.0] * 5),
    ("Skarner", "Q", 1, "Physical Damage", "caster_bonus_hp_pct", [3.0] * 5),
    ("Skarner", "E", 0, "Physical Damage", "caster_max_hp_pct", [6.0] * 5),
    ("Zac", "Q", 0, "Magic Damage", "caster_max_hp_pct", [3.0] * 5),
]

# (champion, slot, the quoted range text, first-rank cd, last-rank cd)
_COOLDOWNS = [
    ("Braum", "Q", "8.0-6.0s cooldown", 8.0, 6.0),
    ("Chogath", "R", "80/70/60s ultimate", 80.0, 60.0),
    ("DrMundo", "E", "9.0-6.0s", 9.0, 6.0),
    ("DrMundo", "W", "17.0-15.0s cooldown", 17.0, 15.0),
    ("KSante", "R", "120/100/80s ult", 120.0, 80.0),
    ("Nunu", "Q", "12.0-8.0s cooldown", 12.0, 8.0),
    ("Shen", "E", "18.0-10.0s cooldown", 18.0, 10.0),
    ("Skarner", "E", "22.0-18.0s cooldown", 22.0, 18.0),
    ("TahmKench", "Q", "7.0-5.0s cooldown", 7.0, 5.0),
]

# (champion, slot, form_index, phrases that must all be in the live effects text)
_QUOTES = [
    ("DrMundo", "E", 0, ["increased by 0% : 40%", "based on Dr. Mundo's missing health"]),
    ("Maokai", "E", 0, ["A Sapling placed in brush", "deals double damage", "over 3 bursts"]),
    ("Skarner", "Q", 0, ["up to three"]),
    ("Skarner", "Q", 1, ["Skarner ends Shattered Earth by throwing his boulder", "applying the same damage"]),
    ("Zac", "Q", 0, ["Zac's next basic attack is replaced by a second Stretching Strike"]),
]


def _patch_dir() -> Path:
    return _DATA / (_DATA / "current.txt").read_text(encoding="utf-8").strip()


@cache
def _snapshot(name: str) -> Any:
    raw = json.loads((_patch_dir() / name).read_text(encoding="utf-8"))
    return raw.get("data", raw) if isinstance(raw, dict) else raw


def _form(champion: str, slot: str, fi: int = 0) -> dict[str, Any]:
    return _snapshot("champion_abilities.json")[champion][slot][fi]


def _block(champion: str, slot: str, fi: int, label: str, field: str) -> dict[str, Any]:
    hits = [
        b for b in _form(champion, slot, fi).get("damage_blocks") or [] if b.get("attribute") == label and field in b
    ]
    assert len(hits) >= 1, (champion, slot, fi, label, field)
    return hits[0]


def _tags(champion: str) -> list[str]:
    return list(_snapshot("champions.json")[champion]["tags"])


def _caster_hp_champions() -> set[str]:
    out = set()
    for champ, kit in _snapshot("champion_abilities.json").items():
        for forms in kit.values():
            for form in forms:
                for block in form.get("damage_blocks") or []:
                    if any(f in block for f in _HP_FIELDS):
                        out.add(champ)
    return out


def test_census_is_the_fourteen_and_seeded_is_census_minus_rejects():
    assert _caster_hp_champions() == _CENSUS
    assert set(_CHAMPION_HEALTH_DAMAGE_COUPLING) == _CENSUS - set(_REJECTS)
    assert "exactly FOURTEEN champions" in _DOC and "ELEVEN tank-primary" in _DOC


def test_seeded_champions_are_tank_primary():
    assert {c: _tags(c)[0] for c in _CHAMPION_HEALTH_DAMAGE_COUPLING} == dict.fromkeys(
        _CHAMPION_HEALTH_DAMAGE_COUPLING, "Tank"
    )


@pytest.mark.parametrize("champion", sorted(_REJECTS))
def test_reject_tags_quoted_in_docstring_are_live(champion):
    assert _tags(champion) == _REJECTS[champion]
    assert f"tags ``{json.dumps(_REJECTS[champion])}``" in _DOC


@pytest.mark.parametrize("champion", sorted(_ROWS))
def test_seeded_row_matches_live_taken_block(champion):
    slot, fi, label, field, value, word, prob = _ROWS[champion]
    entry = _CHAMPION_HEALTH_DAMAGE_COUPLING[champion]
    form = _form(champion, slot, fi)
    assert form["name"] == entry.attribute
    assert set(_block(champion, slot, fi, label, field)[field]) == {value}
    taken = entry.max_hp_pct if field == "caster_max_hp_pct" else entry.bonus_hp_pct
    other = entry.bonus_hp_pct if field == "caster_max_hp_pct" else entry.max_hp_pct
    assert (taken, other) == (value, 0.0)
    assert entry.pct_base == _POOL[field]
    assert form["damage_type"] in (word, None) and word.title() in label
    assert f"{word} damage" in entry.note
    assert entry.note.startswith(f"{slot}: ")
    assert entry.conditional_probability == prob


@pytest.mark.parametrize(("champion", "slot", "fi", "label", "field", "values"), _DISCARDED)
def test_discarded_blocks_still_exist_at_the_quoted_value(champion, slot, fi, label, field, values):
    assert _block(champion, slot, fi, label, field)[field] == values


def test_sub_component_sums_stated_in_the_comments_hold():
    sej = [b["caster_max_hp_pct"][0] for b in _form("Sejuani", "W")["damage_blocks"]]
    assert sej[0] + sej[1] == sej[2] == 12.0
    sk = _block("Skarner", "Q", 0, "Bonus Physical Damage per Hit", "caster_bonus_hp_pct")["caster_bonus_hp_pct"][0]
    assert 3 * sk == 9.0
    zac = _block("Zac", "Q", 0, "Magic Damage", "caster_max_hp_pct")["caster_max_hp_pct"][0]
    assert 2 * zac == 6.0
    strike = _block("KSante", "R", 0, "Strike Physical Damage", "caster_bonus_hp_pct")["caster_bonus_hp_pct"]
    total = _block("KSante", "R", 0, "Total Physical Damage", "caster_bonus_hp_pct")["caster_bonus_hp_pct"]
    assert strike == total


@pytest.mark.parametrize(("champion", "slot", "quoted", "first", "last"), _COOLDOWNS)
def test_quoted_cooldown_ranges_are_live(champion, slot, quoted, first, last):
    cd = _form(champion, slot)["cooldown"]
    assert (cd[0], cd[-1]) == (first, last)
    assert quoted in _SOURCE_FLAT


@pytest.mark.parametrize(("champion", "slot", "fi", "phrases"), _QUOTES)
def test_quoted_ability_text_is_live(champion, slot, fi, phrases):
    text = " ".join(" ".join(_form(champion, slot, fi).get("effects_descriptions") or []).split())
    for phrase in phrases:
        assert phrase in text, phrase


def _hp_keys(champion: str) -> list[tuple[str, str, str]]:
    return [
        (slot, block.get("attribute"), key)
        for slot, forms in _snapshot("champion_abilities.json")[champion].items()
        for form in forms
        for block in form.get("damage_blocks") or []
        for key in block
        if "hp_pct" in key
    ]


def test_negative_controls_carry_no_caster_health_block():
    for champion in ("Sett", "Sion", "Poppy", "Leona"):
        assert not [k for k in _hp_keys(champion) if k[2].startswith("caster_")], champion
    assert _hp_keys("Leona") == []
    assert _block("Sett", "Q", 0, "Bonus Physical Damage", "target_max_hp_pct")["target_max_hp_pct"] == [1.0] * 5
    assert _block("Sett", "Q", 0, "Total Bonus Physical Damage", "target_max_hp_pct")["target_max_hp_pct"] == [2.0] * 5
    assert _block("Sett", "R", 0, "Physical Damage", "target_bonus_hp_pct")["target_bonus_hp_pct"] == [40.0, 50.0, 60.0]
    assert _block("Sett", "R", 0, "Reduced Damage", "target_bonus_hp_pct")["target_bonus_hp_pct"] == [10.0, 12.5, 15.0]
    assert _block("Sion", "W", 0, "Magic Damage", "target_max_hp_pct")["target_max_hp_pct"] == [14.0] * 5
    assert _block("Poppy", "Q", 0, "Physical Damage", "target_max_hp_pct")["target_max_hp_pct"] == [9.0] * 5
    assert _block("Poppy", "Q", 0, "Total Physical Damage", "target_max_hp_pct")["target_max_hp_pct"] == [18.0] * 5
