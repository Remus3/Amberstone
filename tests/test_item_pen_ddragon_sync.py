"""Guard: engine-hardcoded item PENETRATION magnitudes track live DDragon <stats>.

CLAUDE.md Settled: item PEN / LETHALITY magnitudes come from DDragon ``<stats>``
only, never Meraki. ``ITEM_EFFECTS`` is the SOLE credit path for them (no
generic stat key carries penetration), and every value is hand-pinned. Until
RM-766 only Ability Haste had a drift checker (``ops/audit/item_ah_drift_check.py``),
so DDragon 16.21.1 moving Bastionbreaker (2520) Lethality 22 -> 18 inside its
``<stats>`` block reached the engine unnoticed: the refresh's targeted tests and
two hardcoded 22.0 assertions all stayed green.

``ops/audit/item_pen_drift_check.py`` re-derives Lethality, % Armor
Penetration, flat Magic Penetration and % Magic Penetration from the
current-patch DDragon item.json and diffs them against the engine's
``lethality`` / ``armor_pen_pct`` / ``magic_pen_flat`` / ``magic_pen_pct``
(plus ``armor_pen_flat``, which no DDragon stat line states). This module pins:

  1. ``test_engine_pen_matches_live_ddragon`` - zero add / remove / value drift
     at current.txt. It FAILED on 2520 before the RM-766 fix.
  2. the tool's no-arg default tracks current.txt (the AH checker's original
     blind-default bug, not repeated here);
  3. coverage honesty: Ornn masterworks, the throwback band and unparsed pen
     lines are classified, never silently skipped; the passive-pen allowlist
     cannot rot.

Repo-level (not agents/daemon_slayer/tests/) on purpose, like the AH guard: it
imports the ops/audit tool, which the engine suite must stay able to run
without. ASCII only (CLAUDE.md hard rule).
"""
from __future__ import annotations

import json
from pathlib import Path

import ops.audit.item_pen_drift_check as pdc
from agents.daemon_slayer.effects import ITEM_EFFECTS

_REPO_ROOT = Path(__file__).resolve().parents[1]
_CURRENT = _REPO_ROOT / "data" / "daemon_slayer" / "current.txt"


def _current_patch() -> str:
    return _CURRENT.read_text(encoding="utf-8").strip()


def _live_item_json() -> Path:
    return _REPO_ROOT / "data" / "meta_build" / "ddragon" / _current_patch() / "item.json"


def test_engine_pen_matches_live_ddragon() -> None:
    item_json = _live_item_json()
    assert item_json.exists(), f"no DDragon item.json for live patch {_current_patch()}"
    report = pdc.diff(pdc.classify_ddragon(item_json), pdc.load_engine())
    assert not report.changed, (
        f"item penetration value drift vs DDragon {_current_patch()}: {report.changed}. "
        "Re-pin agents/daemon_slayer/_effects_data.py in this commit."
    )
    assert not report.added and not report.removed, (
        f"item penetration id/axis drift vs DDragon {_current_patch()}: "
        f"added={report.added} removed={report.removed}"
    )
    assert not report.stale_allowlist, (
        f"PASSIVE_SOURCED rows no longer passive-only: {report.stale_allowlist}"
    )


def test_drift_check_default_tracks_current_patch() -> None:
    resolved = pdc._default_item_json()
    assert _current_patch() in str(resolved), (
        f"pen drift-check default {resolved} does not track current.txt"
    )
    assert resolved.exists(), f"resolved default item.json missing: {resolved}"


def test_live_catalog_every_pen_line_is_classified() -> None:
    cls = pdc.classify_ddragon(_live_item_json())
    assert cls.unparsed == [], f"pen lines no axis parses: {cls.unparsed}"
    # Non-vacuity: the live catalog states all four axes on buyable items.
    axes = {axis for row in cls.buyable.values() for axis in row}
    assert axes == set(pdc.AXES), f"live catalog axes {sorted(axes)}"
    assert len(cls.buyable) >= 40, f"only {len(cls.buyable)} buyable pen items parsed"


def test_bastionbreaker_is_parsed_from_its_own_stats_line() -> None:
    # The motivating row: read from DDragon, so this follows the data, not 22.
    cls = pdc.classify_ddragon(_live_item_json())
    assert "lethality" in cls.buyable["2520"]
    assert ITEM_EFFECTS["2520"].lethality == cls.buyable["2520"]["lethality"]


# --- synthetic coverage (no live data) ---------------------------------------

def _fixture(tmp_path: Path, rows: dict[str, str]) -> Path:
    blob = {
        "version": "0.0.0",
        "data": {i: {"name": f"item{i}", "description": d} for i, d in rows.items()},
    }
    p = tmp_path / "item.json"
    p.write_text(json.dumps(blob), encoding="utf-8")
    return p


def _stats(*lines: str) -> str:
    return "<mainText><stats>" + "<br>".join(lines) + "</stats></mainText>"


_LETH = "<attention>18</attention> Lethality"
_PCT_ARP = "<attention>35%</attention> Armor Penetration"
_FLAT_MP = "<attention>15</attention> Magic Penetration"
_PCT_MP = "<attention>40%</attention> Magic Penetration"


def test_all_four_axes_parse_and_percent_is_a_fraction(tmp_path: Path) -> None:
    p = _fixture(tmp_path, {"1": _stats(_LETH, _PCT_ARP), "2": _stats(_FLAT_MP, _PCT_MP)})
    cls = pdc.classify_ddragon(p)
    assert cls.buyable == {
        "1": {"lethality": 18.0, "armor_pen_pct": 0.35},
        "2": {"magic_pen_flat": 15.0, "magic_pen_pct": 0.40},
    }


def test_ornn_bonus_pen_is_classified_not_buyable(tmp_path: Path) -> None:
    ornn = "<mainText><stats><ornnBonus>20</ornnBonus> Lethality</stats></mainText>"
    cls = pdc.classify_ddragon(_fixture(tmp_path, {"228003": ornn}))
    assert cls.ornn == {"228003": {"lethality": 20.0}}
    assert cls.buyable == {} and cls.unparsed == []


def test_throwback_band_is_excluded(tmp_path: Path) -> None:
    cls = pdc.classify_ddragon(_fixture(tmp_path, {"773020": _stats(_FLAT_MP)}))
    assert cls.buyable == {} and cls.band_skipped == ["773020"]


def test_unknown_pen_line_surfaces_as_unparsed(tmp_path: Path) -> None:
    odd = _stats("<rarityMythic>9</rarityMythic> Lethality")
    cls = pdc.classify_ddragon(_fixture(tmp_path, {"9999": odd}))
    assert cls.unparsed == ["9999"]


def test_diff_reports_value_drift_and_missing_axes() -> None:
    cls = pdc.PenClassification(buyable={"1": {"lethality": 18.0}, "2": {"magic_pen_flat": 12.0}})
    engine = {"1": {"lethality": 22.0}, "3": {"armor_pen_pct": 0.3}}
    rep = pdc.diff(cls, engine, passive_sourced={})
    assert rep.changed == {("1", "lethality"): (22.0, 18.0)}
    assert rep.added == [("2", "magic_pen_flat")]
    assert rep.removed == [("3", "armor_pen_pct")]


def test_passive_sourced_rows_are_exempt_but_cannot_rot() -> None:
    engine = {"3302": {"armor_pen_pct": 0.3}}
    clean = pdc.diff(pdc.PenClassification(), engine, passive_sourced={"3302": "why"})
    assert clean.removed == [] and clean.stale_allowlist == []
    # The exemption rots if DDragon starts stating the axis, or the engine drops it.
    stated = pdc.PenClassification(buyable={"3302": {"armor_pen_pct": 0.3}})
    assert pdc.diff(stated, engine, passive_sourced={"3302": "why"}).stale_allowlist == ["3302"]
    assert pdc.diff(pdc.PenClassification(), {}, passive_sourced={"3302": "why"}).stale_allowlist == ["3302"]


def test_main_exit_codes(tmp_path: Path, monkeypatch, capsys) -> None:
    p = _fixture(tmp_path, {"1": _stats(_LETH)})
    monkeypatch.setattr(pdc, "load_engine", lambda: {"1": {"lethality": 18.0}})
    monkeypatch.setattr(pdc, "PASSIVE_SOURCED", {})
    monkeypatch.setattr("sys.argv", ["item_pen_drift_check.py", str(p)])
    assert pdc.main() == 0
    monkeypatch.setattr(pdc, "load_engine", lambda: {"1": {"lethality": 22.0}})
    assert pdc.main() == 1
    assert "CHANGED" in capsys.readouterr().out
    monkeypatch.setattr("sys.argv", ["item_pen_drift_check.py", str(tmp_path / "nope.json")])
    assert pdc.main() == 2
