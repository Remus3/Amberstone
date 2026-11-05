"""RM-1359: ten dashboard/ modules cite their neighbours by symbol.

_state_builder, routes_diag, _handler, _idempotency, _deterministic_coaching,
builders_home, routes_history, routes_moon_sync, routes_loop_monitor and
routes_pickban carried `<file>.py:<line>` anchors into server.py, _dispatch.py,
event_callouts.py, lead_projection.py, vision_tesseract.py, snapshot_shape.py,
slots.py and the web panels. Nearly all had drifted (`server.py:35` is a
comment about the dual-stack bind, `_dispatch.py:143` is inside the WPA route
list, `tools/lcu_agent.py:194-234` is a block of cadence constants, not a queue
id list, `champ_select.js:2060` is inside a CC-deficit line). The prose now
names the symbol; this guard keeps it that way and pins that every cited
symbol still exists. Port numbers such as `(:8890)` are not line cites and are
left alone.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
MODULES = (
    "dashboard/_state_builder.py",
    "dashboard/routes_diag.py",
    "dashboard/_handler.py",
    "dashboard/_idempotency.py",
    "dashboard/_deterministic_coaching.py",
    "dashboard/builders_home.py",
    "dashboard/routes_history.py",
    "dashboard/routes_moon_sync.py",
    "dashboard/routes_loop_monitor.py",
    "dashboard/routes_pickban.py",
)

# `server.py:35`, `slots.py:49-82`, `file.py:105,603-617`, `main.js:3106`,
# `overlay.css:127`. A bare `(:8890)` port is deliberately NOT matched.
_LINE_CITE = re.compile(r"[A-Za-z0-9_/.]+\.(?:py|js|css|json):\d+")


@pytest.mark.parametrize("rel", MODULES)
def test_module_cites_no_file_line_numbers(rel):
    text = (ROOT / rel).read_text(encoding="utf-8")
    assert _LINE_CITE.findall(text) == [], "cite a symbol, not a line number"


def test_line_cite_pattern_catches_the_old_forms():
    for old in (
        "(dashboard/_lcu_inprocess.py:138-196): WARN on CHANGE",
        "(web/css/overlay.css:127). Both are imperative",
        "#   core/event_callouts.py:120  \"Your lvl-6 spike\"",
        "(`dashboard/_dispatch.py:114` and `:198`).",
        "(core/vision_tesseract.py:539), rebound",
        "reaches (dashboard/server.py:35).",
        "an UNCAUGHT AttributeError at routes_state.py:516 - traceback",
        "Same OpenProcess idiom as ops/loop/slots.py:49-82, with one",
        "(web/js/main.js:3106 _HOME",
        "tools/lcu_agent.py:194-234.",
    ):
        assert _LINE_CITE.search(old), old
    assert _LINE_CITE.search("proxied to the agents supervisor (:8890)") is None


@pytest.mark.parametrize(
    "rel, needle",
    [
        ("dashboard/_lcu_inprocess.py", "def _log_degrade"),
        ("web/css/overlay.css", "The wrappers collapse to nothing"),
        ("web/css/overlay.css", '#right-now .panel-body > *:not(#rn-lead)'),
        ("web/css/panels/map_state.css", "trigger-pill"),
        ("core/event_callouts.py", "_SPIKE_LEVEL_LINES"),
        ("core/event_callouts.py", "_SPIKE_ITEM_LINES"),
        ("core/event_callouts.py", "_SR_OBJECTIVES"),
        ("core/event_callouts.py", "Drake spawns 5:00 - set up vision"),
        ("core/lead_projection.py", "_LINES: Dict"),
        ("core/lead_projection.py", "_LINES_BY_MODE"),
        ("core/lead_projection.py", "Big lead: dive or roam, snowball it now."),
        ("dashboard/_dispatch.py", "def _gather_get"),
        ("dashboard/_dispatch.py", "def _gather_post"),
        ("dashboard/_dispatch.py", "routes_loop_monitor.GET_ROUTES"),
        ("dashboard/server.py", 'HOST = "::"'),
        ("dashboard/server.py", "class _DualStackHTTPServer"),
        ("core/vision_tesseract.py", "_DROP_FIELDS: set"),
        ("core/vision_tesseract.py", "def configure_drop_fields"),
        ("core/vision_tesseract.py", "def read_fast_fields"),
        ("core/vision_routing.py", "read_fast_fields"),
        ("dashboard/routes_state.py", "def _serve_command_post"),
        ("core/item_wpa.py", "def load_legendary_ids"),
        ("coaches/aram_coach.py", "def _item_interaction_block"),
        ("lcu/snapshot_shape.py", "def shape_snapshot"),
        ("lcu/snapshot_shape.py", "_LOBBY_QUEUE_NAMES"),
        ("dashboard/routes_op_score.py", "_CACHE_TTL_S"),
        ("web/js/main.js", "const _HOME = { lastFetchAt: 0, intervalMs: 20000"),
        ("ops/loop/slots.py", "def pid_alive"),
        ("web/js/panels/champ_select.js", "const _PB_PLACEHOLDERS"),
    ],
)
def test_every_symbol_the_modules_cite_still_exists(rel, needle):
    assert needle in (ROOT / rel).read_text(encoding="utf-8"), f"{rel} lost {needle}"


@pytest.mark.parametrize(
    "rel, name",
    [
        ("dashboard/_state_builder.py", "_log_degrade"),
        ("dashboard/_state_builder.py", "_SPIKE_LEVEL_LINES"),
        ("dashboard/_state_builder.py", "_SPIKE_ITEM_LINES"),
        ("dashboard/_state_builder.py", "_SR_OBJECTIVES"),
        ("dashboard/_state_builder.py", "_LINES_BY_MODE"),
        ("dashboard/routes_diag.py", "_gather_get"),
        ("dashboard/routes_diag.py", "_gather_post"),
        ("dashboard/routes_diag.py", "_DROP_FIELDS"),
        ("dashboard/_handler.py", "_serve_command_post"),
        ("dashboard/_idempotency.py", "_DualStackHTTPServer"),
        ("dashboard/_deterministic_coaching.py", "load_legendary_ids"),
        ("dashboard/_deterministic_coaching.py", "_item_interaction_block"),
        ("dashboard/_deterministic_coaching.py", "shape_snapshot"),
        ("dashboard/builders_home.py", "_LOBBY_QUEUE_NAMES"),
        ("dashboard/routes_history.py", "_HOME"),
        ("dashboard/routes_moon_sync.py", "pid_alive"),
        ("dashboard/routes_loop_monitor.py", "_gather_get"),
    ],
)
def test_prose_still_names_the_symbol(rel, name):
    assert name in (ROOT / rel).read_text(encoding="utf-8")
