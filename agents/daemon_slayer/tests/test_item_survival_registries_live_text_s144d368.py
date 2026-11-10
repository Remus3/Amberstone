"""S144-D-368..371 - four DS item survival / amp registries match the live text they cite.

WHY. The item revive (R102), passive omnivamp (R100), self-stasis window (R103)
and low-HP magic crit (Cinderbloom) registries each document their mechanic,
registered ids, dropped mirrors and exclusions from the item text of the patch
they were written at (16.13.1). Their mirror and fail-soft guards pin the
VALUES; nothing pinned the prose to the live snapshot, and each had drifted.

* S144-D-368 ``_item_revive``: the docstring said the Arena Guardian Angel
  223026 "shares the identical Rebirth passive text". Live it names the passive
  "Saving Grace" and gives it "a one round cooldown" instead of the 300 second
  one; only the restored "50% base Health" is shared. It also cited 16.13.1
  ``items.json`` / ``items_meraki.json`` line numbers that no longer point at
  the rows.
* S144-D-369 ``_item_omnivamp``: it called Hemomancer's Helm 447103 "NOT an
  omnivamp grant". Its live ``<stats>`` block prints 15% Omnivamp, as Endless
  Hunger 2517 prints 5%: sixteen live ids carry a flat stat-line omnivamp that
  the structured ``stats`` dict omits and no engine path reads (only this
  passive registry sets ``stats["omnivamp"]``). The docstring now says the
  registry is passive-only and names the stat-line gap (filed S144-D-372).
* S144-D-370 ``_item_survival_window``: Wooglet's Witchcap 228002 was called
  "Arena-native"; it is live on maps 12 and 30. The Arena Zhonya's 223157 was
  said to share "the identical Time Stop active"; it names its active "Stasis"
  and words it differently (same 2.5s). Seeker's Armguard 2420's live Time Stop
  is "(Single use)", which the docstring never said (value change filed
  S144-D-373). The Guardian Angel stasis rows were not named as excluded.
* S144-D-371 ``_item_lowhp_magic_crit``: it said Shadowflame is "DDragon-only
  in the item index"; Meraki carries 4645 Cinderbloom ("120% damage", the same
  +20%). It labelled 4645 ``maps.11``; it is live on maps 11, 12 and 453.

MEASURED 2026-11-09 (``data/daemon_slayer/current.txt`` = 16.22.1). Docstring
fixes only; no registry value or code path changes, so scorer output is
byte-identical.
"""

from __future__ import annotations

import json
import re
from functools import cache
from pathlib import Path
from typing import Any

import pytest

from agents.daemon_slayer import _item_lowhp_magic_crit as crit_mod
from agents.daemon_slayer import _item_omnivamp as vamp_mod
from agents.daemon_slayer import _item_revive as revive_mod
from agents.daemon_slayer import _item_survival_window as stasis_mod

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


def _meraki_text(iid: str, name: str) -> str:
    row = _meraki()[iid]
    for block in list(row.get("passives") or []) + list(row.get("active") or []):
        if block.get("name") == name:
            return block.get("effects") or ""
    raise AssertionError(f"Meraki {iid} carries no {name!r} passive or active")


def _names(name: str) -> set[str]:
    return {k for k, v in _items().items() if v.get("name") == name}


_DOCS = {
    "_item_revive": _flat(revive_mod.__doc__ or ""),
    "_item_omnivamp": _flat(vamp_mod.__doc__ or ""),
    "_item_survival_window": _flat(stasis_mod.__doc__ or ""),
    "_item_lowhp_magic_crit": _flat(crit_mod.__doc__ or ""),
}


@pytest.mark.parametrize("mod", sorted(_DOCS))
def test_docstring_cites_no_snapshot_line_numbers(mod: str) -> None:
    # A line number in a vendored JSON moves on every re-extract; the 16.13.1
    # cites no longer pointed at their rows.
    assert not re.search(r"items(?:_meraki)?\.json:\d", _DOCS[mod]), mod


# --------------------------------------------------------------------------
# S144-D-368 - _item_revive
# --------------------------------------------------------------------------

_REVIVE_RE = re.compile(r"Upon taking lethal damage, restores 50% base Health")


def test_revive_registry_is_exactly_the_live_carrier_set() -> None:
    live = {k for k in _items() if _REVIVE_RE.search(_desc(k))}
    assert live == set(revive_mod._ITEM_REVIVE) == {"3026", "223026"}
    assert _names("Guardian Angel") == live
    assert set(revive_mod._ITEM_REVIVE.values()) == {0.50}


def test_revive_base_rebirth_magnitude_and_cooldown_are_live() -> None:
    text = _meraki_text("3026", "Rebirth")
    assert "50% of '''base''' health" in text
    assert "300 second cooldown" in text
    assert "3026" in _meraki() and "223026" not in _meraki()


def test_revive_docstring_names_the_arena_saving_grace_wording() -> None:
    arena = _desc("223026")
    assert "Saving Grace" in arena and "one round cooldown" in arena
    assert "300 second" not in arena
    doc = _DOCS["_item_revive"]
    assert "identical Rebirth passive text" not in doc
    assert "Saving Grace" in doc and "one round cooldown" in doc


def test_revive_dropped_mirror_stays_absent() -> None:
    assert "323026" not in _items() and "323026" not in revive_mod._ITEM_REVIVE
    assert "323026" in _DOCS["_item_revive"]


# --------------------------------------------------------------------------
# S144-D-369 - _item_omnivamp
# --------------------------------------------------------------------------

_STATS_RE = re.compile(r"<stats>(.*?)</stats>", re.S)


def _stat_line_omnivamp_ids() -> set[str]:
    out = set()
    for k, v in _items().items():
        m = _STATS_RE.search(v.get("description", ""))
        if m and "Omnivamp" in _plain(m.group(1)):
            out.add(k)
    return out


def test_omnivamp_registry_is_riftmaker_at_its_live_split() -> None:
    assert set(vamp_mod._ITEM_OMNIVAMP) == _names("Riftmaker") == {"4633", "224633"}
    assert "{{rd|10%|6%}} omnivamp" in _meraki_text("4633", "Void Corruption")
    assert set(vamp_mod._ITEM_OMNIVAMP.values()) == {(0.10, 0.06)}
    for iid in vamp_mod._ITEM_OMNIVAMP:
        assert "At maximum strength, gain Omnivamp" in _desc(iid)


def test_omnivamp_regeneration_scan_matches_the_docstring() -> None:
    hits = {
        k
        for k, v in _meraki().items()
        for p in v.get("passives") or []
        if "omnivamp}}" in (p.get("effects") or "")
    }
    assert hits == {"2517", "3156", "4633", "447103"}
    doc = _DOCS["_item_omnivamp"]
    for iid in hits:
        assert iid in doc, iid


def test_omnivamp_docstring_names_the_stat_line_gap() -> None:
    ids = _stat_line_omnivamp_ids()
    assert {"2517", "447103", "1055", "3146"} <= ids
    assert not ids & set(vamp_mod._ITEM_OMNIVAMP)
    for iid in ids:
        assert "vamp" not in json.dumps(_items()[iid].get("stats", {})).lower(), iid
    doc = _DOCS["_item_omnivamp"]
    assert "NOT an omnivamp grant" not in doc
    assert "S144-D-372" in doc
    m = re.search(r"(\d+) DDragon item ids print a flat", doc)
    assert m, "docstring lost its stat-line carrier count"
    assert int(m.group(1)) == len(ids)


def test_the_omnivamp_registry_is_the_only_engine_writer_of_stats_omnivamp() -> None:
    # The docstring says no engine path reads a stat-line omnivamp; a second
    # writer of stats["omnivamp"] would make that false.
    pkg = _REPO_ROOT / "agents" / "daemon_slayer"
    writer = re.compile(r"""stats\[["']omnivamp["']\]\s*=""")
    hits = sorted(
        f.name
        for f in pkg.glob("*.py")
        if writer.search(f.read_text(encoding="utf-8"))
    )
    assert hits == ["ehp.py"]
    src = (pkg / "ehp.py").read_text(encoding="utf-8")
    assert len(writer.findall(src)) == 1
    assert "item_omnivamp_fraction(resolved.item_ids, is_ranged)" in src


def test_omnivamp_dropped_ids_stay_absent() -> None:
    for iid in ("324633", "124633"):
        assert iid not in _items() and iid not in vamp_mod._ITEM_OMNIVAMP
        assert iid in _DOCS["_item_omnivamp"]


# --------------------------------------------------------------------------
# S144-D-370 - _item_survival_window
# --------------------------------------------------------------------------


def test_stasis_registry_is_the_live_stasis_set_minus_guardian_angel() -> None:
    live = {k for k in _items() if re.search(r"\bstasis\b", _desc(k), re.I)}
    assert live - set(stasis_mod._ITEM_SURVIVAL_WINDOW) == {"3026", "223026"}
    assert set(stasis_mod._ITEM_SURVIVAL_WINDOW) <= live
    for iid, window in stasis_mod._ITEM_SURVIVAL_WINDOW.items():
        assert window == 2.5 and "for 2.5 seconds" in _desc(iid), iid
    doc = _DOCS["_item_survival_window"]
    assert "Guardian Angel" in doc and "3026" in doc and "223026" in doc


def test_stasis_docstring_matches_live_maps_and_wording() -> None:
    doc = _DOCS["_item_survival_window"]
    assert _maps("228002") == ["12", "30"]
    assert "Arena-native" not in doc
    assert "maps 12 and 30" in doc
    assert "Active - Stasis" in _desc("223157")
    assert "identical Time Stop active" not in doc
    for iid in ("3157", "2420", "228002"):
        assert "Enter Stasis for 2.5 seconds" in _desc(iid), iid
    assert "|stasis}} for {{fd|2.5}} seconds" in _meraki_text("228002", "Stasis")
    assert _meraki_text("3157", "Time Stop") == _meraki_text("2420", "Time Stop")


def test_stasis_docstring_says_seekers_armguard_is_single_use() -> None:
    assert "(Single use)" in _desc("2420")
    doc = _DOCS["_item_survival_window"]
    assert "Single use" in doc and "S144-D-373" in doc


def test_stasis_dropped_mirrors_stay_absent() -> None:
    for iid in ("323157", "222420", "322420", "22228002", "32228002"):
        assert iid not in _items() and iid not in stasis_mod._ITEM_SURVIVAL_WINDOW
        assert iid in _DOCS["_item_survival_window"], iid


# --------------------------------------------------------------------------
# S144-D-371 - _item_lowhp_magic_crit
# --------------------------------------------------------------------------

_CRIT_RE = re.compile(
    r"Magic and true damage Critically Strikes? enemies below (\d+)% Health, "
    r"dealing (\d+)% increased damage"
)


def test_lowhp_registry_is_the_live_cinderbloom_set_at_its_live_values() -> None:
    live = {}
    for k in _items():
        m = _CRIT_RE.search(_desc(k))
        if m:
            live[k] = (int(m.group(1)), int(m.group(2)))
    assert set(live) == set(crit_mod._ITEM_LOWHP_MAGIC_CRIT) == {"4645", "224645"}
    for iid, (gate, amp) in live.items():
        assert gate / 100 == crit_mod._LOWHP_THRESHOLD, iid
        assert amp / 100 == crit_mod._ITEM_LOWHP_MAGIC_CRIT[iid], iid


def test_lowhp_docstring_matches_live_meraki_and_maps() -> None:
    text = _meraki_text("4645", "Cinderbloom")
    assert "120% damage" in text and "below 40% '''maximum''' health" in text
    assert "224645" not in _meraki()
    doc = _DOCS["_item_lowhp_magic_crit"]
    assert "DDragon-only" not in doc
    assert "120%" in doc
    assert _maps("4645") == ["11", "12", "453"]
    assert _maps("224645") == ["30"]
    assert "(SR, ``maps.11``" not in doc
    assert "maps 11, 12 and 453" in doc


def test_lowhp_dropped_mirror_stays_absent() -> None:
    assert "324645" not in _items()
    assert "324645" not in crit_mod._ITEM_LOWHP_MAGIC_CRIT
    assert "324645" in _DOCS["_item_lowhp_magic_crit"]
