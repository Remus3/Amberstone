"""S144-P-664 - ruff D400 (first docstring line does not end in a period) is held at a shrink-only baseline.

D400 is not selected by ruff.toml. Measured 2026-11-10 with ``ruff check --isolated --line-length 120`` (target py39)
over the tracked Python: 210 findings in 180 files (D415 reports the same sites, so only D400 is counted). Ten
production modules (22 sites: agents/_supervisor_http.py, dashboard/routes_ops_panels.py and the one-line
``GET /api/...`` route docstrings of routes_item_wpa, routes_rune_wpa, routes_skill_wpa, routes_summspell_wpa,
routes_post_game_wpa, routes_post_game_rubric, routes_personal_context, routes_replay_events) got the closing period
ruff asks for - text inside a docstring only, no token outside a string changes, so behaviour is unchanged.

Not touched, and named in ``_BASELINE`` with their counts (now 167 sites in 150 files), so it drains in later slices:
a docstring whose summary opens on its own line or wraps over several lines needs the sentence rewritten, not a
period appended; ``agents/daemon_slayer/`` belongs to the ds lane and ``ops/launcher/`` is PKG-owned; files other
lane branches changed and have not landed stay in the baseline until they land.

Second slice (S144-P-665): ten tests/snapshot_panels modules (build_insights_view, focus_ring_token_sites,
history_view, home_review_r30, home_view, item_value_diff, lobby_view, overlay_fix_coach_radial,
overlay_phase_surfaces, overlay_stats_role) gained a one-line summary ending in a period (four ``Hard rule:
ASCII-only`` test docstrings and six module docstrings that opened on a path line), 10 sites, so the baseline is
now 178 sites in 160 files.

Third slice (S144-P-666): ten more modules (tests/snapshot_panels test_render_dedup_reshow, test_replay_view,
test_session_view, test_settings_view, test_spike_curve, test_user_builds_view, test_xss_escaping,
test_ui_mock_active_match_map_stall, tests/snapshot_regressions/test_app_authority, tests/test_two_tier_tokens_oq5)
gained a one-line summary ending in a period, 11 sites, so the baseline is now 167 sites in 150 files.

Fourth slice (S144-P-667): ten tests/ modules (test_overlay_css_typography_tokens, test_overlay_launcher_hit_targets,
test_view_section_btn_selector_removed, test_web_element_id_resolution_rm339, test_web_view_registry_rm340,
test_web_css_split_plan_rm726, test_web_js_split_plan_rm726, test_motion_reduce_sweep_oq4,
test_dark_values_ratchet_oq6, test_oq3_objective_gauge_mocks) gained a one-line summary above their path line,
10 sites, so the baseline is now 157 sites in 140 files.

Fifth slice (S144-P-669): ten tests/ modules (test_gated_b29_window_parity, test_gated_frame_readback,
test_gated_live_probe_relay_auth, test_gated_tls_2999_probe, test_gated_vision_pillow, test_history_session_wl_oq8,
test_overlay_slider_hit_target, test_rc_skel_removed, test_live_item_tape_wiring, test_loop_controller_code_reload)
gained a one-line summary above their path line (or a summary line ahead of the wrapped opening), 10 sites, so the
baseline is now 147 sites in 130 files.

Sixth slice (S144-P-670): ten more tests/ modules (test_historical_pgr_dom, test_home_last20,
test_loop_control_contention, test_loop_director_context_caps, test_md_guard_selector_bound_argv_s144q40b,
test_metrics_cache_coaching_ts_instant_rm298b, test_no_console_flash_scheduled_tools,
test_overlay_callouts_ui_audit, test_post_game_rubric, test_replay_analysis) gained a one-line summary ending in a
period (a summary line above a wrapped or path-led opening, or a question reworded as a statement), 10 sites, so
the baseline is now 137 sites in 120 files.

Seventh slice (S144-P-671): ten more tests/ modules (test_aram_coach_shadow_choices_native_emit,
test_base_coach_structured_field_limit, test_coach_choices_alt_hotkey, test_coach_output_p2_2,
test_css_var_definitions_rm209, test_dashboard_post_trust_boundary, test_data_viz_tier_y07,
test_decision_detector_lane8_cycle12, test_ds_perm_swarm, test_mission_control_server) gained a one-line summary
ending in a period (a summary line above a path-led or wrapped opening, or a question reworded as a statement),
10 sites, so the baseline is now 127 sites in 110 files. The three tests/snapshot_panels modules still in the
baseline are the uiux lane's (changed on lane/uiux and not yet landed).

``ops/fleet_kit/`` is vendored byte-for-byte and pinned by its MANIFEST, so it is not scanned. The run uses NO
config (``--isolated``) so a per-file-ignore cannot hide a finding. The baseline only shrinks.
"""
from __future__ import annotations

import collections
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

from tests._repo_walk import REPO_ROOT, relative_posix, repo_files

pytestmark = pytest.mark.skipif(
    importlib.util.find_spec("ruff") is None,
    reason="ruff is not importable by this interpreter",
)

_RULES = ("D400",)
_VENDORED = "ops/fleet_kit/"
# file -> finding count. The baseline only shrinks: a new finding fails, and an entry that stops offending (or
# offends less) fails test_baseline_is_exact.
_BASELINE = {
    "agents/agent2_backend/file_ingest.py": 1,
    "agents/agent3_testing/suite/test_round12.py": 1,
    "agents/daemon_slayer/matchup.py": 1,
    "agents/daemon_slayer/tests/test_ability_base_overrides.py": 2,
    "agents/daemon_slayer/tests/test_ability_item_proc_p1l22.py": 1,
    "agents/daemon_slayer/tests/test_block_index_overrides.py": 3,
    "agents/daemon_slayer/tests/test_engine_math_correctness_pipeline_c.py": 1,
    "agents/daemon_slayer/tests/test_hps_hybrid_burst_p1l17.py": 2,
    "agents/supervisor.py": 1,
    "app/__init__.py": 1,
    "app/_game_lifecycle.py": 2,
    "app/_health_monitor.py": 1,
    "app/_overlay_manager.py": 1,
    "app/_remediation.py": 2,
    "app/_state_authority.py": 2,
    "coaches/_base_coach.py": 2,
    "coaches/aram_coach.py": 1,
    "coaches/arena_coach.py": 1,
    "coaches/brawl_coach.py": 1,
    "core/corpus_hygiene.py": 1,
    "core/daemon_slayer_client.py": 1,
    "core/decision_detector.py": 1,
    "core/draft_elo.py": 2,
    "core/hot_reload.py": 1,
    "core/math_core.py": 1,
    "core/post_game_score.py": 1,
    "core/replay_analysis.py": 1,
    "core/rofl_archive.py": 1,
    "core/skill_point_tracker.py": 1,
    "core/vision_fusion.py": 1,
    "core/vision_profiles.py": 1,
    "dashboard/_handler.py": 1,
    "dashboard/_idempotency.py": 1,
    "dashboard/_screen_read.py": 1,
    "dashboard/builders.py": 1,
    "dashboard/routes_adaptive_summoners.py": 1,
    "dashboard/routes_coach_choice.py": 1,
    "dashboard/routes_diag.py": 1,
    "dashboard/routes_ds_matchup.py": 1,
    "dashboard/routes_moon_sync.py": 1,
    "dashboard/routes_personal_vs.py": 1,
    "dashboard/view_router_state.py": 1,
    "docs/_rescore/aggregation_sweep.py": 1,
    "game_reader/poller.py": 1,
    "item_advisor.py": 1,
    "lcu/lcu_client.py": 1,
    "lcu/lcu_postgame_collector.py": 1,
    "lcu/lcu_pregame.py": 2,
    "lib/rewind_live_writer.py": 1,
    "modes/shared_vision.py": 1,
    "ops/audit/ds_perm_swarm/perm_score.py": 1,
    "ops/audit/p3c24_token_equiv.py": 1,
    "ops/rc_dev_runtime.py": 1,
    "ops/rc_incident_log.py": 1,
    "ops/rc_self_monitor.py": 2,
    "ops/rc_state_validator.py": 1,
    "ops/rc_supervisor.py": 1,
    "scripts/audit_api_surface.py": 1,
    "scripts/patch_champion.py": 1,
    "scripts/prune_synthetic_matches.py": 1,
    "scripts/rewind_catchup.py": 1,
    "scripts/rewind_dedup_children.py": 1,
    "scripts/rewind_scraper.py": 1,
    "scripts/rewind_timeline_backfill.py": 1,
    "scripts/team_planner_sync.py": 1,
    "scripts/wakeup_prune.py": 1,
    "tests/snapshot_panels/test_overlay_hotkey_hints.py": 1,
    "tests/snapshot_panels/test_overlay_launcher_menu.py": 1,
    "tests/snapshot_panels/test_stale_fade_view_t12.py": 1,
    "tests/test_inbox_responder_runner.py": 2,
    "tests/test_last_match_tabs_reframe_dom.py": 2,
    "tests/test_metrics_cache_lane8_cycle40.py": 2,
    "tests/test_no_environ_in_assert_operands.py": 2,
    "tests/test_panel_visibility_permode.py": 1,
    "tests/test_resource_manager_ceiling_rm146.py": 1,
    "tests/test_resource_manager_hardening_s144.py": 1,
    "tests/test_resource_manager_mem_remediation.py": 1,
    "tests/test_rm172_mode_modifier_seam_characterization.py": 2,
    "tests/test_routes_personal_vs.py": 1,
    "tests/test_run_packaged_smoke_updater_pkg6b.py": 1,
    "tests/test_skip_condition_hygiene.py": 2,
    "tests/test_snowball_elasticity.py": 1,
    "tests/test_stale_fade_gentle_t12.py": 1,
    "tests/test_state_builder_latency_rc2.py": 1,
    "tests/test_tft_local_player_reconcile_s135.py": 1,
    "tests/test_tft_stage_gate_rm615.py": 1,
    "tests/test_view_router_registry_rm341.py": 1,
    "tests/test_vision_seed_reachability_rm26.py": 1,
    "tft/tft_coach_engine.py": 1,
    "tft/tft_ocr_reader.py": 1,
    "tft/tft_vision_reader.py": 1,
    "tools/champion_loadout_cleanup_pollution_item213.py": 1,
    "tools/champion_loadout_collapse_to_paths.py": 1,
    "tools/champion_loadout_invariants.py": 1,
    "tools/champion_loadout_sweep_item_s8.py": 1,
    "tools/det_coach_shadow_report.py": 1,
    "tools/ds_patch_diff.py": 1,
    "tools/gated_g303_variant_reach.py": 1,
    "tools/gated_g314_tower_input.py": 1,
    "tools/gated_g5_focus_layout.py": 1,
    "tools/gated_rm869_vision_fields.py": 1,
    "tools/gated_rm881_duo_lobby.py": 1,
    "tools/gated_tft_live_keys.py": 1,
    "tools/gated_tls_2999_probe.py": 1,
    "tools/gated_y01_chain_report.py": 1,
    "tools/mine_event_patterns.py": 1,
    "tools/package_portable.py": 1,
    "tools/probe_101qq_hero_rank_double.py": 1,
    "tools/rm_id_registry.py": 1,
    "tools/vision_atlas_validate.py": 1,
}


def _ruff(args: list[str], stdin: str | None = None) -> list[dict]:
    kwargs = {}
    if sys.platform == "win32":
        kwargs["creationflags"] = 0x08000000  # CREATE_NO_WINDOW
    proc = subprocess.run(
        [sys.executable, "-m", "ruff", "check", "--isolated", "--target-version", "py39",
         "--line-length", "120", "--no-fix", "--no-cache", "--output-format", "json",
         "--select", ",".join(_RULES), *args],
        cwd=REPO_ROOT, capture_output=True, text=True, timeout=300, input=stdin, check=False, **kwargs,
    )
    # ruff exits 1 when it reports anything; 2 is a real failure.
    assert proc.returncode in (0, 1), proc.stderr[-400:]
    return json.loads(proc.stdout)


@pytest.fixture(scope="module")
def tree_counts() -> dict[str, int]:
    tracked = {relative_posix(p) for p in repo_files(REPO_ROOT, ("*.py",))}
    assert len(tracked) > 100, "the tracked-file walk returned almost nothing"
    counts: collections.Counter = collections.Counter()
    for d in _ruff(["."]):
        rel = relative_posix(Path(d["filename"]).resolve())
        if rel in tracked and not rel.startswith(_VENDORED):
            counts[rel] += 1
    return dict(counts)


def test_no_new_d400_finding(tree_counts):
    new = {rel: n for rel, n in tree_counts.items() if n > _BASELINE.get(rel, 0)}
    assert not new, f"ruff {_RULES} findings above the baseline, file: count: {new}"


def test_baseline_is_exact(tree_counts):
    """Every baseline entry still offends at its recorded count; one that shrank must be lowered or dropped."""
    stale = {rel: (n, tree_counts.get(rel, 0)) for rel, n in _BASELINE.items() if tree_counts.get(rel, 0) != n}
    assert not stale, f"baseline file: (recorded, measured): {stale}"


def test_probe_is_live():
    """D400 reports a first line without a period and stays quiet once it ends in one."""
    bad = 'def f():\n    """GET /api/x?a=1"""\n    return 1\n'
    good = 'def f():\n    """GET /api/x?a=1."""\n    return 1\n'
    found = _ruff(["--stdin-filename", "probe_mod.py", "-"], stdin=bad)
    assert {d["code"] for d in found} == set(_RULES), found
    assert _ruff(["--stdin-filename", "probe_mod.py", "-"], stdin=good) == []
