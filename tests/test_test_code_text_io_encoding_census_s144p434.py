"""S144-P-434 - test code that calls ``.read_text()`` / ``.write_text(x)`` with no ``encoding=``: a shrinking baseline.

The production sibling ``tests/test_path_text_io_encoding_census_s144p372.py`` holds the same shape at a zero floor and
names test trees out of scope ("about 80 test-code sites remain and are filed, not hidden"). This is that filing as a
ratchet. Without ``encoding=`` Python uses the locale code page (cp1252 on a stock Windows box), so a test that writes a
non-ASCII fixture and reads it back through a module that names UTF-8 passes or fails by machine, and the same test
behaves differently under ``PYTHONUTF8=1``. Most of these are ASCII JSON fixtures written and read back in one process
(harmless today, which is why this is a ratchet and not a purge): the point is that a NEW test no longer adds one.

Measured 2026-11-08 over every tracked ``*.py`` under ``tests/`` and ``agents/daemon_slayer/tests/``: 84 sites in 33
files. This slice fixed the nine densest files (52 sites: test_hot_reload, test_gated_lx07_recap_check,
test_rm484_offline_tools_rate_limit, test_ddragon_script_icon_names_rm379, test_disk_guard, test_fleet_route,
test_disk_guard_true_audit_s144, test_lane_run_ledger, test_rofl_stats_backfill); S144-P-435 fixed nine more (14 sites:
test_archetype_picks, test_cache_ddragon_assets_version_rm372, test_ds_feed_watch, test_gated_g423_base_capture,
test_inbox_responder_runner, test_obs_recorder, test_operator_push, test_rm510_ingest_exit_codes,
test_scraper_foreign_host_rm374); 18 sites in 15 files are the baseline below (three launcher / PKG files and
test_repo_review_driver, which another lane branch changed, are not this lane's to edit). The baseline only shrinks: a file that no longer offends fails ``test_baseline_is_exact`` until its row is dropped.

The scanner is ``scan_source`` of the production census (same shapes, same ``**kwargs`` skip), imported, never copied.
"""
from __future__ import annotations

from tests._repo_walk import REPO_ROOT, relative_posix, repo_files
from tests.test_path_text_io_encoding_census_s144p372 import scan_source

_SCOPE = ("tests/", "agents/daemon_slayer/tests/")

# rel path -> bare call count. Only shrinks.
_BASELINE: dict[str, int] = {
    "agents/daemon_slayer/tests/test_enchanter_pool_hsp_rm90.py": 1,
    "agents/daemon_slayer/tests/test_r144_mirror_slice_a.py": 1,
    "tests/phase2_smoke/test_sr_aram_worker.py": 1,
    "tests/phase2_smoke/test_tft_worker.py": 1,
    "tests/snapshot_panels/test_home_view.py": 1,
    "tests/test_launcher_service_host.py": 1,
    "tests/test_launcher_update_hardening_pkg6b.py": 3,
    "tests/test_log_scrub_secret_redaction_s144t108.py": 1,
    "tests/test_repo_review_driver.py": 2,
    "tests/test_rm236_snapshot_normalizer_defects.py": 1,
    "tests/test_seraphine_beat_drop_wording_s144d78.py": 1,
    "tests/test_seraphine_encore_charm_rm1151.py": 1,
    "tests/test_session_checklist_item13.py": 1,
    "tests/test_supervisor_common_l02.py": 1,
    "tests/test_tft_cv_accuracy_harness.py": 1,
}

# Files this slice converted: each must stay at zero (a regression here is a re-introduced bare call).
_FIXED_THIS_SLICE = (
    "tests/test_hot_reload.py",
    "tests/test_gated_lx07_recap_check.py",
    "tests/test_rm484_offline_tools_rate_limit.py",
    "tests/test_ddragon_script_icon_names_rm379.py",
    "tests/test_disk_guard.py",
    "tests/test_fleet_route.py",
    "tests/test_disk_guard_true_audit_s144.py",
    "tests/test_lane_run_ledger.py",
    "tests/test_rofl_stats_backfill.py",
    # S144-P-435: nine more (14 sites).
    "tests/test_archetype_picks.py",
    "tests/test_cache_ddragon_assets_version_rm372.py",
    "tests/test_ds_feed_watch.py",
    "tests/test_gated_g423_base_capture.py",
    "tests/test_inbox_responder_runner.py",
    "tests/test_obs_recorder.py",
    "tests/test_operator_push.py",
    "tests/test_rm510_ingest_exit_codes.py",
    "tests/test_scraper_foreign_host_rm374.py",
)


def _tree_hits() -> dict[str, int]:
    out: dict[str, int] = {}
    for path in repo_files():
        rel = relative_posix(path)
        if not rel.endswith(".py") or not rel.startswith(_SCOPE):
            continue
        try:
            hits = scan_source((REPO_ROOT / rel).read_text(encoding="utf-8"))
        except (OSError, SyntaxError, UnicodeDecodeError):
            continue
        if hits:
            out[rel] = len(hits)
    return out


def test_no_new_locale_encoded_text_io_in_test_code():
    hits = _tree_hits()
    new = {rel: n for rel, n in hits.items() if n > _BASELINE.get(rel, 0)}
    assert not new, f"test code with .read_text() / .write_text() and no encoding= (locale code page): {new}"


def test_baseline_is_exact():
    hits = _tree_hits()
    stale = {rel: n for rel, n in _BASELINE.items() if hits.get(rel, 0) < n}
    assert not stale, f"baseline rows that no longer offend, drop them: {stale}"


def test_scan_reaches_the_measured_files():
    """An empty walk would pass both checks above: the walk must reach a baseline file and a converted one."""
    seen = {relative_posix(p) for p in repo_files()}
    for rel in (*_BASELINE, *_FIXED_THIS_SLICE):
        assert rel in seen, rel


def test_converted_files_stay_clean():
    hits = _tree_hits()
    back = {rel: hits[rel] for rel in _FIXED_THIS_SLICE if rel in hits}
    assert not back, f"files converted in S144-P-434 offend again: {back}"
