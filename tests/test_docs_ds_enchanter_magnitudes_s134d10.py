"""Guard (RM-918): DS doc magnitudes and deferred-item claims are re-derived from data.

``docs/DAEMON_SLAYER.md``'s ``hps.py`` module-map row names a magnitude beside
most curated enchanter items. RM-917 pinned the row's COUNT and its item
NAMES; nothing read the magnitudes, and one was wrong: "Echoes of Helia Soul
Siphon 50 HP" is neither end of the curated 40 -> 70 per-proc range in
``enchanter_items.json`` (base 40, +1.76 per level over 17 levels), and the row
dropped the 15% AP ratio the engine credits.

The "Permanently deferred items (N)" section also sat unread. At patch 16.21.1
Lightning Braid (4013) is on NO map (DDragon ``maps`` all false), which the
section did not say. Each check below measures the claim from the snapshot
named by ``current.txt`` and the live ``ITEM_EFFECTS`` registry, so a patch
refresh or an engine change that moves one fails here instead of rotting.
ASCII only (CLAUDE.md hard rule).
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from agents.daemon_slayer._effects_data import ITEM_EFFECTS

_REPO_ROOT = Path(__file__).resolve().parents[1]
_DOC = _REPO_ROOT / "docs" / "DAEMON_SLAYER.md"
_DATA_ROOT = _REPO_ROOT / "data" / "daemon_slayer"
_LEVEL_SPAN = 17  # level 1 -> 18, the span every per_level field is curated over


def _patch() -> str:
    return (_DATA_ROOT / "current.txt").read_text(encoding="utf-8").strip()


def _load(name: str) -> dict:
    return json.loads((_DATA_ROOT / _patch() / name).read_text(encoding="utf-8"))


def _doc() -> str:
    return _DOC.read_text(encoding="utf-8")


def _hps_row() -> str:
    rows = [ln for ln in _doc().splitlines() if ln.startswith("| `hps.py` |")]
    assert len(rows) == 1, f"expected exactly one hps.py module-map row, got {len(rows)}"
    return rows[0]


def _formula(name: str) -> dict:
    items = _load("enchanter_items.json")["items"]
    hits = [v for k, v in items.items() if len(k) <= 4 and v["name"] == name]
    assert len(hits) == 1, f"expected one bare enchanter row named {name!r}, got {len(hits)}"
    return hits[0]


def _match(pattern: str, text: str, what: str) -> re.Match:
    m = re.search(pattern, text)
    assert m is not None, f"{what}: prose shape {pattern!r} not found - state the magnitude, do not drop it"
    return m


def _range(base: float, per_level: float) -> tuple[int, int]:
    return round(base), round(base + per_level * _LEVEL_SPAN)


# --- hps.py row magnitudes --------------------------------------------------


def test_moonstone_chain_amp_matches_formula():
    m = _match(r"Moonstone Renewer (\d+)% chain amp", _hps_row(), "Moonstone")
    assert int(m.group(1)) == round(_formula("Moonstone Renewer")["heal_shield_amp_pct"] * 100)


def test_redemption_heal_range_matches_formula():
    f = _formula("Redemption")
    m = _match(r"Redemption AoE heal (\d+)->(\d+)", _hps_row(), "Redemption")
    assert (int(m.group(1)), int(m.group(2))) == _range(f["heal_per_proc_base"], f["heal_per_proc_per_level"])


def test_helia_soul_siphon_range_ratio_and_rate_match_formula():
    """The exact defect: '50 HP' was a mid-level figure, not the curated range."""
    f = _formula("Echoes of Helia")
    m = _match(
        r"Echoes of Helia Soul Siphon (\d+)->(\d+) HP \+ (\d+)% AP x ([\d.]+)/s",
        _hps_row(),
        "Echoes of Helia",
    )
    assert (int(m.group(1)), int(m.group(2))) == _range(f["heal_per_proc_base"], f["heal_per_proc_per_level"])
    assert int(m.group(3)) == round(f["heal_per_proc_ap_scaling"] * 100)
    assert float(m.group(4)) == pytest.approx(f["heal_procs_per_second"])


def test_locket_shield_range_matches_formula():
    f = _formula("Locket of the Iron Solari")
    m = _match(r"Locket of the Iron Solari AoE shield (\d+)->(\d+)", _hps_row(), "Locket")
    assert (int(m.group(1)), int(m.group(2))) == _range(f["shield_per_proc_base"], f["shield_per_proc_per_level"])


@pytest.mark.parametrize(
    "name",
    ["Ardent Censer", "Staff of Flowing Water", "Imperial Mandate", "Knight's Vow"],
)
def test_ally_buff_credit_matches_formula(name):
    m = _match(re.escape(name) + r" \+(\d+)", _hps_row(), name)
    assert int(m.group(1)) == round(_formula(name)["ally_buff_credit_per_second"])


# --- permanently deferred items ---------------------------------------------


def _deferred_section() -> tuple[int, list[str]]:
    m = _match(
        r"## Permanently deferred items \((\d+)\)\n\n((?:\d+\. .*\n)+)",
        _doc(),
        "deferred section",
    )
    return int(m.group(1)), m.group(2).strip().splitlines()


def _deferred_line(label: str) -> str:
    _, lines = _deferred_section()
    hits = [ln for ln in lines if f"**{label}**" in ln]
    assert len(hits) == 1, f"expected one deferred line for {label!r}, got {len(hits)}"
    return hits[0]


def _ddragon_item(item_id: str) -> dict:
    return _load("items.json")["data"][item_id]


def test_deferred_heading_count_matches_list():
    count, lines = _deferred_section()
    assert count == len(lines)


@pytest.mark.parametrize(("label", "item_id"), [("Lightning Braid", "4013"), ("Kinkou Jitte", "447116")])
def test_deferred_item_is_named_by_id_and_still_uncredited(label, item_id):
    """A deferred item that the engine starts crediting makes the section stale."""
    line = _deferred_line(label)
    assert f"({item_id})" in line, f"{label}: name the item id so the claim can be probed"
    effect = ITEM_EFFECTS.get(item_id)
    assert effect is not None, f"{label} ({item_id}) left ITEM_EFFECTS - re-check the deferral"
    assert effect.defensive_only is True, f"{label} ({item_id}) is now credited - move it out of the deferred list"


def test_lightning_braid_map_status_is_stated_from_ddragon():
    line = _deferred_line("Lightning Braid")
    on_no_map = not any(_ddragon_item("4013")["maps"].values())
    assert ("not on any map" in line) == on_no_map


def test_lightning_braid_meraki_claim_matches_snapshot():
    line = _deferred_line("Lightning Braid")
    meraki_items = _load("items_meraki.json")["items"]
    assert "3041" in meraki_items, "Meraki snapshot shape moved - the membership probe below would be vacuous"
    in_meraki = "4013" in meraki_items
    assert ("no formula in Meraki" in line) == (not in_meraki)


def test_kinkou_jitte_arena_only_claim_matches_ddragon():
    line = _deferred_line("Kinkou Jitte")
    on_maps = {k for k, v in _ddragon_item("447116")["maps"].items() if v}
    assert ("Arena-only" in line) == (on_maps == {"30"})


def test_mejai_arena_mirror_still_absent_from_ddragon():
    line = _deferred_line("Mejai's Arena mirror")
    assert "3041 is the only Mejai's row" in line
    rows = sorted(k for k, v in _load("items.json")["data"].items() if "Mejai" in v["name"])
    assert rows == ["3041"], f"Mejai's rows are now {rows} - re-check the deferral"
    assert _ddragon_item("3041")["maps"]["30"] is False, "3041 is now on Arena (map 30) - re-check the deferral"
