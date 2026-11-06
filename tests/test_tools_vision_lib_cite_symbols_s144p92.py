"""RM-1363: ten more modules cite their neighbours by symbol.

hz_mismatch_diagnose, sibling_sweep_ci, vision_server _http, replay_chain_watch,
regen_arena_laning_table, live_write_tracer, gated_live_probe, the scraper base,
hz_shadow_arena_contamination and screen_agent carried `<file>.py:<line>`
anchors that had drifted: `laning_scenario_precompute.py:355` is a
`load_build_orders` signature, not the enemy combo, `ci_watchdog.py:315-317` is
a command-plan docstring, `sibling_name_sweep.py:344` a dataclass field. The
prose now names the symbol; this guard keeps it that way and pins that every
cited symbol still exists. Port numbers such as `:8889` are not line cites and
are left alone.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
MODULES = (
    "tools/hz_mismatch_diagnose.py",
    "tools/sibling_sweep_ci.py",
    "vision_server/_http.py",
    "tools/replay_chain_watch.py",
    "tools/regen_arena_laning_table.py",
    "tools/live_write_tracer.py",
    "tools/gated_live_probe.py",
    "lib/scrapers/_base.py",
    "tools/hz_shadow_arena_contamination.py",
    "tools/screen_agent.py",
)

_LINE_CITE = re.compile(r"[A-Za-z0-9_/.]+\.(?:py|js|css|json):\d+")


@pytest.mark.parametrize("rel", MODULES)
def test_module_cites_no_file_line_numbers(rel):
    text = (ROOT / rel).read_text(encoding="utf-8")
    assert _LINE_CITE.findall(text) == [], "cite a symbol, not a line number"


def test_line_cite_pattern_catches_the_old_forms():
    for old in (
        "_TRADE nudge in core/precomputed_laning_coach.py:79-81 ONLY WITH",
        "assumption (core/laning_scenario_precompute.py:355): the",
        "absent (sibling_name_sweep.py:344). ``_run_scan``",
        "(sibling_name_sweep.py:1098-1100). So the",
        "Containment copied from dashboard/routes_static.py:64-67",
        "same reason as tools/ci_watchdog.py:315-317.",
        "``atomic_write`` at ``core/laning_scenario_precompute.py:909``,",
        "(ops/loop/slots.py:39 DEFAULT_ROOT's parent)",
        "`modes/shared_vision.py:25` +",
        "``agents/agent2_backend/pipeline/orchestrator.py:149`` and",
        "fallback, core/precomputed_laning_coach.py:511)",
        "# Precedent: tools/liveclient_relay.py:41-51.",
    ):
        assert _LINE_CITE.search(old), old
    assert _LINE_CITE.search("relay on :8889 by modes/shared_vision.py") is None


@pytest.mark.parametrize(
    "rel, needle",
    [
        ("core/precomputed_laning_coach.py", "_BACK_OFF: float"),
        ("core/precomputed_laning_coach.py", "def _resolve_cell_ctx("),
        ("core/laning_scenario_precompute.py", "_FULL_COMBO: Tuple"),
        ("core/laning_scenario_precompute.py", "def atomic_write("),
        ("core/laning_scenario_precompute.py", 'f"laning_scenarios_{mode_key}.json"'),
        ("tools/sibling_name_sweep.py", "def load_config("),
        ("tools/sibling_name_sweep.py", "def _run_scan("),
        ("tools/sibling_name_sweep.py", "assert_non_vacuous(needles)"),
        ("dashboard/routes_static.py", "def _serve_web_asset("),
        ("dashboard/routes_static.py", "abs_path.relative_to(web_root)"),
        ("tools/ci_watchdog.py", "def _run("),
        ("tools/ci_watchdog.py", "no_window = 0x08000000"),
        ("ops/loop/slots.py", "DEFAULT_ROOT ="),
        ("modes/shared_vision.py", "_VISION_SERVER ="),
        ("modes/shared_vision.py", "def _capture_screen("),
        ("agents/agent2_backend/pipeline/orchestrator.py", "def _scrape_one("),
        ("tools/liveclient_relay.py", "class _LFFileHandler(logging.FileHandler)"),
    ],
)
def test_every_symbol_the_modules_cite_still_exists(rel, needle):
    assert needle in (ROOT / rel).read_text(encoding="utf-8"), f"{rel} lost {needle}"


@pytest.mark.parametrize(
    "rel, name",
    [
        ("tools/hz_mismatch_diagnose.py", "_FULL_COMBO in core/laning_scenario_precompute.py"),
        ("tools/sibling_sweep_ci.py", "``load_config`` in sibling_name_sweep.py"),
        ("tools/sibling_sweep_ci.py", "``assert_non_vacuous`` call in ``_run_scan``"),
        ("vision_server/_http.py", "``_serve_web_asset`` in dashboard/routes_static.py"),
        ("tools/replay_chain_watch.py", "``_run`` in tools/ci_watchdog.py"),
        ("tools/regen_arena_laning_table.py", "``atomic_write`` in ``core/laning_scenario_precompute.py``"),
        ("tools/live_write_tracer.py", "``DEFAULT_ROOT``'s parent in ops/loop/slots.py"),
        ("tools/gated_live_probe.py", "`_capture_screen` in modes/shared_vision.py"),
        ("lib/scrapers/_base.py", "``_scrape_one`` in agents/agent2_backend/pipeline/orchestrator.py"),
        ("tools/hz_shadow_arena_contamination.py", "``_resolve_cell_ctx`` in core/precomputed_laning_coach.py"),
        ("tools/screen_agent.py", "FileHandler setup in tools/liveclient_relay.py"),
    ],
)
def test_prose_still_names_the_symbol(rel, name):
    assert name in (ROOT / rel).read_text(encoding="utf-8")
