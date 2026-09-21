"""Guard: the per-item Ability-Haste registry stays in lock-step with live DDragon.

The hand-pinned ``_item_ability_haste._ITEM_ABILITY_HASTE`` (220 items) has no
committed regen tool, so a patch that re-values an item's AH silently drifts the
registry - and every existing test asserts HARDCODED values, so nothing catches
it. Exactly that happened: at 16.13.1 Riot re-valued Eclipse's Arena mirror
226692 (10 -> 15, matching base 6692) and the pin + the value-assertion tests
both missed it, uncaught until the 16.14.1 refresh audit.

These two guards make the drift class fail LOUDLY at CI time going forward:

  1. ``test_registry_matches_live_ddragon`` re-derives the AH dict from the
     CURRENT-patch DDragon item.json (via the drift-check tool's canonical
     parse) and asserts zero add/remove/value drift vs the pin. Any future AH
     re-value fails here until the registry is re-pinned in the same commit.
  2. ``test_drift_check_default_tracks_current_patch`` pins the fix to the
     drift-check TOOL: its no-arg default must resolve the LIVE patch
     (current.txt), not a hardcoded stale catalog (the original bug: the tool
     hardcoded 16.12.1 and false-reported IN SYNC).

Repo-level (not agents/daemon_slayer/tests/) on purpose: it imports the
ops/audit drift-check tool, which sits outside the engine package and which
the engine suite must stay able to run without.
ASCII only (CLAUDE.md hard rule).
"""
from __future__ import annotations

import json
from pathlib import Path

import ops.audit.item_ah_drift_check as ahc
from agents.daemon_slayer._item_ability_haste import _ITEM_ABILITY_HASTE

_REPO_ROOT = Path(__file__).resolve().parents[1]
_CURRENT = _REPO_ROOT / "data" / "daemon_slayer" / "current.txt"


def _current_patch() -> str:
    return _CURRENT.read_text(encoding="utf-8").strip()


def test_registry_matches_live_ddragon() -> None:
    patch = _current_patch()
    item_json = _REPO_ROOT / "data" / "meta_build" / "ddragon" / patch / "item.json"
    assert item_json.exists(), f"no DDragon item.json for live patch {patch}"

    derived = ahc.derive_from_ddragon(item_json)
    pinned = _ITEM_ABILITY_HASTE

    changed = {
        i: (pinned[i], derived[i])
        for i in set(pinned) & set(derived)
        if pinned[i] != derived[i]
    }
    added = sorted(set(derived) - set(pinned), key=int)     # DDragon has AH, pin missing
    removed = sorted(set(pinned) - set(derived), key=int)   # pin has AH, DDragon dropped

    assert not changed, (
        f"item-AH pin value drift vs DDragon {patch}: {changed}. Re-pin "
        "agents/daemon_slayer/_item_ability_haste.py in this commit."
    )
    assert not added and not removed, (
        f"item-AH id-set drift vs DDragon {patch}: added={added} removed={removed}. "
        "Re-pin the registry in this commit."
    )


def test_drift_check_default_tracks_current_patch() -> None:
    # The tool's no-arg default catalog must follow the live patch, else it is a
    # blind guard (the original bug hardcoded 16.12.1 and false-cleaned).
    resolved = ahc._default_item_json()
    patch = _current_patch()
    assert patch in str(resolved), (
        f"drift-check default {resolved} does not track current.txt patch {patch}"
    )
    assert resolved.exists(), f"resolved default item.json missing: {resolved}"


# ---------------------------------------------------------------------------
# Ornn masterwork coverage (the <ornnBonus> blind spot).
#
# The original parse only matched "<attention>N</attention> Ability Haste", so
# an Ornn masterwork whose AH sits in "<ornnBonus>N</ornnBonus> Ability Haste"
# (e.g. Wooglet's Witchcap 228002, 20 AH at 16.15.1) was SILENTLY SKIPPED and
# the IN SYNC verdict said nothing about it. Masterworks are excluded from
# recommendations by design (agents/daemon_slayer/rank.py _is_ornn_masterwork)
# and must NOT gain registry rows - so the checker classifies them explicitly
# as excluded-by-design instead of dropping them on the floor.
# ---------------------------------------------------------------------------

_ORNN_DESC = (
    "<mainText><stats><ornnBonus>300</ornnBonus> Ability Power<br>"
    "<ornnBonus>50</ornnBonus> Armor<br><ornnBonus>20</ornnBonus> Ability Haste"
    "</stats></mainText>"
)
_BUY_DESC = (
    "<mainText><stats><attention>45</attention> Ability Power<br>"
    "<attention>15</attention> Ability Haste</stats></mainText>"
)
# An AH line in a tag neither arm knows: must surface as UNPARSED, not vanish.
_ODD_DESC = "<mainText><stats><rarityMythic>9</rarityMythic> Ability Haste</stats></mainText>"


def _fixture(tmp_path: Path, rows: dict[str, str]) -> Path:
    blob = {
        "version": "0.0.0",
        "data": {i: {"name": f"item{i}", "description": d} for i, d in rows.items()},
    }
    p = tmp_path / "item.json"
    p.write_text(json.dumps(blob), encoding="utf-8")
    return p


def test_ornn_bonus_ah_is_detected_and_classified_excluded(tmp_path: Path) -> None:
    p = _fixture(tmp_path, {"228002": _ORNN_DESC, "3100": _BUY_DESC})
    cls = ahc.classify_ddragon(p)
    assert cls.ornn_excluded == {"228002": 20.0}
    assert cls.buyable == {"3100": 15.0}
    assert cls.unparsed == []
    # derive_from_ddragon stays the BUYABLE set the registry is diffed against,
    # so a masterwork never reads as a missing registry row.
    assert ahc.derive_from_ddragon(p) == {"3100": 15.0}


def test_unknown_tag_ah_line_surfaces_as_unparsed(tmp_path: Path) -> None:
    p = _fixture(tmp_path, {"9999": _ODD_DESC})
    cls = ahc.classify_ddragon(p)
    assert cls.unparsed == ["9999"]
    assert cls.buyable == {} and cls.ornn_excluded == {}


def test_main_reports_ornn_excluded_by_design(tmp_path: Path, monkeypatch, capsys) -> None:
    p = _fixture(tmp_path, {"228002": _ORNN_DESC})
    monkeypatch.setattr(ahc, "_load_pin", lambda: {})
    monkeypatch.setattr("sys.argv", ["item_ah_drift_check.py", str(p)])
    rc = ahc.main()
    out = capsys.readouterr().out
    assert rc == 0
    assert "EXCLUDED BY DESIGN" in out and "228002" in out


def test_main_fails_on_unparsed_ah_line(tmp_path: Path, monkeypatch, capsys) -> None:
    p = _fixture(tmp_path, {"9999": _ODD_DESC})
    monkeypatch.setattr(ahc, "_load_pin", lambda: {})
    monkeypatch.setattr("sys.argv", ["item_ah_drift_check.py", str(p)])
    assert ahc.main() == 1
    assert "UNPARSED" in capsys.readouterr().out


def test_live_catalog_every_ah_line_is_classified() -> None:
    # Coverage honesty on the live patch: no AH line in any <stats> block may
    # fall through both arms, and no masterwork may carry a registry row.
    item_json = _REPO_ROOT / "data" / "meta_build" / "ddragon" / _current_patch() / "item.json"
    cls = ahc.classify_ddragon(item_json)
    assert cls.unparsed == [], f"AH lines neither arm parses: {cls.unparsed}"
    assert not set(cls.ornn_excluded) & set(_ITEM_ABILITY_HASTE), (
        "an Ornn masterwork gained a registry row; masterworks are excluded by design"
    )
    # Anchor against vacuity: the live catalog does carry masterwork AH today.
    assert cls.ornn_excluded, "expected at least one <ornnBonus> AH masterwork"
