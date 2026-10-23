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
RC_LANE_PROGRESS_ROOT, RC_FUSION_SHADOW_PATH, RC_PHASE3_LOG_DIR (RM-812: bound
into agents/_supervisor_common.LOG_ROOT at import, i.e. during collection, so a
per-test value would arrive too late).
Not runtime roots, left out on purpose: RC_VISION_BASE and RC_PSEUDO_BASE (URLs),
RC_TRACER_ROOT (the tree the write tracer READS), RC_SELF_CAST_LOG (an on/off flag),
RC_TRACER_REPORT (its default is already the system temp dir, never the live tree).

EXTRA_IGNORE - files under the kit's watched dirs that RC's own scheduled inbox
tick (RC-InboxResponder, every 5 min) rewrites while a suite runs, added to the
kit's IGNORE for the same reason the kit ignores inbox_status.json: a change the
live tick made says nothing about a test. Kit v14 (MAIN 2026-10-09 0930 step 3):
passed as install(..., extra_ignore=EXTRA_IGNORE), which ADDS to the kit IGNORE;
the v14 IGNORE itself now holds every *.lock and headless_budget.json, so
inbox_tick.lock and headless_budget.json left this list. ASCII only.
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
    # RM-776: agents/agent2_backend/ws_server.py logs/ws/{ingest,push}.log root;
    # a test's `python -m agents.agent2_backend.ws_server` child inherits it.
    "RC_WS_LOG_DIR": "ws_logs",
    # RM-788: tools/sibling_name_sweep.py BYPASS report log (default
    # ops/runtime/sibling_sweep_bypass.log beside the tool's own checkout).
    "RC_SIBLING_SWEEP_BYPASS_LOG": "sibling_sweep_bypass.log",
    # RM-812: tools/liveclient_relay.py logs/liveclient_relay.log (import-time
    # FileHandler); tests/test_agent_relay_audit.py imports it in a child.
    "RC_LIVECLIENT_RELAY_LOG": "liveclient_relay.log",
    # RM-812: vision_server/_config.py <repo>/moon_vision_server.log
    # (import-time basicConfig); a key-lookup test imports it in a child.
    "RC_VISION_SERVER_LOG": "moon_vision_server.log",
    # RM-812: modules/cache_engine.decisions_db_path() data/decisions.db, read
    # at call time (performance_tracker.save_rating -> coaches.feedback).
    "RC_DECISIONS_DB": "decisions.db",
}

EXTRA_IGNORE = (
    "ops/loop/control/inbox_tick_last.json",
    "ops/loop/control/inbox_held/*",
)
