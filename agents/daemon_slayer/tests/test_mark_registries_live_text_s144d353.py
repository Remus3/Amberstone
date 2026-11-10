"""S144-D-353..356 - the DS mark registries match the live text they cite.

WHY. Two pure registries model a mark a champion or item lays on the target:
``_target_vulnerability_overrides`` (an all-source +X% damage-taken mark) and
``_ally_detonation_overrides`` (a discrete chunk an ALLY deals when it
consumes the mark). Both carry prose that was verified once, at 16.12.1 or
16.13.1, and never re-measured. ``_effects_data`` carries a third copy of the
Imperial Mandate story in its ``note=`` strings. Re-measured against the
current snapshot:

* S144-D-353: the 324005 vulnerability note gave it the retired map-12 label
  with the "32-mirror" spelling.
  Every ``32xxxx`` row is map 11 only (the S144-D-334 guard); its token
  pattern missed the ``32-mirror`` spelling. That guard now catches it.
* S144-D-354: the three ``_effects_data`` Imperial Mandate rows (4005 /
  224005 / 324005) still described the pre-16.13.1 Coordinated Fire
  detonation. The live text of all three ids is Control + Command (a
  Vulnerable mark), and only the Meraki mirror still carries Coordinated
  Fire. Note and comment text only.
* S144-D-355: the vulnerability registry's magnitudes are tied to the live
  text. The Arena 224005 copy reads 6% Vulnerable in every snapshot dir on
  disk from 16.12.1 to 16.22.1 (16.16.1 / 16.17.1 were never snapshotted),
  never the 7% the registry carries and its note called
  "identical". The magnitude fix is an item-effect change, so it is filed
  Tier-2 (S144-D-357) and pinned here as a known drift that fails the day
  either side moves. Evenshroud 3001 / 223001 is in the snapshot but is not
  purchasable and is on no map in any snapshot dir on disk from 16.10.1 to
  16.22.1, so
  the docstring no longer calls it ACTIVE.
* S144-D-356: the ally-detonation registry's Leona P row matches the live
  Sunlight text (32 : 151, 2.5 s mark), its empty item registry matches a
  scan of the live item text, and its "only the Meraki mirror still carries
  Coordinated Fire" claim matches both feeds.

MEASURED 2026-11-09 (``data/daemon_slayer/current.txt`` = 16.22.1). Prose
and test only: scorer output is byte-identical.
"""

from __future__ import annotations

import json
import re
from functools import cache
from pathlib import Path
from typing import Any

from agents.daemon_slayer import _ally_detonation_overrides as det
from agents.daemon_slayer import _target_vulnerability_overrides as vuln
from agents.daemon_slayer._effects_data import ITEM_EFFECTS

_ROOT = Path(__file__).resolve().parents[3]
_DS_DATA = _ROOT / "data" / "daemon_slayer"
_EFFECTS_SRC = _ROOT / "agents" / "daemon_slayer" / "_effects_data.py"

_TAG = re.compile(r"<[^>]+>")
_WS = re.compile(r"\s+")
_ITEM_PCT = re.compile(r"(\d+(?:\.\d+)?)% (?:Vulnerable|increased damage)")
_IMPERIAL_IDS = ("4005", "224005", "324005")

# S144-D-357 (Tier-2, not a lane change): the live text reads this amp; the
# registry still carries 0.07. Remove the row when the registry is re-seeded.
_KNOWN_AMP_DRIFT: dict[str, float] = {"224005": 0.06}


def _patch() -> str:
    return (_DS_DATA / "current.txt").read_text(encoding="utf-8").strip()


@cache
def _live_items() -> dict[str, Any]:
    doc = json.loads((_DS_DATA / _patch() / "items.json").read_text(encoding="utf-8"))
    return doc["data"]


@cache
def _meraki_items() -> dict[str, Any]:
    path = _DS_DATA / _patch() / "items_meraki.json"
    return json.loads(path.read_text(encoding="utf-8"))["items"]


@cache
def _abilities() -> dict[str, Any]:
    path = _DS_DATA / _patch() / "champion_abilities.json"
    return json.loads(path.read_text(encoding="utf-8"))["data"]


def _item_text(item_id: str) -> str:
    row = _live_items()[item_id]
    return _WS.sub(" ", _TAG.sub(" ", row.get("description", ""))).strip()


def _ability_text(champion: str, slot: str) -> str:
    forms = _abilities()[champion][slot]
    return " ".join(" ".join(f.get("effects_descriptions") or []) for f in forms)


def _live_item_amp(item_id: str) -> float:
    found = _ITEM_PCT.findall(_item_text(item_id))
    assert len(found) == 1, f"{item_id}: expected one mark percent, got {found}"
    return float(found[0]) / 100.0


def _maps(item_id: str) -> frozenset[str]:
    return frozenset(k for k, v in (_live_items()[item_id].get("maps") or {}).items() if v)


# -- S144-D-355: _target_vulnerability_overrides --------------------------------


def test_every_item_vuln_row_is_in_the_live_snapshot() -> None:
    keys = set(vuln._ITEM_VULN_OVERRIDES)
    assert keys == {"3001", "223001", "4005", "224005", "324005"}
    missing = sorted(k for k in keys if k not in _live_items())
    assert not missing, f"registry ids absent from the live snapshot: {missing}"


def test_item_vuln_amps_match_the_live_text() -> None:
    wrong = {}
    for key, entry in vuln._ITEM_VULN_OVERRIDES.items():
        if key in _KNOWN_AMP_DRIFT:
            continue
        live = _live_item_amp(key)
        if abs(entry.amp - live) > 1e-9:
            wrong[key] = (entry.amp, live)
    assert not wrong, f"registry amp != live text percent: {wrong}"


def test_known_amp_drift_is_still_open() -> None:
    for key, live_amp in _KNOWN_AMP_DRIFT.items():
        assert abs(_live_item_amp(key) - live_amp) < 1e-9, (
            f"{key}: live text moved off {live_amp}; re-measure S144-D-357"
        )
        assert abs(vuln._ITEM_VULN_OVERRIDES[key].amp - live_amp) > 1e-9, (
            f"{key}: registry now matches the live text; drop it from _KNOWN_AMP_DRIFT"
        )


def test_arena_imperial_note_does_not_claim_the_sr_magnitude() -> None:
    note = vuln._ITEM_VULN_OVERRIDES["224005"].note
    assert "identical" not in note
    assert "6% Vulnerable" in note
    assert "S144-D-357" in note


def test_vladimir_r_amp_matches_the_live_text() -> None:
    text = _ability_text("Vladimir", "R")
    found = re.findall(r"from all sources by (\d+)%", text)
    assert found == ["10"], found
    assert vuln._CHAMPION_VULN_OVERRIDES["Vladimir"].amp == float(found[0]) / 100.0
    assert set(vuln._CHAMPION_VULN_OVERRIDES) == {"Vladimir"}


def test_evenshroud_rows_are_unbuyable_and_the_docstring_says_so() -> None:
    for key in ("3001", "223001"):
        row = _live_items()[key]
        assert row["gold"]["purchasable"] is False, key
        assert _maps(key) == frozenset(), key
    doc = vuln.__doc__ or ""
    start = doc.index("* Evenshroud (3001")
    para = doc[start : doc.index("* Imperial Mandate (4005", start)]
    assert "ACTIVE" not in para
    assert "not purchasable" in para


def test_imperial_mandate_rows_are_on_their_maps() -> None:
    assert "11" in _maps("4005")
    assert _maps("224005") == {"30"}
    assert _maps("324005") == {"11"}


# -- S144-D-356: _ally_detonation_overrides -------------------------------------


def test_leona_p_row_matches_the_live_sunlight_text() -> None:
    text = _ability_text("Leona", "P")
    window = re.findall(r"mark enemies hit for ([\d.]+) seconds", text)
    ramp = re.findall(r"deal (\d+) : (\d+) \(based on level\) bonus magic damage", text)
    assert window == ["2.5"], window
    assert ramp == [("32", "151")], ramp
    entry = det._CHAMPION_DETONATION_OVERRIDES["Leona"]
    assert entry.kind == "FLAT_MAGIC"
    assert (entry.flat_lo, entry.flat_hi) == (32.0, 151.0)
    assert entry.cadence_s == float(window[0])
    assert set(det._CHAMPION_DETONATION_OVERRIDES) == {"Leona"}


def test_no_live_item_text_carries_an_ally_current_health_detonation() -> None:
    hits = sorted(
        key
        for key in _live_items()
        if re.search(r"current health", _item_text(key), re.IGNORECASE)
        and re.search(r"\bmark|\bconsume|detonat", _item_text(key), re.IGNORECASE)
    )
    assert hits == [], hits
    assert det._ITEM_DETONATION_OVERRIDES == {}
    assert det._NONFIT_DETONATION_CANDIDATES == {}


def test_only_the_meraki_mirror_still_carries_coordinated_fire() -> None:
    names = [p.get("name") for p in _meraki_items()["4005"].get("passives") or []]
    assert "Coordinated Fire" in names, names
    for key in _IMPERIAL_IDS:
        text = _item_text(key)
        assert "Coordinated Fire" not in text, key
        assert "Command" in text and "Vulnerable" in text, key


# -- S144-D-354: _effects_data Imperial Mandate notes ---------------------------


def test_effects_data_imperial_notes_name_the_live_passive() -> None:
    for key in _IMPERIAL_IDS:
        note = ITEM_EFFECTS[key].note
        assert "Coordinated Fire" not in note, (key, note)
        assert "Command" in note and "Vulnerable" in note, (key, note)
        pct = f"{round(_live_item_amp(key) * 100)}% Vulnerable"
        assert pct in note, (key, note)


def test_effects_data_imperial_source_block_drops_coordinated_fire() -> None:
    lines = _EFFECTS_SRC.read_text(encoding="utf-8").splitlines()
    for key in _IMPERIAL_IDS:
        start = next(i for i, ln in enumerate(lines) if ln.strip() == f'"{key}": ItemEffect(')
        end = next(i for i in range(start, len(lines)) if lines[i].strip() == "),")
        block = "\n".join(lines[start : end + 1])
        assert "Coordinated Fire" not in block, key
