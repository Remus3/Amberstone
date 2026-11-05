"""RM-1358: six lcu / core modules cite their neighbours by symbol.

lcu/champ_select_shape.py, lcu/snapshot_shape.py, core/claude_project.py,
core/config_validator.py, core/event_callouts.py and core/rofl_stats_backfill.py
carried `<file>.py:<line>` anchors into lcu_agent, _lcu_inprocess,
rc_supervisor, rofl_archive, routes_static, routes_state and others. Nearly all
had drifted (`rc_supervisor.py:1339` is no longer inside `_do_rollback`'s
prune, `tools/lcu_agent.py:919-921` is the pick-order swap, not the lock_pick
cast the comment meant, `routes_state.py:226` sits in a cadence comment, not
the state dump). The prose now names the symbol; these guards keep it that way
and pin that every cited symbol still exists.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
MODULES = (
    "lcu/champ_select_shape.py",
    "lcu/snapshot_shape.py",
    "core/claude_project.py",
    "core/config_validator.py",
    "core/event_callouts.py",
    "core/rofl_stats_backfill.py",
)

# `routes_state.py:226`, `file.py:105,603-617`, a bare `at :943`, `and :959`,
# `lines 12`.
_LINE_CITE = re.compile(
    r"[A-Za-z_/.]+\.(?:py|js|json):\d+"
    r"|\bat ``?:\d+|\bat :\d+|\bto :\d+"
    r"|\band :\d+"
    r"|\(:\d+"
    r"|\blines? \d{2,}"
)


@pytest.mark.parametrize("rel", MODULES)
def test_module_cites_no_file_line_numbers(rel):
    text = (ROOT / rel).read_text(encoding="utf-8")
    assert _LINE_CITE.findall(text) == [], "cite a symbol, not a line number"


def test_line_cite_pattern_catches_the_old_forms():
    for old in (
        "dashboard/_lcu_inprocess.py:340-342  catches Exception",
        "tools/lcu_agent.py:1612              calls capture_state()",
        "localPlayerCellId / cellId already are at :346 and :349.",
        "(tools/lcu_agent.py:919-921) measured",
        "``dashboard/routes_state.py:226`` dumps the state",
        "(``tools/lcu_agent.py:222``, ``lcu/lcu_client.py:197``)",
        "`ops/rc_supervisor.py:1339` (FROZEN, fired at the tail",
        "callers in dashboard/_deterministic_coaching.py (:929 inline,",
        "core/rofl_archive.py:811 serializes at the default",
        "(web/js/main.js:711 s209 sticky-guard, :728",
    ):
        assert _LINE_CITE.search(old), old


@pytest.mark.parametrize(
    "rel, needle",
    [
        ("dashboard/_lcu_inprocess.py", "def lcu_summary_inprocess"),
        ("tools/lcu_agent.py", "def _state_push_loop"),
        ("tools/lcu_agent.py", "def lcu_request"),
        ("tools/lcu_agent.py", 'if name == "lock_pick":'),
        ("lcu/lcu_client.py", "def _request"),
        ("lcu/snapshot_shape.py", "def shape_snapshot"),
        ("lcu/champ_select_shape.py", "def shape_champ_select"),
        ("dashboard/_cs_retention.py", "_CLEAR_PHASES"),
        ("core/claude_project.py", "def project_dir"),
        ("dashboard/routes_loop_monitor.py", "DEFAULT_TRANSCRIPT_DIR"),
        ("tools/perseus_sync.py", "MEMDIR"),
        ("ops/loop/loop_controller.py", '"transcript_dir"'),
        ("ops/rc_supervisor.py", "def _do_rollback"),
        ("ops/rc_supervisor.py", "IncidentLog("),
        ("ops/rc_transactional_deploy.py", "def prune_backups"),
        ("dashboard/routes_state.py", "json.dumps(_timed_build_state())"),
        ("agents/_supervisor_http.py", "def _send_json"),
        ("performance_tracker.py", "def _atomic_write_json"),
        ("dashboard/_deterministic_coaching.py", "_sort_key as _callout_sort_key"),
        ("tests/test_event_callouts.py", "def test_negative_max_n_returns_full_list"),
        ("core/rofl_archive.py", "def extract_archive"),
        ("core/rofl_archive.py", "def download_replays"),
        ("core/rofl_archive.py", "atomic_write_json(target, payload)"),
        ("core/polled_json.py", "ensure_ascii=False"),
        ("dashboard/routes_static.py", "def _serve_web_asset"),
    ],
)
def test_every_symbol_the_modules_cite_still_exists(rel, needle):
    assert needle in (ROOT / rel).read_text(encoding="utf-8"), f"{rel} lost {needle}"


@pytest.mark.parametrize(
    "rel, name",
    [
        ("lcu/champ_select_shape.py", "lcu_summary_inprocess"),
        ("lcu/champ_select_shape.py", "_state_push_loop"),
        ("lcu/champ_select_shape.py", "execute_command"),
        ("lcu/snapshot_shape.py", "LcuClient._request"),
        ("lcu/snapshot_shape.py", "_cs_retention"),
        ("core/claude_project.py", "DEFAULT_TRANSCRIPT_DIR"),
        ("core/config_validator.py", "_do_rollback"),
        ("core/config_validator.py", "IncidentLog("),
        ("core/event_callouts.py", "_timed_build_state"),
        ("core/event_callouts.py", "_callout_sort_key"),
        ("core/event_callouts.py", "test_negative_max_n_returns_full_list"),
        ("core/rofl_stats_backfill.py", "extract_archive"),
        ("core/rofl_stats_backfill.py", "download_replays"),
        ("core/rofl_stats_backfill.py", "atomic_write_json"),
        ("core/rofl_stats_backfill.py", "_serve_web_asset"),
    ],
)
def test_prose_still_names_the_symbol(rel, name):
    assert name in (ROOT / rel).read_text(encoding="utf-8")
