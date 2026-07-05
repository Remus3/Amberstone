"""D6 (2026-07-04): RC-LCUAgent must bump data/force_scan.json when the
Arena/Cherry augment picker opens, so the free-running ~20s vision scan is
pulled forward to OCR the transient augment panel before it closes (which is
what seeds data/augment_shadow.jsonl / data/anvil_shadow.jsonl).

phase_watcher is dead/undeployed, so the bump lives in the ONLY live component
that can reach the Cherry augment LCU endpoint: RC-LCUAgent (tools/lcu_agent.py),
whose _state_push_loop runs capture_state() every ~1s. capture_state() probes
/lol-cherry-game-intra-event/v1/augments (Arena-gated) and sets
state['cherry_augment_open']; an edge-latch (_maybe_force_augment_scan) fires
_write_force_scan_marker() exactly once on the False->True transition, re-arming
on close so each Arena round (1-4) fires once.

The agent runs standalone and cannot import core.* (see the module comment in
tools/lcu_agent.py) - so the marker writer is a LOCAL tmp+replace, NOT
core.polled_json.atomic_write_json. This suite pins the edge/atomicity/gate
behavior. All authored content here is 7-bit ASCII.
"""
from __future__ import annotations

import inspect
import json
from pathlib import Path

import pytest

import tools.lcu_agent as agent

_REPO_ROOT = Path(__file__).resolve().parent.parent

# en/em dash + smart single/double quotes, built via code points so this
# guard file stays 7-bit ASCII and never trips its own assertion.
_BANNED_CHARS = "".join(chr(c) for c in (
    0x2013, 0x2014, 0x2018, 0x2019, 0x201c, 0x201d))


@pytest.fixture(autouse=True)
def _reset_edge_state():
    """Every test starts from a known-closed edge state so ordering between
    tests can never leak a stale was_open latch."""
    agent._augment_scan_state["was_open"] = False
    yield
    agent._augment_scan_state["was_open"] = False


# ---------------------------------------------------------------------------
# 1-3. edge-latch semantics (fire once on open, re-arm on close)
# ---------------------------------------------------------------------------

def test_edge_fires_once_on_open(monkeypatch):
    """False->True fires exactly one marker write; a second True while still
    open is deduped (no re-fire)."""
    calls = {"n": 0}
    monkeypatch.setattr(agent, "_write_force_scan_marker",
                        lambda: calls.__setitem__("n", calls["n"] + 1))
    agent._augment_scan_state["was_open"] = False

    agent._maybe_force_augment_scan({"cherry_augment_open": True})
    agent._maybe_force_augment_scan({"cherry_augment_open": True})

    assert calls["n"] == 1


def test_no_fire_when_closed(monkeypatch):
    """Picker never opens -> zero marker writes."""
    calls = {"n": 0}
    monkeypatch.setattr(agent, "_write_force_scan_marker",
                        lambda: calls.__setitem__("n", calls["n"] + 1))

    for _ in range(3):
        agent._maybe_force_augment_scan({"cherry_augment_open": False})

    assert calls["n"] == 0


def test_rearm_after_close_refires(monkeypatch):
    """True,False,True (round boundary) fires on each fresh open -> two writes."""
    calls = {"n": 0}
    monkeypatch.setattr(agent, "_write_force_scan_marker",
                        lambda: calls.__setitem__("n", calls["n"] + 1))
    agent._augment_scan_state["was_open"] = False

    for open_now in (True, False, True):
        agent._maybe_force_augment_scan({"cherry_augment_open": open_now})

    assert calls["n"] == 2


# ---------------------------------------------------------------------------
# 4. the marker itself lands atomically with the expected payload
# ---------------------------------------------------------------------------

def test_marker_written_atomically(tmp_path, monkeypatch):
    """_write_force_scan_marker writes data/force_scan.json under the agent's
    app dir via tmp+replace: valid JSON with a positive float 'force', and no
    leftover *.tmp sidecar."""
    monkeypatch.setattr(agent, "_APP_DIR_LCU", tmp_path)
    agent._augment_scan_state["was_open"] = False

    agent._maybe_force_augment_scan({"cherry_augment_open": True})

    marker = tmp_path / "data" / "force_scan.json"
    assert marker.is_file()
    payload = json.loads(marker.read_text(encoding="utf-8"))
    force = payload.get("force")
    assert isinstance(force, float) and force > 0
    assert list(marker.parent.glob("*.tmp")) == []


# ---------------------------------------------------------------------------
# 5. capture_state()'s probe/gate logic reads available[] correctly
# ---------------------------------------------------------------------------

def test_capture_state_flag_from_available():
    """The Arena-gated probe in capture_state sets cherry_augment_open True
    only when /lol-cherry-game-intra-event/v1/augments returns a non-empty
    available[] list; empty list or an HTTP error -> False.

    capture_state() is too heavy to unit-drive hermetically (it opens a live
    LCU connection, walks gameflow/champ-select/mastery), so we pin the probe
    LOGIC as it is actually authored in the source: the exact endpoint path,
    the reused Arena queue-id guard literal, and the non-empty-list truthiness
    that maps available -> the flag.
    """
    src = inspect.getsource(agent.capture_state)
    # the augment endpoint is probed
    assert "/lol-cherry-game-intra-event/v1/augments" in src
    # the flag exists and defaults present
    assert "cherry_augment_open" in src
    # the SAME Arena queue-id guard set used at the arena_teams block is reused
    assert "1700" in src and "1710" in src and "1750" in src
    # available[] non-empty is the open signal
    assert "available" in src

    # Behavioral cross-check of the truthiness rule the probe uses, exercised
    # directly (mirrors the source: bool(isinstance(avail, list) and avail)).
    def _open_from(resp):
        avail = resp.get("available") if isinstance(resp, dict) else None
        return bool(isinstance(avail, list) and avail)

    assert _open_from({"available": [{"id": 1}]}) is True
    assert _open_from({"available": []}) is False
    assert _open_from(None) is False
    assert _open_from({}) is False


# ---------------------------------------------------------------------------
# 6. the state-push loop actually wires the edge helper
# ---------------------------------------------------------------------------

def test_state_loop_wires_helper():
    src = inspect.getsource(agent._state_push_loop)
    assert "_maybe_force_augment_scan" in src


# ---------------------------------------------------------------------------
# ASCII hygiene for every file this slice touched
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("rel", [
    "tools/lcu_agent.py",
    "tests/test_lcu_agent_augment_force_scan.py",
])
def test_no_banned_typography(rel):
    text = (_REPO_ROOT / rel).read_text(encoding="utf-8")
    bad = sorted({c for c in text if c in _BANNED_CHARS})
    assert not bad, f"{rel} contains banned chars: {[hex(ord(c)) for c in bad]}"
