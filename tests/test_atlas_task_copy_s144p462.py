"""atlas.html node copy names no unregistered scheduled task as live (S144-P-462).

The 2026-10-31 launcher cutover unregistered RC-DaemonSlayer and the other
launcher-owned tasks (docs/OPERATIONS.md, "Moved to the app"). Two atlas node
descriptions still described the old arrangement in the present tense:

- ``t_startds``: "Boot launcher the RC-DaemonSlayer scheduled task uses ...";
- ``operations``: "... the scheduled-task list that keeps RC alive".

On this host RC's DsWatchdog starts Daemon Slayer as its own child and the
rc-shell service host keeps the runtime up, so each desc now says so. Only the
``desc`` copy changes: node ids, labels and edges are untouched.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
ATLAS = REPO / "atlas.html"

# A launcher-owned task named as something that runs or uses a file today.
_LIVE_TASK = re.compile(
    r"RC-DaemonSlayer scheduled task uses|scheduled-task list that keeps RC alive"
)
_UNREGISTERED = (
    "RC-Supervisor",
    "RC-LCUAgent",
    "RC-LiveClientRelay",
    "RC-HotkeyListener",
    "RC-Phase3-Supervisor",
    "RC-DaemonSlayer",
)


@pytest.fixture(scope="module")
def nodes() -> list[dict]:
    html = ATLAS.read_text(encoding="utf-8")
    start = html.index("var NODES=")
    body = html[start : html.index("var DUST=", start)]
    arr = json.loads(body[body.index("[") : body.rindex("]") + 1])
    assert len(arr) > 100, f"NODES parse collapsed: {len(arr)} nodes"
    return arr


def _desc(nodes: list[dict], node_id: str) -> str:
    for n in nodes:
        if n["id"] == node_id:
            return n["desc"]
    raise AssertionError(f"atlas node {node_id!r} missing")


def test_no_desc_calls_an_unregistered_task_live(nodes):
    bad = [n["id"] for n in nodes if _LIVE_TASK.search(n.get("desc", ""))]
    assert not bad, f"atlas descs still describe the old task arrangement: {bad}"


def test_t_startds_desc_names_dswatchdog_and_the_cutover(nodes):
    desc = _desc(nodes, "t_startds")
    assert "DsWatchdog" in desc, desc
    assert "unregistered" in desc, desc
    assert "tools/start_daemon_slayer.py" in desc or "launcher" in desc.lower()


def test_operations_desc_names_the_service_host(nodes):
    desc = _desc(nodes, "operations")
    assert "service host" in desc, desc


def test_the_pattern_matches_the_old_copy_and_not_the_new():
    """Positive control for the pattern."""
    assert _LIVE_TASK.search("Boot launcher the RC-DaemonSlayer scheduled task uses to start")
    assert _LIVE_TASK.search("and the scheduled-task list that keeps RC alive.")
    assert not _LIVE_TASK.search(
        "Boot launcher for the engine; the RC-DaemonSlayer task that ran it is unregistered"
    )


def test_premise_the_cutover_unregistered_the_task_and_dswatchdog_spawns_ds():
    ops = (REPO / "docs" / "OPERATIONS.md").read_text(encoding="utf-8")
    assert "UNREGISTERED" in ops and "`RC-DaemonSlayer`" in ops
    client = (REPO / "core" / "daemon_slayer_client.py").read_text(encoding="utf-8")
    assert "_spawn_child" in client and "DsWatchdog" in client


def test_premise_the_names_are_still_listed_as_cutover_tasks():
    """The unregistered set this guard reasons about is the launcher's own."""
    cut = (REPO / "tools" / "launcher_cutover.ps1").read_text(encoding="utf-8")
    for name in _UNREGISTERED:
        assert f"'{name}'" in cut, name
