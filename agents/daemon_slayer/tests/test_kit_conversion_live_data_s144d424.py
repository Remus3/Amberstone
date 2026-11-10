"""S144-D-424..427 - the RM-86 kit-conversion registry (``kit_conversion.py``) checked
against the shipped data it cites: the Meraki ability snapshot
``data/daemon_slayer/<current.txt>/champion_abilities.json`` and the DDragon item
snapshot ``data/daemon_slayer/<current.txt>/items.json``.

Every number in ``_KIT_CONVERSION`` is justified by its ``note`` and by the comments
around it, so a note that misreports the data it quotes leaves a seed with no valid
evidence. These guards only read notes, comments and data; they never change a
conversion fraction (that would be a Tier-2 DS batch, not a lane edit).

S144-D-424. The Quinn over-fire comment quotes Edge of Night's health. The number it
states is the snapshot's ``FlatHPPoolMod``, and that health still clears the
off-axis threshold (the over-fire it describes is real).

S144-D-425. The Naafiri note says a regex finds nothing in her kit while it matches
a named list of other seeded champions. Over ``effects_descriptions`` (the field the
note's own quotes come from) the regex finds nothing for her, and the names the note
lists are exactly the seeded champions it matches.

S144-D-426. The Naafiri and Orianna notes describe which ratio keys their blocks
carry. Each note carries the pinned phrase, and the phrase is true: every block that
carries a ratio carries only the named keys.

S144-D-427. Each quote listed in ``_NOTE_QUOTES`` is in its note verbatim and its
parts (split on "...") occur in order in the listed ``effects_descriptions`` entry;
each per-rank figure the notes quote equals the snapshot's; each component price the
``_GOLD_PER`` comment cites equals the item snapshot's.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Mapping

import pytest

from agents.daemon_slayer import kit_conversion as kc

_DS_DATA = Path(__file__).resolve().parents[3] / "data" / "daemon_slayer"
_SOURCE = Path(kc.__file__).read_text(encoding="utf-8")
# Comment text with each line break plus its leading "#" folded to one space, so a
# cite that wraps across two comment lines still matches.
_COMMENTS = re.sub(r"\s+", " ", re.sub(r"\n\s*#", " ", _SOURCE))


def _patch() -> str:
    return (_DS_DATA / "current.txt").read_text(encoding="utf-8").strip()


def _abilities() -> Mapping[str, Any]:
    path = _DS_DATA / _patch() / "champion_abilities.json"
    return json.loads(path.read_text(encoding="utf-8"))["data"]


def _items() -> Mapping[str, Any]:
    raw = json.loads((_DS_DATA / _patch() / "items.json").read_text(encoding="utf-8"))
    return raw.get("data", raw)


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _form(data: Mapping[str, Any], champ: str, slot: str, form_index: int = 0):
    forms = [f for f in data[champ][slot] if f.get("form_index") == form_index]
    assert len(forms) == 1, (champ, slot, form_index)
    return forms[0]


def _descriptions(data: Mapping[str, Any], champ: str) -> list[str]:
    return [
        e for slot in "PQWER" for form in data[champ].get(slot) or [] for e in form.get("effects_descriptions") or []
    ]


def _ratio_keys(data: Mapping[str, Any], champ: str) -> list[frozenset[str]]:
    """The non-zero ``*_pct`` keys of every block that carries at least one."""
    out = []
    for slot in "PQWER":
        for form in data[champ].get(slot) or []:
            for block in form.get("damage_blocks") or []:
                keys = frozenset(k for k, v in block.items() if k.endswith("_pct") and v)
                if keys:
                    out.append(keys)
    return out


# --- S144-D-424: the Edge of Night health the Quinn comment states -----------

_EON_CITE = re.compile(r"Edge of Night \(3814, (\d+) HP\)")


def test_edge_of_night_health_cite_matches_the_item_snapshot():
    cites = _EON_CITE.findall(_COMMENTS)
    assert len(cites) == 1, cites
    hp = _items()["3814"]["stats"]["FlatHPPoolMod"]
    assert int(cites[0]) == hp


def test_edge_of_night_still_clears_the_off_axis_threshold():
    rec = _items()["3814"]
    assert kc.item_exposures("3814", rec, "ad")["off_axis_stat"] == 1.0
    gold = kc._GOLD_PER["FlatHPPoolMod"] * rec["stats"]["FlatHPPoolMod"]
    assert gold >= kc._OFF_AXIS_MIN_GOLD


# --- S144-D-425: the Naafiri regex claim --------------------------------------

_KIT_RX = re.compile(r"attack speed|on-hit|critical|per second|per tick", re.I)
_LIST_RX = re.compile(r"the same regex matches (.+?) and (\w+)\.")


def _named_matches() -> set[str]:
    m = _LIST_RX.search(_norm(kc._KIT_CONVERSION["Naafiri"].note))
    assert m, "the Naafiri note no longer names the champions the regex matches"
    return {n.strip() for n in m.group(1).split(",")} | {m.group(2)}


def test_naafiri_descriptions_carry_no_regex_match():
    data = _abilities()
    assert not _KIT_RX.findall(" ".join(_descriptions(data, "Naafiri")))


def test_naafiri_note_names_exactly_the_seeded_champions_the_regex_matches():
    data = _abilities()
    measured = {cid for cid in kc.registry_champion_ids() if _KIT_RX.search(" ".join(_descriptions(data, cid)))}
    assert _named_matches() == measured


def test_the_naafiri_list_check_catches_a_planted_name():
    note = kc._KIT_CONVERSION["Naafiri"].note
    planted = note.replace("Orianna, ", "Orianna, Poppy, ")
    assert planted != note
    m = _LIST_RX.search(_norm(planted))
    assert m and "Poppy" in m.group(1)


# --- S144-D-426: the ratio-key claims ------------------------------------------

_RATIO_CLAIMS = {
    "Naafiri": ("Every block of hers that carries a ratio scales bonus_ad_pct only", {"bonus_ad_pct"}),
    "Orianna": ("every block of hers that carries a ratio carries ap_pct only", {"ap_pct"}),
}


@pytest.mark.parametrize("champ", sorted(_RATIO_CLAIMS))
def test_ratio_key_claim_is_in_the_note_and_true(champ):
    phrase, allowed = _RATIO_CLAIMS[champ]
    assert phrase in _norm(kc._KIT_CONVERSION[champ].note)
    blocks = _ratio_keys(_abilities(), champ)
    assert blocks
    assert all(keys <= allowed for keys in blocks), blocks


def test_orianna_has_no_health_or_resist_ratio():
    banned = {"caster_max_hp_pct", "caster_bonus_hp_pct", "bonus_armor_pct", "bonus_mr_pct"}
    for keys in _ratio_keys(_abilities(), "Orianna"):
        assert not keys & banned


def test_poppy_ratio_keys_are_the_ones_her_note_lists():
    union = set().union(*_ratio_keys(_abilities(), "Poppy"))
    assert union == {"bonus_ad_pct", "ap_pct", "target_max_hp_pct"}


# --- S144-D-427: quotes, per-rank figures, component prices -------------------

# (champion, slot, form_index, effects_descriptions index, quote)
_NOTE_QUOTES = (
    ("Naafiri", "W", 0, 2, "Naafiri gains 20% AD bonus attack damage"),
    (
        "Olaf",
        "P",
        0,
        0,
        "Olaf gains bonus attack speed and life steal based on his missing health, up to 50% : 100% (based on level) bonus attack speed",
    ),
    (
        "Pantheon",
        "P",
        0,
        0,
        "Pantheon generates a stack of Mortal Will whenever he lands a basic attack on-hit or casts an ability, stacking up to 5 times. At 5 stacks, Pantheon's next basic ability consumes the stacks to become empowered",
    ),
    ("Pantheon", "W", 0, 1, "Each hit is affected by critical strike modifiers and applies on-hit effects."),
    (
        "Orianna",
        "P",
        0,
        1,
        "Orianna's basic attacks are empowered to deal 10 : 50 (based on level) (+ 15% AP) bonus magic damage on-hit",
    ),
    ("Poppy", "P", 0, 0, "Periodically, Poppy's next basic attack is empowered to throw her buckler"),
    (
        "Quinn",
        "P",
        0,
        1,
        "Quinn's basic attacks against Vulnerable targets are empowered to consume the mark to deal 10 : 95 (based on level) (+ 16% : 50% (based on level) AD) bonus physical damage",
    ),
    (
        "RekSai",
        "Q",
        0,
        0,
        "Rek'Sai gains 35% bonus attack speed for 3 seconds. Her next basic attack within the duration will have an uncancellable windup and deal bonus physical damage... Queen's Wrath's damage to the primary target is affected by critical strike modifiers.",
    ),
    ("Rengar", "Q", 0, 0, "his next two basic attacks within 3 seconds to gain 40% bonus attack speed"),
    ("Rengar", "Q", 0, 1, "50% : 101% (based on level) bonus attack speed for 5 seconds"),
    ("Rengar", "Q", 0, 0, "critically strike for ((31.25% + 30%) critical strike chance + 40%) AD"),
    (
        "Riven",
        "P",
        0,
        0,
        "Riven's ability casts generate a stack of Charge... stacking up to 3 times. Riven's basic attacks are empowered to each consume a stack to deal bonus physical damage equal to 30% : 50% (based on level) AD",
    ),
    (
        "Riven",
        "P",
        0,
        1,
        "The bonus damage is affected by critical strike modifiers and applies life steal at 100% effectiveness.",
    ),
)


@pytest.mark.parametrize("champ,slot,form_index,index,quote", _NOTE_QUOTES)
def test_note_quote_is_verbatim_in_the_listed_entry(champ, slot, form_index, index, quote):
    assert quote in _norm(kc._KIT_CONVERSION[champ].note)
    entry = _norm(_form(_abilities(), champ, slot, form_index)["effects_descriptions"][index])
    pos = 0
    for part in (_norm(p) for p in quote.split("...")):
        found = entry.find(part, pos)
        assert found >= 0, (part, entry)
        pos = found + len(part)


def _block_values(form: Mapping[str, Any], attribute: str) -> list[float]:
    blocks = [b for b in form["damage_blocks"] if b.get("attribute") == attribute]
    assert len(blocks) == 1, attribute
    return [float(v) for v in blocks[0]["raw_modifiers"][0]["values"]]


def test_per_rank_figures_the_notes_quote():
    data = _abilities()
    olaf_w = _form(data, "Olaf", "W")
    assert _block_values(olaf_w, "Bonus Attack Speed") == [40, 50, 60, 70, 80]
    assert olaf_w["cooldown"] == [16, 15, 14, 13, 12]
    assert _form(data, "RekSai", "Q")["cooldown"] == [4, 3.5, 3, 2.5, 2]
    assert _form(data, "Rengar", "Q")["cooldown"] == [6, 5.5, 5, 4.5, 4]
    quinn_p = _form(data, "Quinn", "P")
    assert quinn_p["cooldown"] == [8, 8, 8]
    assert quinn_p["damage_blocks"] == []
    assert quinn_p["parse_status"] == "no_damage"
    assert _block_values(_form(data, "Quinn", "W"), "Bonus Attack Speed") == [28, 41, 54, 67, 80]


def test_naafiri_block_ratios_the_note_quotes():
    data = _abilities()
    q = _form(data, "Naafiri", "Q")
    assert q["damage_blocks"][0]["bonus_ad_pct"][0] == 20
    assert max(b.get("bonus_ad_pct", [0])[0] for b in q["damage_blocks"] if b.get("bonus_ad_pct")) == 240
    e = [b["bonus_ad_pct"][0] for b in _form(data, "Naafiri", "E")["damage_blocks"]]
    assert (min(e), max(e)) == (40, 120)
    r = _form(data, "Naafiri", "R")["damage_blocks"]
    assert r[0]["attribute"] == "Physical Damage" and r[0]["bonus_ad_pct"][0] == 120


# (item id, name, gold, stat key, stat value) as the ``_GOLD_PER`` comment cites them
_COMPONENTS = (
    ("1052", "Amplifying Tome", 400, "FlatMagicDamageMod", 20),
    ("1036", "Long Sword", 350, "FlatPhysicalDamageMod", 10),
    ("1028", "Ruby Crystal", 400, "FlatHPPoolMod", 150),
    ("1027", "Sapphire Crystal", 300, "FlatMPPoolMod", 300),
    ("1029", "Cloth Armor", 300, "FlatArmorMod", 15),
    ("1033", "Null-Magic Mantle", 400, "FlatSpellBlockMod", 20),
    ("1042", "Dagger", 250, "PercentAttackSpeedMod", 0.10),
    ("1018", "Cloak of Agility", 600, "FlatCritChanceMod", 0.15),
)


@pytest.mark.parametrize("item_id,name,gold,key,value", _COMPONENTS)
def test_gold_per_comment_component_matches_the_item_snapshot(item_id, name, gold, key, value):
    rec = _items()[item_id]
    assert rec["name"] == name
    assert rec["gold"]["total"] == gold
    assert rec["stats"] == {key: value}
    assert re.search(rf"{re.escape(name)} {gold}g/", _COMMENTS), name


def test_gold_per_table_is_the_component_price_per_unit():
    by_key = {key: gold / value for _, _, gold, key, value in _COMPONENTS}
    for key, per in kc._GOLD_PER.items():
        assert per == pytest.approx(by_key[key]), key
    assert kc._GOLD_PER_AS == pytest.approx(by_key["PercentAttackSpeedMod"])
    assert kc._GOLD_PER_CRIT == pytest.approx(by_key["FlatCritChanceMod"])
