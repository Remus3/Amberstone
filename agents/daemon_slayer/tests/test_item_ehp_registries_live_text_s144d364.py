"""S144-D-364..367 - the DS item-side EHP registries match the live text they cite.

WHY. The four item-keyed EHP registries (R104 spell shield, R105 mana to
health, R107 bonus-HP amp, R108 general %DR) each document their mechanic,
their registered ids, their dropped mirrors and their exclusions from the
item text of the patch they were written at. Their fail-soft and mirror guards
pin the VALUES; nothing pinned the prose to the live snapshot, and each module
had drifted.

* S144-D-364 ``_item_spell_shield_overrides``: the registry is exactly the live
  Annul set and its dropped mirrors stay absent. The docstring said Banshee's
  Veil "regenerates its shield after leaving combat" and gave every carrier a
  ~40s cooldown; Meraki gives all three base carriers the same "timer restarts
  upon taking damage from champions" clause, and Verdant Barrier a 60 second
  cooldown, not 40 (the Arena 223102 DDragon text carries the restart clause
  too).
* S144-D-365 ``_item_mana_health``: the docstring said the Meraki passives scan
  for 'health' + 'mana' co-occurrence "returned exactly this family". The scan
  returns nine passives; four of them (Guardian's Amulet 2049, Guardian Angel
  3026, Guardian's Orb 3112, The Golden Spatula 224403) were named nowhere.
  Its R144 note also quoted "equal to Total Mana" for both Arena mirrors; only
  223119 reads that, 223121 reads "based on Mana".
* S144-D-366 ``_item_bonus_hp_amp``: RM-102 removed the Arena mirror 443083
  from the registry, but the module docstring still listed it under
  "Registered ids" and both docstrings still reasoned about "the base and its
  Arena mirror". Only 3083 carries Warmog's Vitality live.
* S144-D-367 ``_item_general_dr``: Celestial Opposition 3869 was labelled
  ``maps.11`` / "SR" while it is live on maps 11 and 453; the Cloak of Starry
  Night exclusion gave both ids the Arena numbers (+20% MR, cap 50%) while the
  SR copy 663059 reads +10% MR, cap 25%.

MEASURED 2026-11-09 (``data/daemon_slayer/current.txt`` = 16.22.1). Docstring
and comment fixes only; no registry value changes, so the scorer output is
byte-identical.
"""

from __future__ import annotations

import inspect
import json
import re
from functools import cache
from pathlib import Path
from typing import Any

import pytest

from agents.daemon_slayer import _item_bonus_hp_amp as amp_mod
from agents.daemon_slayer import _item_general_dr as dr_mod
from agents.daemon_slayer import _item_mana_health as awe_mod
from agents.daemon_slayer import _item_spell_shield_overrides as annul_mod

_REPO_ROOT = Path(__file__).resolve().parents[3]
_DATA = _REPO_ROOT / "data" / "daemon_slayer"


def _patch_dir() -> Path:
    return _DATA / (_DATA / "current.txt").read_text(encoding="utf-8").strip()


@cache
def _items() -> dict[str, Any]:
    raw = json.loads((_patch_dir() / "items.json").read_text(encoding="utf-8"))
    return raw["data"]


@cache
def _meraki() -> dict[str, Any]:
    raw = json.loads(
        (_patch_dir() / "items_meraki.json").read_text(encoding="utf-8")
    )
    return raw["items"]


def _plain(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", text or "")).strip()


def _desc(iid: str) -> str:
    return _plain(_items()[iid].get("description", ""))


def _maps(iid: str) -> list[str]:
    return sorted(
        (m for m, on in _items()[iid].get("maps", {}).items() if on), key=int
    )


def _flat(text: str) -> str:
    return " ".join(text.split())


def _section(doc: str, start: str, end: str) -> str:
    head, sep, rest = doc.partition(start)
    assert sep, f"docstring lost its {start!r} heading"
    body, sep, _ = rest.partition(end)
    assert sep, f"docstring lost its {end!r} heading"
    return body


def _meraki_passive(iid: str, name: str) -> str:
    for passive in _meraki()[iid].get("passives", []):
        if passive.get("name") == name:
            return passive.get("effects") or ""
    raise AssertionError(f"Meraki {iid} carries no {name!r} passive")


# --------------------------------------------------------------------------
# S144-D-364 - _item_spell_shield_overrides
# --------------------------------------------------------------------------

_ANNUL_DOC = annul_mod.__doc__ or ""
_ANNUL_SRC = inspect.getsource(annul_mod)
_ANNUL_RE = re.compile(r"\bSpell Shield that blocks the next enemy Ability\b")
_ANNUL_BASES = ("3102", "3814", "4632")
_ANNUL_DROPPED = ("323102", "323814", "224632", "324632")
_ANNUL_EXCLUDED = {
    "3140": "Remove all crowd control",
    "3139": "Removes all crowd control",
    "223139": "Remove all crowd control",
    "6035": "Remove all crowd control",
    "226035": "Remove all crowd control",
    "3222": "Remove all crowd control",
    "2051": "Blocks 15 damage from attacks and spells",
    "3156": "would reduce your Health below 30%",
    "3155": "would reduce your Health below 30%",
}


def test_d364_registry_is_exactly_the_live_annul_set() -> None:
    live = {iid for iid in _items() if _ANNUL_RE.search(_desc(iid))}
    assert live == set(annul_mod._ITEM_SPELL_SHIELD)
    for iid in live:
        assert "Annul" in _desc(iid), iid


def test_d364_dropped_mirrors_stay_absent_and_documented() -> None:
    for iid in _ANNUL_DROPPED:
        assert iid not in _items(), iid
        assert iid in _ANNUL_DOC, iid


@pytest.mark.parametrize("iid", sorted(_ANNUL_EXCLUDED))
def test_d364_exclusions_carry_their_live_phrase(iid: str) -> None:
    assert _ANNUL_EXCLUDED[iid] in _desc(iid)
    assert iid in _ANNUL_DOC


def test_d364_cooldown_prose_matches_meraki() -> None:
    cooldowns: dict[str, int] = {}
    for iid in _ANNUL_BASES:
        text = _meraki_passive(iid, "Annul")
        match = re.search(r"\((\d+) second cooldown, timer restarts upon taking "
                          r"damage from champions\)", text)
        assert match, (iid, text)
        cooldowns[iid] = int(match.group(1))
    assert cooldowns == {"3102": 40, "3814": 40, "4632": 60}
    mechanic = _flat(_section(_ANNUL_DOC, "Mechanic:", "Why a NEW registry"))
    # Every carrier restarts its timer on champion damage; none regenerates
    # on leaving combat.
    assert "leaving combat" not in mechanic
    assert "60s" in mechanic and "Verdant Barrier" in mechanic
    assert "~40s cooldown" not in _flat(_ANNUL_SRC)
    # The Arena Banshee's text states the champion-damage restart in DDragon
    # too; the Arena Edge of Night drops "from champions", and the docstring
    # quotes it apart rather than calling it the same restart.
    assert "restarted if you take damage from champions" in _desc("223102")
    assert "restarted if you take damage before" in _desc("223814")
    assert "223102 / 223814 rows state the same restart" not in mechanic
    assert '223814 says only "restarted if you take damage"' in mechanic


# --------------------------------------------------------------------------
# S144-D-365 - _item_mana_health
# --------------------------------------------------------------------------

_AWE_DOC = awe_mod.__doc__ or ""
_AWE_FAMILY = ("Winter's Approach", "Fimbulwinter")


def _meraki_health_mana_scan() -> set[str]:
    hits = set()
    for iid, row in _meraki().items():
        for passive in row.get("passives", []):
            text = passive.get("effects") or ""
            if re.search(r"health", text, re.I) and re.search(r"mana", text, re.I):
                hits.add(iid)
    return hits


def test_d365_registry_is_every_live_awe_family_id() -> None:
    family = {iid for iid, row in _items().items() if row.get("name") in _AWE_FAMILY}
    assert family == set(awe_mod._ITEM_MANA_HEALTH_PCT)
    for iid in family:
        assert "Awe" in _desc(iid), iid


def test_d365_meraki_awe_text_is_the_quoted_mechanic() -> None:
    for iid in ("3119", "3121"):
        text = re.sub(r"\{\{as\||\}\}|'''", "", _meraki_passive(iid, "Awe"))
        assert text == "Grants bonus health equal to 15% bonus mana.", (iid, text)
    assert '"Awe - Grants bonus health equal to 15% bonus mana."' in _flat(_AWE_DOC)


def test_d365_docstring_names_every_id_the_documented_scan_returns() -> None:
    scan = _meraki_health_mana_scan()
    assert scan == {
        "2049", "2530", "3026", "3040", "3112", "3119", "3121", "6657", "224403",
    }
    doc = _flat(_AWE_DOC)
    missing = sorted(iid for iid in scan if not re.search(rf"\b{iid}\b", doc))
    assert not missing, f"scan ids named nowhere in the docstring: {missing}"
    assert "returned exactly this family" not in doc
    assert f"returns {len(scan)} passives" in doc


def test_d365_arena_mirror_wording_is_each_mirrors_own() -> None:
    doc = _flat(_AWE_DOC)
    for iid, phrase in (("223119", "equal to Total Mana"), ("223121", "based on Mana")):
        assert phrase in _desc(iid), iid
        assert re.search(rf"{iid}[^.]*{re.escape(phrase)}", doc), iid


# --------------------------------------------------------------------------
# S144-D-366 - _item_bonus_hp_amp
# --------------------------------------------------------------------------

_AMP_DOC = amp_mod.__doc__ or ""
_AMP_FN_DOC = amp_mod.item_bonus_hp_amp_hp.__doc__ or ""


def test_d366_registry_is_exactly_the_live_vitality_set() -> None:
    live = {iid for iid in _items() if "Warmog's Vitality" in _desc(iid)}
    assert live == set(amp_mod._ITEM_BONUS_HP_AMP_PCT) == {"3083"}
    assert "Warmog's Vitality" not in _desc("443083")
    # The docstring's account of what 443083 does carry matches its own text.
    stats = re.match(r"(\d+) Health (\d+)% Move Speed Warmog's Heart", _desc("443083"))
    assert stats, _desc("443083")
    assert (
        f"carries a {stats.group(1)} Health stat, {stats.group(2)}% move speed and "
        "Warmog's Heart regen"
    ) in _flat(_AMP_DOC)


def test_d366_registered_ids_section_lists_exactly_the_registry() -> None:
    body = _section(_AMP_DOC, "Registered ids", "DOCUMENTED EXCLUSIONS")
    bullets = set(re.findall(r"^\s*\*\s+(\d{4,6})\b", body, re.M))
    assert bullets == set(amp_mod._ITEM_BONUS_HP_AMP_PCT)


def test_d366_no_docstring_reasons_about_a_registered_mirror() -> None:
    for doc in (_AMP_DOC, _AMP_FN_DOC):
        flat = _flat(doc)
        assert "base and its Arena mirror are" not in flat
        assert "the base and the mirror are mutually exclusive" not in flat
        assert "base plus its Arena mirror" not in flat
        assert "a base and its mirror" not in flat


def test_d366_heart_exclusion_threshold_matches_live() -> None:
    assert "If you have 2000 bonus Health" in _desc("3083")
    assert "gated at 2000 bonus health" in _flat(_AMP_DOC)


# --------------------------------------------------------------------------
# S144-D-367 - _item_general_dr
# --------------------------------------------------------------------------

_DR_DOC = dr_mod.__doc__ or ""
_DR_SRC = inspect.getsource(dr_mod)
_DR_ROW_RE = re.compile(r'^\s*"(\d{4,6})"\s*:\s*\([^)]*\),\s*#\s*(.+?)\s*$', re.M)


def test_d367_row_comments_name_the_live_map_flags() -> None:
    rows = dict(_DR_ROW_RE.findall(_DR_SRC))
    assert set(rows) == set(dr_mod._ITEM_GENERAL_DR)
    for iid, comment in rows.items():
        expected = "maps " + "/".join(_maps(iid))
        assert re.search(rf"{re.escape(expected)}(?![\d/])", comment), (
            iid, comment, expected,
        )


def test_d367_registered_bullets_name_the_live_map_flags() -> None:
    body = _flat(_section(_DR_DOC, "Registered ids", "DOCUMENTED EXCLUSIONS"))
    for iid in dr_mod._ITEM_GENERAL_DR:
        expected = "maps " + "/".join(_maps(iid))
        assert re.search(
            rf"\b{iid}\b[^*]*{re.escape(expected)}(?![\d/])", body
        ), (iid, expected)


@pytest.mark.parametrize("iid", ["443059", "663059"])
def test_d367_starry_night_exclusion_quotes_each_ids_own_numbers(iid: str) -> None:
    text = _desc(iid)
    mr = re.search(r"Increase your Magic Resist by (\d+)%", text)
    cap = re.search(r"up to a cap of (\d+)%", text)
    assert mr and cap, text
    expected = f"{iid} (+{mr.group(1)}% MR, cap {cap.group(1)}%)"
    assert expected in _flat(_DR_DOC), expected
