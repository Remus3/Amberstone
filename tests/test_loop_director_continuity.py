# arch: tests for loop_controller director continuity digest | section=tests | frozen=no
"""Regression guard for the gemini-headless DIRECTOR re-issuing completed work.

ROOT CAUSE (caught 2026-06-27): docs/LEDGER.md is append-only NEWEST-FIRST (new
items go at the TOP). The old director() fed the model `tail('docs/LEDGER.md',90)`
- i.e. the LAST 90 lines = the OLDEST entries (items ~325 from 2026-06-06) - so
the genuinely-recent completed items (618-633) were INVISIBLE to the director and
it re-proposed already-shipped work (git history: R28 "CLEAN no-op - directive
premises already shipped 618/619/620", commits aa80b896 / 6a13dc93).

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
    assert "aggregator s" in title.lower()


# --- the chain is only a de-dup input if its titles NAME WORK ---------------
#
# SECOND DEFECT (2026-07-27). ops/loop/director_prompt.md:16-18 mandates a
# three-line GROUNDING PREFIX as the directive's FIRST lines, and never
# requires THEME / SCOPE. directive_title fell through to "the first non-empty
# line", so 181 of the 199 records in the live control/directive_history.jsonl
# are titled "GROUNDED-AGAINST: HEAD=<sha> LEDGER-TOP=<n> CHAIN-LAST=<n>" -
# which names no work at all. The chain was fed to the director and carried
# zero information, so it could not refute a duplicate.

_LIVE_SHAPED_BODY = (
    "GROUNDED-AGAINST: HEAD=f173ce39 LEDGER-TOP=1074 CHAIN-LAST=cycle 4\n"
    "NOT-A-DUPLICATE-OF: LEDGER 1074 | distinct because this is items 1, 9 and 5a\n"
    "PREMISE-CHECK: [from-digest] items 2 and 5 shipped in f173ce39\n"
    "\n"
    "ENGINE-IMPACT: NONE\n"
    "ops sync and tests only, no ds path.\n"
    "\n"
    "DIRECTIVE: f1-phase6 inbox apply and githooks mode commit\n"
    "\n"
    "1. STEP A: run `git diff --cached`.\n"
)


def test_directive_title_skips_the_grounding_prefix(lc):
    """The exact live body that produced the duplicate directive. Its title
    must name the unit, not the grounding line every directive carries."""
    title = lc.directive_title(_LIVE_SHAPED_BODY)
    assert not title.upper().startswith("GROUNDED-AGAINST"), (
        f"title is still the grounding prefix: {title!r}"
    )
    assert "f1-phase6" in title, f"title does not name the work: {title!r}"


def test_directive_title_skips_every_metadata_prefix(lc):
    """Class guard over the whole mandated prefix block, not just line 1: a
    body carrying ONLY metadata plus one prose line must title on the prose."""
    for prefix in lc.DIRECTIVE_METADATA_PREFIXES:
        body = f"{prefix} some machine-readable value\nreal work sentence here\n"
        title = lc.directive_title(body)
        assert title == "real work sentence here", (
            f"prefix {prefix!r} was not skipped - got {title!r}"
        )


def test_directive_title_prefers_the_directive_line_over_stray_prose(lc):
    """`DIRECTIVE:` is the emitted title line; the prose above it ("ops sync
    and tests only") is an ENGINE-IMPACT qualifier and is the wrong label.
    Asserted as an EQUALITY - a not-in check passes vacuously while the title
    is still the untouched grounding prefix."""
    assert lc.directive_title(_LIVE_SHAPED_BODY) == (
        "f1-phase6 inbox apply and githooks mode commit"
    )


def test_directive_title_survives_a_metadata_only_body(lc):
    """A body with nothing but the grounding prefix has no work to name - it
    must degrade to a label, never to an empty string or an IndexError."""
    body = "GROUNDED-AGAINST: HEAD=abc12345 LEDGER-TOP=1074 CHAIN-LAST=cycle 4\n"
    assert lc.directive_title(body).strip(), "empty title for a metadata-only body"


def test_chain_digest_names_work_not_grounding(lc, tmp_path):
    """End to end: record a live-shaped directive, then assert the cycle-N+1
    context shows the UNIT. This is the whole point of the chain."""
    _seed_repo(tmp_path)
    # A marker that cannot appear in the real `git log --oneline` block the
    # context also embeds - "f1-phase6" is in this repo's history and would
    # make this assertion pass while the chain stayed empty of work names.
    body = _LIVE_SHAPED_BODY.replace(
        "f1-phase6 inbox apply", "QQCHAINUNITMARKER inbox apply")
    lc.record_directive_outcome(
        9, body, "1111aaaa", "80bb813f",
        {"tests_pass": 13516, "regressions": False}, "VERDICT: CLEAN", ctl=tmp_path)
    ctx = lc.build_director_context({}, "", root=tmp_path, ctl=tmp_path)
    assert "QQCHAINUNITMARKER" in ctx, (
        "the directive chain must name the unit issued in the prior cycle - "
        "a chain of GROUNDED-AGAINST lines cannot refute a duplicate"
    )


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
