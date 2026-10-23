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
  4. RM-806: the resist-reduction fields (``armor_reduction_pct`` /
     ``armor_reduction_flat`` / ``mr_reduction_pct`` / ``mr_reduction_flat``,
     7 engine rows) are diffed against their DDragon PASSIVE prose (per-stack
     magnitude x stack count), and the Terminus ``PASSIVE_SOURCED`` exemption
     covers only its two passive pen axes, so drift on any other Terminus axis
     is still reported.

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


# The four ItemEffect resist-reduction fields (agents/daemon_slayer/effects.py),
# named here independently of the checker so the spec does not grade itself.
_REDUCTION_FIELDS = (
    "armor_reduction_pct", "armor_reduction_flat", "mr_reduction_pct", "mr_reduction_flat",
)


def _engine_reduction_rows() -> dict[str, dict[str, float]]:
    """Non-zero resist-reduction fields per ITEM_EFFECTS row, read directly."""
    out: dict[str, dict[str, float]] = {}
    for iid, eff in ITEM_EFFECTS.items():
        row = {f: float(getattr(eff, f, 0.0) or 0.0) for f in _REDUCTION_FIELDS}
        row = {f: v for f, v in row.items() if v}
        if row:
            out[str(iid)] = row
    return out


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
    assert cls.unparsed == [], f"pen / reduction lines no axis parses: {cls.unparsed}"
    # Non-vacuity: the live catalog states all four <stats> pen axes and all
    # four passive resist-reduction axes on buyable items.
    axes = {axis for row in cls.buyable.values() for axis in row}
    assert axes == set(pdc.AXES) | set(_REDUCTION_FIELDS), f"live catalog axes {sorted(axes)}"
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
    key = ("3302", "armor_pen_pct")
    engine = {"3302": {"armor_pen_pct": 0.3}}
    clean = pdc.diff(pdc.PenClassification(), engine, passive_sourced={key: "why"})
    assert clean.removed == [] and clean.stale_allowlist == []
    # The exemption rots if DDragon starts stating the axis, or the engine drops it.
    stated = pdc.PenClassification(buyable={"3302": {"armor_pen_pct": 0.3}})
    assert pdc.diff(stated, engine, passive_sourced={key: "why"}).stale_allowlist == [key]
    assert pdc.diff(pdc.PenClassification(), {}, passive_sourced={key: "why"}).stale_allowlist == [key]


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


# --- RM-806 (a): passive resist-reduction rows ------------------------------
#
# Resist reduction is not a <stats> magnitude: DDragon states it in the
# passive prose as a per-stack value and a stack count, and the engine credits
# the full-stack steady state (per-stack x stacks; Black Cleaver convention).
# The prose templates below are the DDragon 16.21.1 shapes, with the
# magnitude and stack count as parameters.

_CARVE = (
    "<passive>Carve</passive><br>Dealing <physicalDamage>physical damage</physicalDamage> "
    "to champions reduces the target's <scaleArmor>Armor by {n}%</scaleArmor> for 6 "
    "seconds. (stacks {k} times)."
)
_VILE = (
    "<passive>Vile Decay</passive><br>Dealing <magicDamage>magic damage</magicDamage> with "
    "abilities or passives to champions reduces their <scaleMR>Magic Resist by {n}%</scaleMR> "
    "for 6 seconds. (Stacks {k} times)."
)
_HACK = (
    "<passive>Hack the Meat</passive><br>Dealing damage shreds {n} <scaleArmor>Armor"
    "</scaleArmor> and <scaleMR>Magic Resist</scaleMR> for 5 seconds, stacking up to {k} "
    "times. Applying stacks has a 1 second cooldown per Ability."
)

# The 7 engine rows RM-806 measured (9 field assignments), each with its
# 16.21.1 passive template, its in-sync (per-stack, stacks), and the
# <stats> tag its description uses (228005 is an Ornn masterwork).
_RM806_ROWS = {
    "3071": (_CARVE, 6, 5, "attention"),      # Black Cleaver
    "223071": (_CARVE, 6, 5, "attention"),    # Black Cleaver (Arena)
    "228005": (_CARVE, 6, 5, "ornnBonus"),    # Obsidian Cleaver (Ornn)
    "8010": (_VILE, 7.5, 4, "attention"),     # Bloodletter's Curse (SR)
    "4010": (_VILE, 7.5, 4, "attention"),     # Bloodletter's Curse
    "667112": (_HACK, 3, 10, "attention"),    # Flesheater
    "447112": (_HACK, 3, 10, "attention"),    # Flesheater (Arena)
}


def _passive_item(template: str, n: float, k: int, tag: str = "attention") -> str:
    stats = f"<stats><{tag}>45</{tag}> Attack Damage<br><{tag}>400</{tag}> Health</stats>"
    return f"<mainText>{stats}<br><br>{template.format(n=n, k=k)}</mainText>"


def test_engine_reduction_rows_are_the_measured_seven() -> None:
    rows = _engine_reduction_rows()
    assert set(_RM806_ROWS) <= set(rows), f"engine reduction rows {sorted(rows)}"
    assert sum(len(r) for r in rows.values()) >= 9, rows


def test_load_engine_reads_every_reduction_field() -> None:
    engine = pdc.load_engine()
    for iid, row in _engine_reduction_rows().items():
        for f, v in row.items():
            assert engine.get(iid, {}).get(f) == v, (
                f"{iid} {f}: load_engine does not carry the engine's {v}"
            )


def test_reduction_passive_parses_to_the_full_stack_value(tmp_path: Path) -> None:
    rows = {iid: _passive_item(t, n, k, tag) for iid, (t, n, k, tag) in _RM806_ROWS.items()}
    cls = pdc.classify_ddragon(_fixture(tmp_path, rows))
    assert cls.unparsed == []
    stated = {**cls.buyable, **cls.ornn}
    assert stated["3071"] == {"armor_reduction_pct": 0.30}
    assert stated["8010"] == {"mr_reduction_pct": 0.30}
    assert stated["667112"] == {"armor_reduction_flat": 30.0, "mr_reduction_flat": 30.0}
    assert "228005" in cls.ornn and "228005" not in cls.buyable


def test_reduction_rows_in_sync_with_their_passive_report_no_drift(tmp_path: Path) -> None:
    engine = _engine_reduction_rows()
    rows = {iid: _passive_item(t, n, k, tag) for iid, (t, n, k, tag) in _RM806_ROWS.items()}
    rep = pdc.diff(pdc.classify_ddragon(_fixture(tmp_path, rows)),
                   {i: engine[i] for i in _RM806_ROWS}, passive_sourced={})
    assert not rep.drift, (rep.changed, rep.added, rep.removed, rep.stale_allowlist)


def test_reduction_magnitude_drift_is_reported_on_each_of_the_seven(tmp_path: Path) -> None:
    engine = {i: r for i, r in _engine_reduction_rows().items() if i in _RM806_ROWS}
    assert len(engine) == 7 and sum(len(r) for r in engine.values()) == 9
    # Each row's per-stack magnitude moves by +1 in DDragon; the engine stays.
    rows = {iid: _passive_item(t, n + 1, k, tag) for iid, (t, n, k, tag) in _RM806_ROWS.items()}
    rep = pdc.diff(pdc.classify_ddragon(_fixture(tmp_path, rows)), engine, passive_sourced={})
    expected = {}
    for iid, (_t, n, k, _tag) in _RM806_ROWS.items():
        for f, v in engine[iid].items():
            want = (n + 1) * k / 100.0 if f.endswith("_pct") else float((n + 1) * k)
            expected[(iid, f)] = (v, want)
    assert set(rep.changed) == set(expected), sorted(rep.changed)
    for key, (en, dd) in expected.items():
        assert rep.changed[key][0] == en and abs(rep.changed[key][1] - dd) < 1e-9, key
    assert rep.added == [] and rep.removed == []


def test_reduction_stack_count_drift_is_reported(tmp_path: Path) -> None:
    p = _fixture(tmp_path, {"4010": _passive_item(_VILE, 7.5, 5)})
    rep = pdc.diff(pdc.classify_ddragon(p), {"4010": {"mr_reduction_pct": 0.30}}, passive_sourced={})
    assert set(rep.changed) == {("4010", "mr_reduction_pct")}
    assert abs(rep.changed[("4010", "mr_reduction_pct")][1] - 0.375) < 1e-9


def test_reduction_dropped_from_prose_or_newly_stated_is_reported(tmp_path: Path) -> None:
    plain = "<mainText><stats><attention>45</attention> Attack Damage</stats></mainText>"
    p = _fixture(tmp_path, {"3071": plain, "9001": _passive_item(_CARVE, 6, 5)})
    rep = pdc.diff(pdc.classify_ddragon(p), {"3071": {"armor_reduction_pct": 0.30}},
                   passive_sourced={})
    assert rep.removed == [("3071", "armor_reduction_pct")]
    assert rep.added == [("9001", "armor_reduction_pct")]


def test_reduction_prose_shapes_are_classified_never_skipped(tmp_path: Path) -> None:
    rows = {
        # Malignance 16.21.1: a reduction with NO magnitude in the prose.
        "3118": ("<mainText><stats><attention>90</attention> Ability Power</stats><br><br>"
                 "<passive>Hatefog</passive><br>Damaging a champion with your Ultimate burns "
                 "the ground beneath them for 3s, dealing <magicDamage>magic damage</magicDamage> "
                 "per second and reducing their <scaleMR>Magic Resist</scaleMR>. <br></mainText>"),
        # A number-bearing reduction no shape understands must FAIL (unparsed).
        "9002": ("<mainText><stats><attention>40</attention> Ability Power</stats><br><br>"
                 "<passive>Despair</passive><br>Reduces the <scaleMR>Magic Resist</scaleMR> of "
                 "nearby enemies by <scaleMR>20</scaleMR></mainText>"),
        # Self buffs naming a resist are not reductions.
        "6665": ("<mainText><stats><attention>400</attention> Health</stats><br><br>"
                 "<passive>Voidborn Resilience</passive><br>After 5 seconds of champion combat, "
                 "increase your bonus <scaleArmor>Armor</scaleArmor> and <scaleMR>Magic Resist"
                 "</scaleMR> by 30% until end of combat.<br><br></mainText>"),
        "443059": ("<mainText><stats><attention>400</attention> Health</stats><br><br>"
                   "<passive>Limitless as the Stars</passive><br>Increase your <scaleMR>Magic "
                   "Resist</scaleMR> by 20%. Reduce all damage you take from non-Basic Attack "
                   "sources by a percentage, scaling with your <scaleMR>Magic Resist</scaleMR> "
                   "up to 20%.</mainText>"),
    }
    cls = pdc.classify_ddragon(_fixture(tmp_path, rows))
    assert cls.unparsed == ["9002"]
    assert cls.reduction_unstated == ["3118"]
    assert cls.buyable == {} and cls.ornn == {}
    # An engine reduction on an item whose prose states no magnitude is drift.
    rep = pdc.diff(cls, {"3118": {"mr_reduction_flat": 10.0}}, passive_sourced={})
    assert rep.removed == [("3118", "mr_reduction_flat")]


def test_live_reduction_rows_are_parsed_from_their_own_passive() -> None:
    cls = pdc.classify_ddragon(_live_item_json())
    stated = {**cls.buyable, **cls.ornn}
    for iid, row in _engine_reduction_rows().items():
        for f, v in row.items():
            assert iid in stated and f in stated[iid], f"{iid} {f}: no DDragon passive parse"
            assert abs(stated[iid][f] - v) < 1e-9, f"{iid} {f}: engine {v} vs DDragon {stated[iid][f]}"


# --- RM-806 (b): the Terminus exemption is per axis --------------------------

_TERMINUS_AXES = {
    ("3302", "armor_pen_pct"), ("3302", "magic_pen_pct"),
    ("223302", "armor_pen_pct"), ("223302", "magic_pen_pct"),
}


def test_terminus_exemption_names_only_its_passive_pen_axes() -> None:
    assert set(pdc.PASSIVE_SOURCED) == _TERMINUS_AXES
    assert all(reason.strip() for reason in pdc.PASSIVE_SOURCED.values())


def test_terminus_exemption_does_not_hide_drift_on_another_axis() -> None:
    full = {"armor_pen_pct": 0.3, "magic_pen_pct": 0.3}
    arena = {"armor_pen_pct": 0.24, "magic_pen_pct": 0.24}
    # Engine credits an extra axis DDragon never states -> REMOVED.
    rep = pdc.diff(pdc.PenClassification(),
                   {"3302": {**full, "lethality": 10.0}, "223302": {**arena, "armor_reduction_pct": 0.1}})
    assert rep.removed == [("3302", "lethality"), ("223302", "armor_reduction_pct")]
    assert rep.stale_allowlist == []
    # DDragon <stats> states a new axis the engine does not credit -> ADDED.
    rep = pdc.diff(pdc.PenClassification(buyable={"3302": {"magic_pen_flat": 12.0}}),
                   {"3302": full, "223302": arena})
    assert rep.added == [("3302", "magic_pen_flat")]
    assert rep.stale_allowlist == []
    # A value drift on a non-exempt axis -> CHANGED.
    rep = pdc.diff(pdc.PenClassification(buyable={"223302": {"lethality": 12.0}}),
                   {"3302": full, "223302": {**arena, "lethality": 10.0}})
    assert rep.changed == {("223302", "lethality"): (10.0, 12.0)}


def test_terminus_exemption_rots_per_axis() -> None:
    full = {"armor_pen_pct": 0.3, "magic_pen_pct": 0.3}
    arena = {"armor_pen_pct": 0.24, "magic_pen_pct": 0.24}
    # DDragon starts stating one exempt axis in <stats>: only that axis is stale.
    rep = pdc.diff(pdc.PenClassification(buyable={"3302": {"armor_pen_pct": 0.3}}),
                   {"3302": full, "223302": arena})
    assert rep.stale_allowlist == [("3302", "armor_pen_pct")]
    # The engine stops crediting one exempt axis: only that axis is stale.
    rep = pdc.diff(pdc.PenClassification(), {"3302": full, "223302": {"armor_pen_pct": 0.24}})
    assert rep.stale_allowlist == [("223302", "magic_pen_pct")]
