"""Hermetic smoke coverage for tools/repo_insights.py (the grounded /insights variant).

Structural-invariant tests only (no data-fragile numeric assertions): the render
must be ASCII + carry every section header; the helpers must behave; build_facts
must return the documented shape. The synthetic-facts render path is fully
hermetic; the build_facts smoke runs git on the real repo over a 1-day window and
degrades to key-presence assertions when there is no commit in range.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
_SPEC = importlib.util.spec_from_file_location(
    "repo_insights", ROOT / "tools" / "repo_insights.py"
)
ri = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(ri)


def _synthetic_facts() -> dict:
    return {
        "generated": "2026-06-17 19:00",
        "engine_version": "1.140.0",
        "ds_patch": "16.12.1",
        "git": {
            "days": 30,
            "window_start": "2026-05-18",
            "window_end": "2026-06-17",
            "commits": 1475,
            "active_days": 31,
            "commits_per_active_day": 47.6,
            "churn_total": [2602433, 697329],
            "churn_source": [558359, 72324],
            "types": [["docs", 482], ["feat", 403], ["fix", 131]],
            "dirs": [["agents", 6397], ["tools", 4707], ["docs", 825]],
            "authors": [["Moonbeam", 1468]],
            "files_touched": 2996,
        },
        "ledger": {
            "latest_item": 488,
            "items_in_window": [[488, "2026-06-17", "live-session prep batch"]],
            "count_in_window": 163,
            "friction": {"SEQUENCING": 35, "verify-before-redo": 24, "zero-signal": 0},
        },
        "orchestration": {"status": {"DONE": 68, "CLOSED": 1}, "excluded": ["Phase-D flips"]},
        "roadmap_open": [],
    }


def test_render_html_is_ascii():
    out = ri.render_html(_synthetic_facts())
    offenders = [b for b in out.encode("utf-8") if b > 0x7F]
    assert not offenders, f"non-ASCII byte(s) in rendered report: {offenders[:5]}"


def test_render_html_has_every_section():
    out = ri.render_html(_synthetic_facts())
    for marker in (
        "<!DOCTYPE html>",
        "Amberstone - Repo Insights",
        "What You Worked On",
        "What Shipped",
        "What's Working",
        "Where Friction Showed Up",
        "On the Horizon",
    ):
        assert marker in out, f"missing section/marker: {marker!r}"


def test_render_drops_zero_friction_rows():
    # The zero-count friction key must not surface; the non-zero ones must.
    out = ri.render_html(_synthetic_facts())
    assert "zero-signal" not in out
    assert "SEQUENCING" in out


def test_short_truncates_and_stays_ascii():
    long = "x" * 500
    s = ri._short(long, limit=140)
    assert len(s) <= 143  # limit + "..."
    assert s.endswith("...")
    assert all(ord(c) < 0x80 for c in s)


def test_short_strips_commit_tail():
    assert ri._short("Did a thing (commit abc1234; Tier-2)") == "Did a thing"


def test_area_name_maps_and_passes_through():
    assert ri.area_name("agents") == "Daemon Slayer engine"
    assert ri.area_name("totally_unknown_dir") == "totally_unknown_dir"


def test_build_facts_shape():
    facts = ri.build_facts(days=1, author=None)
    for key in ("generated", "engine_version", "ds_patch", "git", "ledger",
                "orchestration", "roadmap_open"):
        assert key in facts, f"facts missing top-level key {key!r}"
    for key in ("commits", "types", "dirs", "churn_total", "active_days"):
        assert key in facts["git"], f"git facts missing {key!r}"
    # engine version is read from the live source - must be a dotted string
    assert facts["engine_version"].count(".") >= 1 or facts["engine_version"] == "?"


def test_render_from_real_build_facts_is_ascii():
    # End-to-end: real repo facts (1-day window) render to valid ASCII HTML.
    out = ri.render_html(ri.build_facts(days=1, author=None))
    assert out.startswith("<!DOCTYPE html>")
    assert not [b for b in out.encode("utf-8") if b > 0x7F]
