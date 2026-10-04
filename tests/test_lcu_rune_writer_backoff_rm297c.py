"""RM-297c: a permanently rejected rune write must not retry at 1 Hz forever.

Before: _last_applied_* recorded SUCCESS only, so every 1 s poll redid the
whole GET + DELETEs + 3 POSTs, and the single WARNING said nothing about WHY
(the frozen client returns None instead of raising).
"""
from __future__ import annotations

import logging
import sys
import threading
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import lcu.lcu_rune_writer as rw  # noqa: E402
from lcu.lcu_rune_writer import RuneWriter  # noqa: E402


class _Lcu:
    def __init__(self, sessions):
        self.sessions = list(sessions)

    def get_champ_select(self):
        return self.sessions.pop(0) if self.sessions else None


def _writer(sessions, apply_result=False, why="http 403"):
    w = RuneWriter.__new__(RuneWriter)
    w._lcu = _Lcu(sessions)
    w._stop_event = threading.Event()
    w._last_applied_champion = ""
    w._last_applied_mode = ""
    w._in_champ_select = False
    w._detect_game_mode = lambda: "ARAM"
    w._sync_spells = lambda s, m: True
    w._detect_my_champion = lambda s: (s or {}).get("champ", "")
    w.calls = 0

    def _apply(c, m):
        w.calls += 1
        if not apply_result:
            w.last_write_error = why
        return apply_result

    w._apply_runes = _apply
    return w


def test_failure_backs_off_and_warns_once(caplog):
    caplog.set_level(logging.DEBUG, logger=rw._log.name)
    clock = [1000.0]
    w = _writer([{"champ": "Sett"}] * 200)
    with mock.patch.object(rw.time, "monotonic", lambda: clock[0]):
        for _ in range(120):  # 120 s of 1 Hz polls
            w._poll()
            clock[0] += 1.0
    # 2+4+8+16+32 s gaps then the circuit opens at 6 attempts.
    assert w.calls == RuneWriter._FAIL_GIVE_UP
    warns = [r.getMessage() for r in caplog.records
             if r.levelno >= logging.WARNING and "rune write failed" in r.getMessage()]
    assert len(warns) == 1
    assert "http 403" in warns[0]


def test_backoff_resets_on_champion_change_and_on_exit():
    clock = [0.0]
    w = _writer([{"champ": "Sett"}, {"champ": "Olaf"}, None, {"champ": "Olaf"}])
    with mock.patch.object(rw.time, "monotonic", lambda: clock[0]):
        w._poll()      # Sett fails
        w._poll()      # Olaf: different pick -> immediate attempt
        w._poll()      # champ select ends -> re-arm
        w._poll()      # Olaf in a new champ select -> immediate attempt
    assert w.calls == 3


def test_success_clears_failure_state():
    w = _writer([{"champ": "Sett"}], apply_result=True)
    w._poll()
    assert w.calls == 1 and w._fail_count == 0


class _Client:
    def __init__(self, err):
        self._err = err

    def last_request_error(self):
        return self._err

    def _request(self, method, endpoint, data=None):
        return None

    def get_all_rune_pages(self):
        return []


def test_write_page_reports_the_client_reason(caplog):
    caplog.set_level(logging.WARNING, logger=rw._log.name)
    w = RuneWriter.__new__(RuneWriter)
    w._lcu = _Client("http 400")
    with mock.patch.object(rw.time, "sleep", lambda s: None):
        ok = w._write_page("RC: x", 8100, 8000, list(range(9)))
    assert ok is False
    assert w.last_write_error == "http 400"
    assert any("http 400" in r.getMessage() for r in caplog.records)


def test_frozen_client_records_the_http_status():
    import urllib.error
    from lcu import lcu_client as lc
    c = lc.LcuClient()
    c._port, c._auth = 1, "x"

    def boom(req, *a, **kw):
        raise urllib.error.HTTPError(req.full_url, 403, "Forbidden", {}, None)

    with mock.patch.object(lc.urllib.request, "urlopen", boom), \
            mock.patch.object(c, "_refresh_conn_if_changed", lambda: None), \
            mock.patch("core.lcu_pool.pool_enabled", lambda: False):
        assert c._request("POST", "/lol-perks/v1/pages", {"a": 1}) is None
        assert c.last_request_error() == "http 403"
        c._port = None
        assert c._request("GET", "/x") is None
        assert c.last_request_error() == "not connected"
