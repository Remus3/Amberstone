"""RM-1360: ten scattered modules cite their neighbours by symbol.

rc_transactional_deploy, overlay_live_frame_probe, performance_tracker,
queue_loop, vision_server/_relay, repair_spend_ledger, ocr_shadow_report,
inbox_responder_exec, rewind_catchup and sr_user_builds carried
`<file>.py:<line>` anchors into rc_supervisor.py, _liveclient.py,
inbox_responder.py, riot_api.py, _dispatch.py and others. Most had drifted
(`_liveclient.py:114 liveclient_summary()` now lives at line 271;
`inbox_responder.py:259-276` is a different validator than the one described).
The prose now names the symbol; this guard keeps it that way and pins that
every cited symbol still exists. Port numbers such as `:8888` are not line
cites and are left alone.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
MODULES = (
    "ops/rc_transactional_deploy.py",
    "tools/overlay_live_frame_probe.py",
    "performance_tracker.py",
    "ops/loop/queue_loop.py",
    "vision_server/_relay.py",
    "tools/repair_spend_ledger.py",
    "tools/ocr_shadow_report.py",
    "tools/inbox_responder_exec.py",
    "scripts/rewind_catchup.py",
    "coaches/sr_user_builds.py",
)

_LINE_CITE = re.compile(r"[A-Za-z0-9_/.]+\.(?:py|js|css|json):\d+")


@pytest.mark.parametrize("rel", MODULES)
def test_module_cites_no_file_line_numbers(rel):
    text = (ROOT / rel).read_text(encoding="utf-8")
    assert _LINE_CITE.findall(text) == [], "cite a symbol, not a line number"


def test_line_cite_pattern_catches_the_old_forms():
    for old in (
        "(`ops/rc_supervisor.py:658`,",
        "configured at `ops/rc_config.json:9`)",
        "dashboard/_liveclient.py:114 liveclient_summary() (attached at",
        "(_liveclient.py:148) and the clock",
        "``agents/supervisor.py:794-805``. Measured",
        "(lanes.py:300-306) and reusing",
        "(_frame.py:231, cycle 20) and",
        "flags (inbox_responder.py:259-276). That is",
        "(core/riot_api.py:799-806) and a bare None",
        """stageFor(next_buy_model.js:67-75): the FURTHER""",
        "(tests/test_sr_user_builds_lane8_cycle22.py:28). Lane 8",
        "dashboard/_dispatch.py:168 + :208). Nothing",
    ):
        assert _LINE_CITE.search(old), old
    assert _LINE_CITE.search("spliced into :8888 by dashboard/_dispatch.py") is None


@pytest.mark.parametrize(
    "rel, needle",
    [
        ("ops/rc_supervisor.py", "def _run_deploy_thread"),
        ("ops/rc_supervisor.py", "def process_deploy_requests"),
        ("ops/rc_supervisor.py", "def app_is_healthy"),
        ("ops/rc_supervisor.py", "[12] rollback excludes ops/backups/"),
        ("ops/rc_config.json", '"deploy_script"'),
        ("dashboard/routes_static.py", "relative_to(web_root)"),
        ("core/polled_json.py", "_REPLACE_RETRY_DELAYS_S"),
        ("dashboard/_liveclient.py", "def liveclient_summary"),
        ("dashboard/_liveclient.py", 'out["gold"]'),
        ("dashboard/_liveclient.py", 'out["game_time_s"]'),
        ("dashboard/_state_builder.py", "liveclient_summary"),
        ("agents/supervisor.py", "def _rating_file_is_current"),
        ("tft/placement_aggregator.py", "def build_heatmap"),
        ("ops/loop/lanes.py", 'slots = _bind("rc_loop_slots"'),
        ("ops/loop/lanes.py", "def lane_state"),
        ("ops/loop/steer.py", "def append"),
        ("vision_server/_frame.py", "def handle_upload_frame"),
        ("core/liveclient_cache.py", "def _fetch_once"),
        ("coaches/_base_coach.py", "def _record_coach_call"),
        ("core/match_db.py", "def _note_match_boundary"),
        ("coaches/aram_coach.py", "_ARAM_SHADOW_FIELDS"),
        ("coaches/arena_coach.py", "SHADOW_FIELDS"),
        ("tools/inbox_responder.py", "def _validate_measure"),
        ("tools/inbox_responder.py", "_SHELL_META"),
        ("tools/inbox_responder.py", "_WRITING_FLAGS"),
        ("tools/inbox_responder.py", "def _validate_reply"),
        ("tools/inbox_responder.py", "_MAX_BODY_BYTES"),
        ("core/riot_api.py", "def get_recent_matches"),
        ("core/riot_api.py", "def is_configured"),
        ("dashboard/_dispatch.py", "def _gather_get"),
        ("dashboard/_dispatch.py", "def _gather_post"),
        ("coaches/rune_pages.py", "_user_builds_for"),
        ("web/js/lib/next_buy_model.js", "export function stageFor"),
        ("web/js/lib/next_buy_model.js", "next===true"),
        ("tests/test_sr_user_builds_lane8_cycle22.py", "W6 an exhausted os.replace retry"),
    ],
)
def test_every_symbol_the_modules_cite_still_exists(rel, needle):
    assert needle in (ROOT / rel).read_text(encoding="utf-8"), f"{rel} lost {needle}"


@pytest.mark.parametrize(
    "rel, name",
    [
        ("ops/rc_transactional_deploy.py", "_run_deploy_thread"),
        ("ops/rc_transactional_deploy.py", "process_deploy_requests"),
        ("tools/overlay_live_frame_probe.py", "liveclient_summary"),
        ("performance_tracker.py", "_rating_file_is_current"),
        ("performance_tracker.py", "build_heatmap"),
        ("ops/loop/queue_loop.py", "steer.append"),
        ("vision_server/_relay.py", "handle_upload_frame"),
        ("vision_server/_relay.py", "_fetch_once"),
        ("tools/repair_spend_ledger.py", "_record_coach_call"),
        ("tools/ocr_shadow_report.py", "_ARAM_SHADOW_FIELDS"),
        ("tools/inbox_responder_exec.py", "_validate_measure"),
        ("tools/inbox_responder_exec.py", "_validate_reply"),
        ("scripts/rewind_catchup.py", "get_recent_matches"),
        ("scripts/rewind_catchup.py", "is_configured"),
        ("coaches/sr_user_builds.py", "_gather_get"),
        ("coaches/sr_user_builds.py", "_user_builds_for"),
    ],
)
def test_prose_still_names_the_symbol(rel, name):
    assert name in (ROOT / rel).read_text(encoding="utf-8")
