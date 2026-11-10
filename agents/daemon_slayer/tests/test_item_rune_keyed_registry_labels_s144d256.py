"""S144-D-256..259 - the item- and rune-keyed DS registries name what the live
DDragon feed names.

WHY. ``test_passive_form_keyed_registries_s144d252.py`` (S144-D-255) checks
that every (champion, key, form)-keyed passive row carries a label its live
ability uses; it found two stale heal labels. The registries keyed on an
ITEM id or a RUNE id carry labels too, and nothing checked them against the
feed: a reader-facing name was pinned only by a few hand-typed literals
(``_RUNE_OFFENSE_GRANTS["8010"].name == "Conqueror"`` and two more), so a
renamed rune or item, or a row keyed on the wrong id, kept a label that no
longer matches the id. The labels reach readers: ``dps.py`` and ``burst.py``
print ``_ITEM_REFLECT_NAMES`` in their reflect notes, the flat-mitigation
``attribute`` is the block name, and every ``note`` opens with the name a
maintainer reads to know which row it is.

* S144-D-256: the item-keyed reflect and vulnerability rows. The reflect name
  table covers exactly the reflect registry's ids and gives each one its live
  item name; the shared ``attribute`` ("Thorns") is in every reflect item's
  live description; every reflect and vulnerability ``note`` opens with the
  live item name, and every vulnerability row's ``source_key`` is its own id.
* S144-D-257: every row of the seven rune-keyed registries is a live rune id;
  every rune offense row's ``name`` and ``tree`` are the live rune and tree
  names, and the flat-mitigation ``attribute`` is the live rune name.
* S144-D-258: every rune-keyed row with a ``note`` opens with
  ``"<live rune name>:"``.
* S144-D-259: every id of the item-keyed registries is in the live
  ``item.json``, and every inline ``# <name>`` comment on an item-id row of
  the ``_item_*.py`` registries and the reflect module names that id's live
  item, and the set of files that carry such comments is pinned, so a file
  whose rows stop matching the row pattern fails instead of passing empty
  (the vulnerability module is scanned but has no commented rows). DDragon
  ships some Arena mirror ids with a blank name (226660, Bami's Cinder): a
  blank live name is not checked. ``_ALLY_GRANT_MIRROR_SOURCE`` is not listed
  here: ``test_r144_mirror_slice_a.py`` (beside this file) already re-reads
  it from the catalog.

MEASURED 2026-11-09 (patch 16.22.1, ENGINE 1.291.0): 4 reflect + 5
vulnerability item rows; 14 rune rows over the seven rune registries (8473,
8437, 8451, 8453, 8236, 8233, 8010, 9104, 8316, 8439, 8429, 8242, 8444,
8465); 266 inline-commented item rows over 12 files. ZERO defects - this batch is a guard,
not a fix. Each checker also runs on planted defects, so an empty or blind
checker cannot pass.
"""

from __future__ import annotations

import dataclasses
import json
import re
from pathlib import Path
from typing import Any

import pytest

from agents.daemon_slayer._item_ability_haste import _ITEM_ABILITY_HASTE
from agents.daemon_slayer._item_bonus_hp_amp import _ITEM_BONUS_HP_AMP_PCT
from agents.daemon_slayer._item_general_dr import _ITEM_GENERAL_DR
from agents.daemon_slayer._item_health_stack import _ITEM_HEALTH_STACK_PCT
from agents.daemon_slayer._item_lowhp_magic_crit import _ITEM_LOWHP_MAGIC_CRIT
from agents.daemon_slayer._item_mana_health import _ITEM_MANA_HEALTH_PCT
from agents.daemon_slayer._item_omnivamp import _ITEM_OMNIVAMP
from agents.daemon_slayer._item_proc_heal import _ITEM_PROC_HEAL_BONUS_HP_SCALING
from agents.daemon_slayer._item_resist_grants import _ITEM_RESIST_GRANTS
from agents.daemon_slayer._item_revive import _ITEM_REVIVE
from agents.daemon_slayer._item_spell_shield_overrides import _ITEM_SPELL_SHIELD
from agents.daemon_slayer._item_survival_window import _ITEM_SURVIVAL_WINDOW
from agents.daemon_slayer._item_tenacity import _ITEM_TENACITY
from agents.daemon_slayer._passive_reflect_overrides import (
    _ITEM_REFLECT_NAMES,
    _ITEM_REFLECT_OVERRIDES,
)
from agents.daemon_slayer._rune_flat_mitigation import _RUNE_FLAT_MITIGATION
from agents.daemon_slayer._rune_health_grants import _RUNE_HEALTH_GRANTS
from agents.daemon_slayer._rune_hsp_amp import _RUNE_HSP_PCT
from agents.daemon_slayer._rune_offense_grants import _RUNE_OFFENSE_GRANTS
from agents.daemon_slayer._rune_resist_grants import _RUNE_RESIST_GRANTS
from agents.daemon_slayer._rune_self_heal import _RUNE_SELF_HEAL
from agents.daemon_slayer._rune_shield_grants import _RUNE_SHIELD_GRANTS
from agents.daemon_slayer._target_vulnerability_overrides import (
    _ITEM_VULN_OVERRIDES,
)

_REPO_ROOT = Path(__file__).resolve().parents[3]
_DS_DIR = _REPO_ROOT / "agents" / "daemon_slayer"
_CURRENT_TXT = _REPO_ROOT / "data" / "daemon_slayer" / "current.txt"
_DDRAGON_ROOT = _REPO_ROOT / "data" / "meta_build" / "ddragon"

_RUNE_REGISTRIES: dict[str, dict[str, Any]] = {
    "_RUNE_FLAT_MITIGATION": _RUNE_FLAT_MITIGATION,
    "_RUNE_HEALTH_GRANTS": _RUNE_HEALTH_GRANTS,
    "_RUNE_HSP_PCT": _RUNE_HSP_PCT,
    "_RUNE_OFFENSE_GRANTS": _RUNE_OFFENSE_GRANTS,
    "_RUNE_RESIST_GRANTS": _RUNE_RESIST_GRANTS,
    "_RUNE_SELF_HEAL": _RUNE_SELF_HEAL,
    "_RUNE_SHIELD_GRANTS": _RUNE_SHIELD_GRANTS,
}

_ITEM_REGISTRIES: dict[str, dict[str, Any]] = {
    "_ITEM_ABILITY_HASTE": _ITEM_ABILITY_HASTE,
    "_ITEM_BONUS_HP_AMP_PCT": _ITEM_BONUS_HP_AMP_PCT,
    "_ITEM_GENERAL_DR": _ITEM_GENERAL_DR,
    "_ITEM_HEALTH_STACK_PCT": _ITEM_HEALTH_STACK_PCT,
    "_ITEM_LOWHP_MAGIC_CRIT": _ITEM_LOWHP_MAGIC_CRIT,
    "_ITEM_MANA_HEALTH_PCT": _ITEM_MANA_HEALTH_PCT,
    "_ITEM_OMNIVAMP": _ITEM_OMNIVAMP,
    "_ITEM_PROC_HEAL_BONUS_HP_SCALING": _ITEM_PROC_HEAL_BONUS_HP_SCALING,
    "_ITEM_RESIST_GRANTS": _ITEM_RESIST_GRANTS,
    "_ITEM_REVIVE": _ITEM_REVIVE,
    "_ITEM_SPELL_SHIELD": _ITEM_SPELL_SHIELD,
    "_ITEM_SURVIVAL_WINDOW": _ITEM_SURVIVAL_WINDOW,
    "_ITEM_TENACITY": _ITEM_TENACITY,
    "_ITEM_REFLECT_OVERRIDES": _ITEM_REFLECT_OVERRIDES,
    "_ITEM_REFLECT_NAMES": _ITEM_REFLECT_NAMES,
    "_ITEM_VULN_OVERRIDES": _ITEM_VULN_OVERRIDES,
}

# A dict-literal row keyed by an item id, with a trailing "# <name>" comment.
_COMMENTED_ROW_RE = re.compile(r'^\s*"(\d{4,6})"\s*:\s*[^#\n]*#\s*(.+?)\s*$')


def _comment_files() -> list[Path]:
    files = sorted(_DS_DIR.glob("_item_*.py"))
    files.append(_DS_DIR / "_passive_reflect_overrides.py")
    files.append(_DS_DIR / "_target_vulnerability_overrides.py")
    return files


def _patch_dir() -> Path:
    assert _CURRENT_TXT.exists(), "no data/daemon_slayer/current.txt"
    patch = _CURRENT_TXT.read_text(encoding="utf-8").strip()
    path = _DDRAGON_ROOT / patch
    assert (path / "item.json").exists(), f"no vendored DDragon item.json for {patch}"
    assert (path / "runesReforged.json").exists(), f"no vendored DDragon runesReforged.json for {patch}"
    return path


@pytest.fixture(scope="module")
def live_items() -> dict[str, dict[str, Any]]:
    blob = json.loads((_patch_dir() / "item.json").read_text(encoding="utf-8"))
    return blob["data"]


@pytest.fixture(scope="module")
def live_runes() -> dict[str, tuple[str, str]]:
    """rune id -> (rune name, tree name)."""
    trees = json.loads((_patch_dir() / "runesReforged.json").read_text(encoding="utf-8"))
    out: dict[str, tuple[str, str]] = {}
    for tree in trees:
        for slot in tree["slots"]:
            for rune in slot["runes"]:
                out[str(rune["id"])] = (rune["name"], tree["name"])
    return out


# ---- checkers (pure, so planted defects can exercise them) -------------------


def reflect_label_problems(
    overrides: dict[str, Any],
    names: dict[str, str],
    items: dict[str, dict[str, Any]],
) -> list[str]:
    problems: list[str] = []
    if set(names) != set(overrides):
        problems.append(f"name table ids {sorted(names)} != reflect ids {sorted(overrides)}")
    for iid, entry in overrides.items():
        live = items.get(iid)
        if live is None:
            problems.append(f"{iid}: not a live item")
            continue
        if names.get(iid) != live["name"]:
            problems.append(f"{iid}: name {names.get(iid)!r} != live {live['name']!r}")
        if entry.attribute not in live.get("description", ""):
            problems.append(f"{iid}: attribute {entry.attribute!r} not in live description")
        if not entry.note.startswith(live["name"]):
            problems.append(f"{iid}: note does not open with {live['name']!r}")
    return problems


def vuln_label_problems(overrides: dict[str, Any], items: dict[str, dict[str, Any]]) -> list[str]:
    problems: list[str] = []
    for iid, entry in overrides.items():
        live = items.get(iid)
        if live is None:
            problems.append(f"{iid}: not a live item")
            continue
        if entry.source_key != iid:
            problems.append(f"{iid}: source_key {entry.source_key!r}")
        if not entry.note.startswith(live["name"]):
            problems.append(f"{iid}: note does not open with {live['name']!r}")
    return problems


def rune_label_problems(registries: dict[str, dict[str, Any]], runes: dict[str, tuple[str, str]]) -> list[str]:
    problems: list[str] = []
    for reg_name, reg in registries.items():
        for rid, entry in reg.items():
            live = runes.get(rid)
            if live is None:
                problems.append(f"{reg_name}[{rid}]: not a live rune")
                continue
            live_name, live_tree = live
            for field, want in (("name", live_name), ("tree", live_tree)):
                got = getattr(entry, field, None)
                if got is not None and got != want:
                    problems.append(f"{reg_name}[{rid}]: {field} {got!r} != live {want!r}")
            if reg_name == "_RUNE_FLAT_MITIGATION" and entry.attribute != live_name:
                problems.append(f"{reg_name}[{rid}]: attribute {entry.attribute!r} != live {live_name!r}")
    return problems


def rune_note_problems(registries: dict[str, dict[str, Any]], runes: dict[str, tuple[str, str]]) -> list[str]:
    problems: list[str] = []
    for reg_name, reg in registries.items():
        for rid, entry in reg.items():
            note = getattr(entry, "note", None)
            if note is None or rid not in runes:
                continue
            if not note.startswith(f"{runes[rid][0]}:"):
                problems.append(f"{reg_name}[{rid}]: note {note[:40]!r}")
    return problems


def item_key_problems(registries: dict[str, dict[str, Any]], items: dict[str, dict[str, Any]]) -> list[str]:
    return [
        f"{reg_name}[{iid}]: not a live item" for reg_name, reg in registries.items() for iid in reg if iid not in items
    ]


def comment_rows(text: str) -> list[tuple[int, str, str]]:
    return [
        (lineno, m.group(1), m.group(2))
        for lineno, line in enumerate(text.splitlines(), 1)
        if (m := _COMMENTED_ROW_RE.match(line))
    ]


def comment_problems(rows: list[tuple[str, int, str, str]], items: dict[str, dict[str, Any]]) -> list[str]:
    problems: list[str] = []
    for fname, lineno, iid, comment in rows:
        live = items.get(iid)
        if live is None:
            problems.append(f"{fname}:{lineno} {iid}: not a live item")
            continue
        name = live.get("name", "")
        if name and name.lower() not in comment.lower():
            problems.append(f"{fname}:{lineno} {iid}: comment {comment!r} != live {name!r}")
    return problems


def _all_comment_rows() -> list[tuple[str, int, str, str]]:
    return [
        (path.name, lineno, iid, comment)
        for path in _comment_files()
        for lineno, iid, comment in comment_rows(path.read_text(encoding="utf-8"))
    ]


# ---- S144-D-256: item reflect / vulnerability labels -------------------------


def test_reflect_labels_match_live_items(live_items):
    assert len(_ITEM_REFLECT_OVERRIDES) >= 4
    assert reflect_label_problems(_ITEM_REFLECT_OVERRIDES, _ITEM_REFLECT_NAMES, live_items) == []


def test_vuln_labels_match_live_items(live_items):
    assert len(_ITEM_VULN_OVERRIDES) >= 5
    assert vuln_label_problems(_ITEM_VULN_OVERRIDES, live_items) == []


def test_reflect_checker_catches_planted_defects(live_items):
    entry = _ITEM_REFLECT_OVERRIDES["3075"]
    stale_names = dict(_ITEM_REFLECT_NAMES)
    stale_names["3076"] = "Thornmail"
    del stale_names["323075"]
    found = reflect_label_problems(_ITEM_REFLECT_OVERRIDES, stale_names, live_items)
    assert any("name table ids" in p for p in found)
    assert any(p.startswith("3076: name") for p in found)

    bad_attr = {"3075": dataclasses.replace(entry, attribute="Spikes")}
    found = reflect_label_problems(bad_attr, {"3075": "Thornmail"}, live_items)
    assert found == ["3075: attribute 'Spikes' not in live description"]

    bad_note = {"3076": dataclasses.replace(entry, note="Thornmail Thorns")}
    found = reflect_label_problems(bad_note, {"3076": "Bramble Vest"}, live_items)
    assert found == ["3076: note does not open with 'Bramble Vest'"]

    found = reflect_label_problems({"999999": entry}, {"999999": "x"}, live_items)
    assert found == ["999999: not a live item"]


def test_vuln_checker_catches_planted_defects(live_items):
    entry = _ITEM_VULN_OVERRIDES["4005"]
    moved = {"3001": entry}
    found = vuln_label_problems(moved, live_items)
    assert "3001: source_key '4005'" in found
    assert "3001: note does not open with 'Evenshroud'" in found
    assert vuln_label_problems({"999999": entry}, live_items) == ["999999: not a live item"]


# ---- S144-D-257: rune ids, names, trees, attribute ---------------------------


def test_rune_rows_are_live_and_named_as_live(live_runes):
    assert sum(len(reg) for reg in _RUNE_REGISTRIES.values()) >= 14
    assert rune_label_problems(_RUNE_REGISTRIES, live_runes) == []


def test_rune_label_checker_catches_planted_defects(live_runes):
    conq = _RUNE_OFFENSE_GRANTS["8010"]
    found = rune_label_problems({"_RUNE_OFFENSE_GRANTS": {"8233": conq}}, live_runes)
    assert found == [
        "_RUNE_OFFENSE_GRANTS[8233]: name 'Conqueror' != live 'Absolute Focus'",
        "_RUNE_OFFENSE_GRANTS[8233]: tree 'Precision' != live 'Sorcery'",
    ]

    bone = _RUNE_FLAT_MITIGATION["8473"]
    renamed = dataclasses.replace(bone, attribute="Bone Armor")
    found = rune_label_problems({"_RUNE_FLAT_MITIGATION": {"8473": renamed}}, live_runes)
    assert found == ["_RUNE_FLAT_MITIGATION[8473]: attribute 'Bone Armor' != live 'Bone Plating'"]

    found = rune_label_problems({"_RUNE_HSP_PCT": {"8138": 1.0}}, live_runes)
    assert found == ["_RUNE_HSP_PCT[8138]: not a live rune"]


# ---- S144-D-258: rune notes open with the live rune name ---------------------


def test_rune_notes_open_with_live_name(live_runes):
    with_note = [
        rid
        for reg in _RUNE_REGISTRIES.values()
        for rid, entry in reg.items()
        if getattr(entry, "note", None) is not None
    ]
    assert len(with_note) >= 13
    assert rune_note_problems(_RUNE_REGISTRIES, live_runes) == []


def test_rune_note_checker_catches_planted_defects(live_runes):
    grasp = _RUNE_HEALTH_GRANTS["8437"]
    found = rune_note_problems({"_RUNE_HEALTH_GRANTS": {"8451": grasp}}, live_runes)
    assert len(found) == 1
    assert found[0].startswith("_RUNE_HEALTH_GRANTS[8451]: note 'Grasp of the Undying:")


# ---- S144-D-259: item ids are live; inline comments name the live item -------


def test_item_registry_ids_are_live(live_items):
    assert sum(len(reg) for reg in _ITEM_REGISTRIES.values()) >= 280
    assert item_key_problems(_ITEM_REGISTRIES, live_items) == []


def test_inline_item_comments_name_the_live_item(live_items):
    rows = _all_comment_rows()
    assert len(rows) >= 260
    assert {fname for fname, *_ in rows} == {
        "_item_ability_haste.py",
        "_item_bonus_hp_amp.py",
        "_item_general_dr.py",
        "_item_lowhp_magic_crit.py",
        "_item_mana_health.py",
        "_item_omnivamp.py",
        "_item_proc_heal.py",
        "_item_revive.py",
        "_item_spell_shield_overrides.py",
        "_item_survival_window.py",
        "_item_tenacity.py",
        "_passive_reflect_overrides.py",
    }
    assert comment_problems(rows, live_items) == []


def test_comment_checker_catches_planted_defects(live_items):
    text = (
        '    "3075": 1.0,  # Bramble Vest\n'
        '    "3076": 1.0,  # Bramble Vest\n'
        '    "226660": 5.0,  # Bami\'s Cinder\n'
        '    "999999": 1.0,  # Nothing\n'
        '    "3075": 1.0,\n'
    )
    rows = [("planted", *row) for row in comment_rows(text)]
    assert [r[2] for r in rows] == ["3075", "3076", "226660", "999999"]
    assert comment_problems(rows, live_items) == [
        "planted:1 3075: comment 'Bramble Vest' != live 'Thornmail'",
        "planted:4 999999: not a live item",
    ]


def test_item_key_checker_catches_planted_defects(live_items):
    assert item_key_problems({"R": {"3075": 1.0, "999999": 1.0}}, live_items) == ["R[999999]: not a live item"]
