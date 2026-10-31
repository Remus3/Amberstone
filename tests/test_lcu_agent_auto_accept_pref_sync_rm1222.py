"""RM-1222: the LCU agent's auto-accept follows the SAVED preference.

The defect, measured 2026-10-31 at ddb4a5e20: two mechanisms accept a ready
check. RC's in-process loop (frozen ``lcu/lcu_client.py`` ``_auto_accept_tick``)
reads ``core.auto_accept_pref`` (``data/auto_accept_pref.json``) before every
accept; the LCU agent (``tools/lcu_agent.py`` ``auto_features``) reads its
own ``CONFIG["auto_accept"]``, which is process memory only and boots off.
The dashboard "Auto Accept" control DISPLAYS the agent's CONFIG
(``state.lcu.config.auto_accept``). So after every agent restart the control
said Off while the saved choice said on and RC's loop kept accepting: the
s171 "accepts regardless of the UI" class, the other way round from the
08506e2af default flip.

Ruling C (s145 Q2): the saved preference is the one source of truth. The
agent seeds CONFIG from it at boot, before the first state push, and re-reads
it on every auto-features tick, so the control shows - and both mechanisms
act on - the same saved value. An absent or corrupt preference is still the
OFF default.

Every test points ``core.auto_accept_pref`` at a tmp file; the live
``data/auto_accept_pref.json`` is never read for a decision or written, and a
module fixture asserts its bytes are unchanged.
"""
from __future__ import annotations

import logging
import sys
import types
from pathlib import Path
from unittest import mock

import pytest

from core import auto_accept_pref as pref

_ROOT = Path(__file__).resolve().parent.parent
_LIVE = _ROOT / "data" / "auto_accept_pref.json"
for _p in (str(_ROOT), str(_ROOT / "tools")):
    if _p not in sys.path:
        sys.path.insert(0, _p)


class _Stop(Exception):
    """Breaks an agent ``while True`` loop after the step under test."""


@pytest.fixture(scope="module", autouse=True)
def _live_pref_bytes_untouched():
    before = _LIVE.read_bytes() if _LIVE.exists() else None
    yield
    after = _LIVE.read_bytes() if _LIVE.exists() else None
    assert after == before, "live data/auto_accept_pref.json was modified"


@pytest.fixture
def pref_file(tmp_path, monkeypatch):
    p = tmp_path / "auto_accept_pref.json"
    monkeypatch.setattr(pref, "_PREF_PATH", p)
    monkeypatch.setattr(pref, "_last_good", None)
    monkeypatch.setattr(pref, "_last_problem", None)
    return p


@pytest.fixture
def agent(pref_file, monkeypatch):
    import lcu_agent
    # The read-fault warning dedupe starts clean for every test.
    monkeypatch.setitem(lcu_agent._pref_sync_state, "faulted", False)
    saved_cfg = dict(lcu_agent.CONFIG)
    saved_port = lcu_agent._lcu.get("port")
    yield lcu_agent
    lcu_agent.CONFIG.clear()
    lcu_agent.CONFIG.update(saved_cfg)
    lcu_agent._lcu["port"] = saved_port


def _boot(agent, monkeypatch):
    """Run ``loop()`` up to its idle sleep with every side effect stubbed.

    Returns the ``auto_accept`` value CONFIG held as each worker thread was
    STARTED, so a test can tell a boot seed from a later tick.
    """
    seen: list = []

    class _FakeThread:
        def __init__(self, target=None, daemon=None, name=None):
            self.name = name

        def start(self):
            seen.append((self.name, agent.CONFIG.get("auto_accept")))

    def _sleep(_s):
        raise _Stop()

    monkeypatch.setattr(agent, "threading",
                        types.SimpleNamespace(Thread=_FakeThread))
    monkeypatch.setattr(agent, "time", types.SimpleNamespace(sleep=_sleep))
    for name in ("_load_ingest_state", "_recover_missed_ingest",
                 "_install_draft_log_sink"):
        monkeypatch.setattr(agent, name, lambda: None)
    with pytest.raises(_Stop):
        agent.loop()
    return seen


def _ready_check_fake():
    calls: list = []

    def fake(method, path, body=None):
        calls.append((method, path))
        if method == "GET" and path == "/lol-matchmaking/v1/ready-check":
            return {"state": "InProgress", "playerResponse": "None"}, None
        return {}, None
    return fake, calls


_ACCEPT = ("POST", "/lol-matchmaking/v1/ready-check/accept")


# ------------------------------------------------------------------ boot


def test_boot_with_saved_pref_on_reports_on_before_any_thread(
        agent, pref_file, monkeypatch):
    pref_file.write_text('{"enabled": true}', encoding="utf-8")
    agent.CONFIG["auto_accept"] = False          # the in-memory boot default
    seen = _boot(agent, monkeypatch)
    assert seen, "loop() started no worker thread"
    assert all(v is True for _, v in seen), (
        f"a worker started before CONFIG took the saved choice: {seen}")
    # The snapshot the state-push loop posts (what the dashboard renders).
    monkeypatch.setattr(agent, "ensure_lcu_conn", lambda: False)
    monkeypatch.setattr(agent, "time",
                        types.SimpleNamespace(time=lambda: 0.0))
    assert agent.capture_state()["config"]["auto_accept"] is True


def test_boot_with_saved_pref_on_accepts_a_ready_check(
        agent, pref_file, monkeypatch):
    pref_file.write_text('{"enabled": true}', encoding="utf-8")
    agent.CONFIG["auto_accept"] = False
    _boot(agent, monkeypatch)
    agent._lcu["port"] = 1
    agent.CONFIG["summoner_override"] = False
    fake, calls = _ready_check_fake()
    with mock.patch.object(agent, "lcu_request", side_effect=fake):
        agent.auto_features()
    assert _ACCEPT in calls


def test_boot_with_saved_pref_off_stays_off(agent, pref_file, monkeypatch):
    pref_file.write_text('{"enabled": false}', encoding="utf-8")
    agent.CONFIG["auto_accept"] = True
    seen = _boot(agent, monkeypatch)
    assert all(v is False for _, v in seen), seen


# ------------------------------------------------------- the OFF default


def test_missing_pref_file_is_the_off_default(agent, pref_file, monkeypatch):
    assert not pref_file.exists()
    agent.CONFIG["auto_accept"] = True
    seen = _boot(agent, monkeypatch)
    assert all(v is False for _, v in seen), seen


@pytest.mark.parametrize("raw", [
    b"not json",
    b'{"enabled": "true"}',
    b"\xff\xfe{\"enabled\": true}",
    b"[]",
])
def test_corrupt_pref_file_is_the_off_default(agent, pref_file, monkeypatch,
                                              raw):
    pref_file.write_bytes(raw)
    agent.CONFIG["auto_accept"] = True
    agent._sync_auto_accept_from_pref()
    assert agent.CONFIG["auto_accept"] is False


# ------------------------------------------------------------- each tick


def _one_tick(agent, monkeypatch):
    """Run one ``_auto_features_loop`` iteration; return CONFIG's
    ``auto_accept`` as ``auto_features`` saw it."""
    seen: list = []

    def _sleep(_s):
        raise _Stop()

    monkeypatch.setattr(agent, "ensure_lcu_conn", lambda: True)
    monkeypatch.setattr(agent, "auto_features",
                        lambda: seen.append(agent.CONFIG.get("auto_accept")))
    monkeypatch.setattr(agent, "time", types.SimpleNamespace(sleep=_sleep))
    with pytest.raises(_Stop):
        agent._auto_features_loop()
    return seen


def test_tick_follows_a_saved_change(agent, pref_file, monkeypatch):
    pref_file.write_text('{"enabled": false}', encoding="utf-8")
    agent.CONFIG["auto_accept"] = False
    assert _one_tick(agent, monkeypatch) == [False]
    pref_file.write_text('{"enabled": true}', encoding="utf-8")
    assert _one_tick(agent, monkeypatch) == [True]


def test_unsaved_set_config_lasts_at_most_one_tick(agent, pref_file,
                                                   monkeypatch):
    """A set_config whose save never landed must not stand: the control
    would show, and the agent act on, a state RC's own loop does not hold."""
    pref_file.write_text('{"enabled": false}', encoding="utf-8")
    res = agent.execute_command({"cmd": "set_config", "auto_accept": True})
    assert res["ok"] is True and agent.CONFIG["auto_accept"] is True
    assert _one_tick(agent, monkeypatch) == [False]


def test_tick_syncs_even_with_league_closed(agent, pref_file, monkeypatch):
    """The snapshot is posted with League closed too, so the control must be
    truthful before a client exists (the sync is not behind the port check)."""
    pref_file.write_text('{"enabled": true}', encoding="utf-8")
    agent.CONFIG["auto_accept"] = False
    agent._lcu["port"] = None
    seen: list = []

    def _sleep(_s):
        raise _Stop()

    monkeypatch.setattr(agent, "ensure_lcu_conn", lambda: False)
    monkeypatch.setattr(agent, "time", types.SimpleNamespace(sleep=_sleep))
    with mock.patch.object(agent, "lcu_request",
                           side_effect=lambda *a, **k: seen.append(a)):
        with pytest.raises(_Stop):
            agent._auto_features_loop()
    assert agent.CONFIG["auto_accept"] is True
    assert seen == [], "no LCU call is made while League is closed"


# ------------------------------------------------------------- fail-soft


def test_unexpected_fault_keeps_config_and_logs_once(agent, monkeypatch,
                                                     caplog):
    def _boom():
        raise RuntimeError("synthetic")

    monkeypatch.setattr(pref, "is_enabled", _boom)
    agent.CONFIG["auto_accept"] = True
    with caplog.at_level(logging.WARNING, logger="lcu_agent"):
        agent._sync_auto_accept_from_pref()
        agent._sync_auto_accept_from_pref()
    assert agent.CONFIG["auto_accept"] is True
    hits = [r for r in caplog.records
            if "auto-accept preference" in r.getMessage()]
    assert len(hits) == 1, [r.getMessage() for r in caplog.records]
    assert "synthetic" not in hits[0].getMessage()


def test_a_good_read_after_a_fault_re_arms_the_warning(agent, pref_file,
                                                       monkeypatch, caplog):
    real = pref.is_enabled

    def _boom():
        raise RuntimeError("synthetic")

    pref_file.write_text('{"enabled": true}', encoding="utf-8")
    with caplog.at_level(logging.WARNING, logger="lcu_agent"):
        monkeypatch.setattr(pref, "is_enabled", _boom)
        agent._sync_auto_accept_from_pref()
        monkeypatch.setattr(pref, "is_enabled", real)
        agent._sync_auto_accept_from_pref()
        monkeypatch.setattr(pref, "is_enabled", _boom)
        agent._sync_auto_accept_from_pref()
    hits = [r for r in caplog.records
            if "auto-accept preference" in r.getMessage()]
    assert len(hits) == 2, [r.getMessage() for r in caplog.records]


def test_boot_default_literal_stays_off():
    """CONFIG's literal is the value before the first read; it stays the
    pref module's OFF default (the 08506e2af drift guard still binds)."""
    import lcu_agent
    import ast
    src = Path(lcu_agent.__file__).read_text(encoding="utf-8")
    tree = ast.parse(src)
    for node in tree.body:
        if (isinstance(node, ast.Assign)
                and any(getattr(t, "id", None) == "CONFIG"
                        for t in node.targets)):
            lit = ast.literal_eval(node.value)
            assert lit["auto_accept"] is pref._DEFAULT_ENABLED is False
            return
    pytest.fail("CONFIG literal not found in tools/lcu_agent.py")
