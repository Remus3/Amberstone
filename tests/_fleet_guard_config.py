"""RC's configuration for the FLEET-KIT v12 test guard (FLEET-COMMON item 16 d;
MAIN 2026-10-08 2031 ORDER step 6). `tests/conftest.py` passes these to
`ops/fleet_kit/fleet_test_guard.install()`; `tests/test_fleet_kit_v12_race_guards.py`
pins them. Plain data, no imports, so the conftest and the test read one copy.

ENV_ROOTS - every env var RC code reads to locate a runtime root (a directory or
file it WRITES), except the ones `tests/conftest.py` already redirects. The kit's
function-scoped fixture sets each to tmp_path/<sub> for every test, so a call-time
reader, or a child process a test starts, writes under tmp instead of the live tree.
Already redirected by the conftest and left there on purpose (set in os.environ at
IMPORT, so a child process started before any fixture runs inherits them; or by a
dedicated per-test fixture): RC_HOOK_LOG, RC_SIBLING_SWEEP_RUN_LOG,
RC_NOTIFY_JSONL, RC_MOMENT_MARKS_JSONL, RC_MOMENT_MARKS_DIR,
RC_LANE_PROGRESS_ROOT, RC_FUSION_SHADOW_PATH.
Not runtime roots, left out on purpose: RC_VISION_BASE and RC_PSEUDO_BASE (URLs),
RC_TRACER_ROOT (the tree the write tracer READS), RC_SELF_CAST_LOG (an on/off flag),
RC_TRACER_REPORT (its default is already the system temp dir, never the live tree).

EXTRA_IGNORE - files under the kit's watched dirs that RC's own scheduled inbox
tick (RC-InboxResponder, every 5 min) rewrites while a suite runs, added to the
kit's IGNORE for the same reason the kit ignores inbox_status.json: a change the
live tick made says nothing about a test. ASCII only.
"""

ENV_ROOTS = {
    "RC_INTENT_CONTROL_DIR": "intent_control",
    "RC_INTENT_BASE": "intent_base",
    "RC_OCR_SHADOW_PATH": "ocr_shadow.jsonl",
    "RC_VISION_MERGE_SHADOW_PATH": "vision_merge_shadow.jsonl",
    "RC_HEADLESS_ENV_LOG": "headless_route.log",
    "RC_LOGGER_CENSUS_REPORT_DIR": "logger_census",
    "RC_PHASE3_DB_DIR": "phase3_db",
    "RC_PHASE3_STATE_DIR": "phase3_state",
    "RC_LANE_WORKTREE_BASE": "lane_worktrees",
    "RC_AGENT_STATE_FILE": "rc_agent_state.json",
    "RC_MOON_SYNC_STATE": "moonsync_state",
    "RC_ROFL_ARCHIVE_DIR": "rofl_archive",
}

EXTRA_IGNORE = (
    "ops/loop/control/inbox_tick_last.json",
    "ops/loop/control/inbox_tick.lock",
    "ops/loop/control/inbox_held/*",
    "ops/loop/control/headless_budget.json",
)
