"""Regression tests for the DEFERRED (frozen-file) silent-exception batch.

Spec: docs/specs/2026-07-19-silent-except-triage.md section 4.

Every test here MUST fail while the error is swallowed:
  - recovery shape  : inject a fault, assert the state stays consistent anyway
  - observability   : inject a fault, assert a record exists at a level an
                      operator surface actually reads

Files under test (all CLAUDE.md frozen-list, edited under an explicit
operator grant for this batch):
  core/log_setup.py, lcu/lcu_client.py, app/_game_lifecycle.py
"""

import logging
from datetime import date, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest


# --------------------------------------------------------------------------
# A1  core/log_setup.py:70  - day-roll drops the old stream even if close()
#     raises. Otherwise self.stream keeps pointing at YESTERDAY's open handle
#     and every later record lands in the wrong file for the process lifetime.
# --------------------------------------------------------------------------

def _make_handler(tmp_path):
    from core.log_setup import DailyRotatingFileHandler

    return DailyRotatingFileHandler(
        tmp_path, maxBytes=10 * 1024 * 1024, backupCount=1,
        encoding="utf-8", delay=False,
    )


def test_day_roll_drops_stream_when_close_raises(tmp_path):
    """RED before the fix: close() raising leaves self.stream installed."""
    h = _make_handler(tmp_path)
    try:
        yesterday = date.today() - timedelta(days=1)
        h._current_day = yesterday
        h.baseFilename = str(h._path_for(yesterday))

        class _BadStream:
            closed = False

            def close(self):
                raise OSError("close refused by the OS")

            def write(self, _s):  # pragma: no cover - must never be reached
                raise AssertionError("wrote to the stale day's stream")

            def flush(self):
                pass

        h.stream = _BadStream()

        rec = logging.LogRecord("rc.test", logging.INFO, __file__, 1,
                                "hello", None, None)
        assert h.shouldRollover(rec) == 0

        # The contract: the stale handle is gone, so FileHandler.emit reopens
        # at the NEW baseFilename.
        assert h.stream is None, (
            "day-roll left the previous day's stream installed after a failed "
            "close(); every later record would land in yesterday's file"
        )
        assert h.baseFilename == str(h._path_for(date.today()))
    finally:
        try:
            h.stream = None
            h.close()
        except OSError:
            pass


def test_day_roll_record_lands_in_todays_file_after_failed_close(tmp_path):
    """End-to-end recovery shape: the record must reach today's file."""
    h = _make_handler(tmp_path)
    try:
        yesterday = date.today() - timedelta(days=1)
        h._current_day = yesterday
        h.baseFilename = str(h._path_for(yesterday))

        class _BadStream:
            def close(self):
                raise OSError("close refused")

            def write(self, _s):  # pragma: no cover
                raise AssertionError("wrote to the stale day's stream")

            def flush(self):
                pass

        h.stream = _BadStream()
        h.setFormatter(logging.Formatter("%(message)s"))
        h.emit(logging.LogRecord("rc.test", logging.INFO, __file__, 1,
                                 "MARKER-TODAY", None, None))
        h.flush()

        today_file = h._path_for(date.today())
        assert today_file.exists()
        assert "MARKER-TODAY" in today_file.read_text(encoding="utf-8")
    finally:
        try:
            h.close()
        except OSError:
            pass


# --------------------------------------------------------------------------
# A2  lcu/lcu_client.py:248 - the THREAD auto-accept loop swallowed a raising
#     tick with zero trace. Its async sibling at :258 already logs with
#     exc_info=True and its comment cites the 2026-07-04 silent death that
#     "left no logged trace". Same hazard, same fix.
# --------------------------------------------------------------------------

def test_thread_auto_accept_loop_records_a_raising_tick(caplog):
    """RED before the fix: no log record at all is emitted."""
    from lcu.lcu_client import LcuClient

    client = LcuClient.__new__(LcuClient)
    client._running = True

    calls = {"n": 0}

    def _boom():
        calls["n"] += 1
        client._running = False          # one iteration only
        raise RuntimeError("tick exploded")

    client._auto_accept_tick = _boom

    with caplog.at_level(logging.DEBUG, logger="rc.lcu"):
        LcuClient._auto_accept_loop(client, 0.0)

    assert calls["n"] == 1
    assert caplog.records, (
        "a raising auto-accept tick left NO log record in the thread loop; "
        "the async sibling logs it with exc_info"
    )
    assert any(r.exc_info for r in caplog.records), (
        "the tick failure was recorded without a traceback (exc_info)"
    )


# --------------------------------------------------------------------------
# A3/A4  app/_game_lifecycle.py:147 / :157 - post-game collection and the
#     rewind live writer are both fire-and-forget game-end hooks whose ONLY
#     failure signal was logger.debug. The rewind writer has no success log
#     at all, so a permanently broken path is indistinguishable from a path
#     that was never wired (the RM-107 shape).
# --------------------------------------------------------------------------

def _fake_app():
    app = SimpleNamespace()
    app._tft_mode = False
    app._arena_mode = False
    app._brawl_mode = False
    app._aram_mode = False
    app._game_state = None
    app._tft_coach = None
    app._tft_worker = None
    app._coach = None
    app._sr_aram_worker = None
    app.data = {}
    app._write_data = MagicMock()
    app._update_envelope = MagicMock()
    return app


def _manager():
    from app._game_lifecycle import GameLifecycleManager

    return GameLifecycleManager(_fake_app())


def test_rewind_live_writer_failure_is_visible(monkeypatch, caplog):
    """RED before the fix: the only record is DEBUG."""
    import lib.rewind_live_writer as rlw

    def _boom(*_a, **_kw):
        raise RuntimeError("scheduler refused")

    monkeypatch.setattr(rlw, "schedule_live_insert", _boom)

    mgr = _manager()
    with caplog.at_level(logging.WARNING, logger="rc.app.lifecycle"):
        mgr.on_game_end()

    assert any("rewind" in r.getMessage().lower() for r in caplog.records), (
        "rewind live-writer trigger failed with no record at WARNING or above; "
        "a permanently broken writer is invisible to every operator surface"
    )


def test_postgame_trigger_failure_is_visible(monkeypatch, caplog):
    """RED before the fix: the only record is DEBUG."""
    import app._game_lifecycle as gl

    def _boom(*_a, **_kw):
        raise RuntimeError("collector unavailable")

    monkeypatch.setattr(gl, "HAS_POSTGAME", True)
    monkeypatch.setattr(gl, "_get_postgame_collector", _boom, raising=False)

    mgr = _manager()
    with caplog.at_level(logging.WARNING, logger="rc.app.lifecycle"):
        mgr.on_game_end()

    assert any("postgame" in r.getMessage().lower() for r in caplog.records), (
        "postgame trigger failed with no record at WARNING or above"
    )


# --------------------------------------------------------------------------
# D-CLASS DEMONSTRATION (report-only, NOT a fix)
# lcu/lcu_client.py:173-183 and :384 - _request() returns None on every
# transport / non-2xx / JSON error. That return contract is why the handlers
# at lcu/lcu_rune_writer.py:888 and :996 cannot be narrowed: no exception can
# reach them. This test PASSES today; it exists to pin the contract so the
# proposal in the batch report has a concrete artifact.
# --------------------------------------------------------------------------

@pytest.mark.parametrize(
    "exc",
    [
        OSError("connection refused"),
        TimeoutError("timed out"),
        ValueError("not json"),
    ],
)
def test_request_swallows_transport_errors_and_returns_none(monkeypatch, exc):
    """Pins the CURRENT contract. Do not 'fix' this in a silent-except batch."""
    import lcu.lcu_client as lc

    client = lc.LcuClient.__new__(lc.LcuClient)
    client._port = 1234
    client._auth = "dGVzdA=="
    client._ssl = None

    def _boom(*_a, **_kw):
        raise exc

    monkeypatch.setattr(lc.urllib.request, "urlopen", _boom)
    # Defeat the one lockfile-rotation retry so the test is single-shot.
    monkeypatch.setattr(lc.LcuClient, "_refresh_conn_if_changed",
                        lambda self: None)

    result = client._request("GET", "/lol-summoner/v1/current-summoner")

    assert result is None, (
        "_request no longer returns None on a transport error - the D-class "
        "blockers at lcu_rune_writer.py:888/996 may now be narrowable"
    )
