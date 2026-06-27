# arch: tests for loop_controller director continuity digest | section=tests | frozen=no
"""Regression guard for the gemini-headless DIRECTOR re-issuing completed work.

ROOT CAUSE (caught 2026-06-27): docs/LEDGER.md is append-only NEWEST-FIRST (new
items go at the TOP). The old director() fed the model `tail('docs/LEDGER.md',90)`
- i.e. the LAST 90 lines = the OLDEST entries (items ~325 from 2026-06-06) - so
the genuinely-recent completed items (618-633) were INVISIBLE to the director and
it re-proposed already-shipped work (git history: R28 "CLEAN no-op - directive
premises already shipped 618/619/620", commits e24410d6 / b951f985).

The fix gives the director an explicit ALREADY-COMPLETED DIGEST built from:
  - recent commits (newest first),
  - the NEWEST docs/LEDGER.md items (head, not tail), and
  - the directive chain already issued this run (persisted to disk),
plus an explicit BUILD-ON / de-dup instruction. These tests pin all three.

Loaded by file path so the module's argv-driven CFG load needs no real launch
(the .json-suffix guard makes import-under-pytest fall back to the real config).
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

_CTRL = Path(__file__).resolve().parent.parent / "ops" / "loop" / "loop_controller.py"


@pytest.fixture(scope="module")
def lc():
    spec = importlib.util.spec_from_file_location("loop_controller_uut_continuity", _CTRL)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _seed_repo(root: Path) -> None:
    """A minimal newest-first LEDGER + plan + roadmap fixture under `root`."""
    (root / "docs").mkdir(parents=True, exist_ok=True)
    # Newest-first ledger: item 999 NEWEST at the TOP, item 001 OLDEST at the
    # bottom, padded past the head window so a tail() read would miss the newest.
    lines = ["# Ledger", "", "Append each new item at the TOP (newest-first).", "", "---", ""]
    lines.append("999. DONE NEWEST_MARKER capability-gap consumer slice 3")
    lines.append("")
    for i in range(998, 1, -1):
        lines.append(f"{i:03d}. DONE filler item {i}")
        lines.append("")
    lines.append("001. DONE OLDEST_MARKER very first item")
    (root / "docs" / "LEDGER.md").write_text("\n".join(lines), encoding="utf-8")
    (root / "docs" / "ORCHESTRATION_PLAN.md").write_text(
        "# Plan\n\n| id | Status |\n| A1 | DONE |\n", encoding="utf-8")
    # ROADMAP is high-priority-at-TOP and longer than the head window, so a tail
    # read would drop the top (current) items - the same inversion as LEDGER.
    rm = ["# Roadmap", "", "## Open items - High priority", "",
          "- TOP_ROADMAP_MARKER highest-priority open item", ""]
    rm += [f"- filler roadmap line {i}" for i in range(140)]
    rm.append("- BOTTOM_ROADMAP_MARKER oldest / lowest priority")
    (root / "ROADMAP.md").write_text("\n".join(rm), encoding="utf-8")


# --- the head/tail-inversion root cause -------------------------------------

def test_head_lines_reads_newest_first_head(lc, tmp_path):
    _seed_repo(tmp_path)
    digest = lc.head_lines("docs/LEDGER.md", 12, root=tmp_path)
    assert "NEWEST_MARKER" in digest, "head_lines must surface the newest (top) ledger item"
    assert "OLDEST_MARKER" not in digest, "head_lines must NOT reach the oldest (tail) item"


def test_director_context_surfaces_newest_not_oldest_ledger(lc, tmp_path):
    """The regression: the digest the director sees must contain the NEWEST
    completed item, never only the stale oldest one (the tail() bug)."""
    _seed_repo(tmp_path)
    ctx = lc.build_director_context({}, "", root=tmp_path, ctl=tmp_path)
    assert "NEWEST_MARKER" in ctx
    assert "OLDEST_MARKER" not in ctx


def test_director_context_reads_roadmap_top_not_bottom(lc, tmp_path):
    """Sibling of the LEDGER fix: ROADMAP.md is high-priority-at-top, so the
    director context must surface the TOP (head), not the stale bottom (tail)."""
    _seed_repo(tmp_path)
    ctx = lc.build_director_context({}, "", root=tmp_path, ctl=tmp_path)
    assert "TOP_ROADMAP_MARKER" in ctx
    assert "BOTTOM_ROADMAP_MARKER" not in ctx


# --- explicit BUILD-ON / de-dup instruction ---------------------------------

def test_director_context_has_completed_digest_and_dedup_rule(lc, tmp_path):
    _seed_repo(tmp_path)
    ctx = lc.build_director_context({}, "", root=tmp_path, ctl=tmp_path)
    up = ctx.upper()
    assert "ALREADY-COMPLETED DIGEST" in up
    assert "DE-DUP" in up or "DO NOT RE-ISSUE" in up
    assert "BUILD ON" in up


# --- directive-chain persistence + round-trip -------------------------------

def test_directive_title_extracts_theme_scope(lc):
    body = ("DECISION: x.\n\nTHEME: lift\nSCOPE: Aggregator S competitor teardown -> "
            "docs/COMPETITOR_LIFT.md\n\nINSTRUCTIONS:\n1. ...")
    title = lc.directive_title(body)
    assert "lift" in title.lower()
    assert "aggregator S" in title.lower()


def test_record_and_read_directive_history_roundtrip(lc, tmp_path):
    assert lc.read_directive_history(5, ctl=tmp_path) == []
    lc.record_directive_outcome(
        1, "THEME: lift\nSCOPE: alpha unit", "aaaaaaaa", "bbbbbbbb",
        {"tests_pass": 6900, "regressions": False}, "VERDICT: CLEAN", ctl=tmp_path)
    recs = lc.read_directive_history(5, ctl=tmp_path)
    assert len(recs) == 1
    assert recs[0]["cycle"] == 1
    assert recs[0]["sha_after"] == "bbbbbbbb"
    assert "alpha" in recs[0]["title"].lower()


# --- the >=2-cycle proof: a directive issued in cycle 1 is visible in cycle 2 -

def test_two_cycle_continuity_prevents_reissue(lc, tmp_path):
    """Across two simulated cycles the unit issued in cycle 1 must appear in the
    cycle-2 director context (the de-dup INPUT), so the director can BUILD ON it
    instead of re-issuing it. Old code had NO directive chain at all."""
    _seed_repo(tmp_path)
    # cycle 1 ships a distinctive unit
    lc.record_directive_outcome(
        1, "THEME: lift\nSCOPE: ZZUNIQUEMARKER teardown of competitor X",
        "1111aaaa", "2222bbbb", {"tests_pass": 6901, "regressions": False},
        "VERDICT: CLEAN", ctl=tmp_path)
    # cycle 2 context is assembled
    ctx2 = lc.build_director_context(
        {"tests_pass": 6901, "regressions": False}, "VERDICT: CLEAN",
        root=tmp_path, ctl=tmp_path)
    assert "DIRECTIVES ALREADY ISSUED" in ctx2.upper()
    assert "ZZUNIQUEMARKER" in ctx2, "cycle-1 issued unit must be visible in cycle-2 context"
    assert "2222bbbb" in ctx2, "the resulting sha of the prior directive must be shown"
