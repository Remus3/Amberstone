"""s144 true-audit cycle 83: core/auto_accept_pref.py + dashboard/routes_auto_accept.py.

Findings pinned here (each test is named for its finding):

F1  An absent or corrupt pref file meant auto-accept ON, while the dashboard
    "Auto Accept" control reads the LCU agent's CONFIG, whose boot default is
    OFF (tools/lcu_agent.py CONFIG, mirrored by dashboard/_lcu_inprocess.py).
    With no stored choice the UI said Off and RC's in-process loop still
    accepted every ready check - the s171 "silently always on regardless of
    the UI state" class. The default is now OFF, drift-guarded to the agent.
F2  A transient read failure (a sharing violation while the writer swaps the
    file in) returned the default instead of the stored choice. It now
    returns the last value this process read or wrote.
F3  A corrupt or unreadable file was swallowed with no log line at all. It
    is now logged once per distinct problem (the reader runs about 1 Hz during
    a ready check), and a good read re-arms the warning.
F4  set_enabled() coerced with bool(), so set_enabled("false") stored True.
    A non-bool is now a TypeError and nothing is written.
F5  POST accepted unknown keys silently.
F6  A failed save (OSError after the bounded replace retry) was a 500 with a
    traceback-less warning; it is now a 503 "retry" with the traceback
    logged, and an unexpected error is a traceback-logged generic 500.

The live data/auto_accept_pref.json is never touched: every test redirects
_PREF_PATH to tmp_path and a module fixture asserts the live bytes are
unchanged.
"""
from __future__ import annotations

import json
import logging
import sys
from pathlib import Path

import pytest

from core import auto_accept_pref as pref
from dashboard import routes_auto_accept as route

_ROOT = Path(__file__).resolve().parent.parent
_LIVE = _ROOT / "data" / "auto_accept_pref.json"


@pytest.fixture(scope="module", autouse=True)
def _live_pref_bytes_untouched():
    before = _LIVE.read_bytes() if _LIVE.exists() else None
    yield
    after = _LIVE.read_bytes() if _LIVE.exists() else None
    assert after == before, "live data/auto_accept_pref.json was modified"


@pytest.fixture(autouse=True)
def pref_file(tmp_path, monkeypatch):
    p = tmp_path / "auto_accept_pref.json"
    monkeypatch.setattr(pref, "_PREF_PATH", p)
    # Per-process memo + log dedupe start clean for every test.
    monkeypatch.setattr(pref, "_last_good", None)
    monkeypatch.setattr(pref, "_last_problem", None)
    return p


class FakeHandler:
    def __init__(self) -> None:
        self.path = "/api/lcu/auto-accept"
        self.sent = None

    def _send(self, status, body, ctype):
        self.sent = (status, body, ctype)


def _post(body):
    h = FakeHandler()
    route._serve_post(h, body)
    status, raw, _ = h.sent
    return status, json.loads(raw.decode("utf-8"))


def _get():
    h = FakeHandler()
    route._serve_get(h)
    status, raw, _ = h.sent
    return status, json.loads(raw.decode("utf-8"))


def _fail_read(exc):
    def _read_text(self, *a, **k):
        raise exc
    return _read_text


# ------------------------------------------------------------------ F1
def test_f1_absent_file_means_off(pref_file):
    assert not pref_file.exists()
    assert pref.is_enabled() is False


@pytest.mark.parametrize("raw", [
    "}{not json", "[1, 2, 3]", json.dumps({"other": 1}),
    json.dumps({"enabled": "yes"}), json.dumps({"enabled": 1}), "",
])
def test_f1_corrupt_file_means_off(pref_file, raw):
    pref_file.write_text(raw, encoding="utf-8")
    assert pref.is_enabled() is False


def test_f1_deeply_nested_file_means_off_and_never_raises(pref_file):
    # Verifier finding: json.loads raises RecursionError, not ValueError, on
    # a deeply nested document, which escaped is_enabled() and made GET a 500.
    pref_file.write_text("[" * 200000, encoding="utf-8")
    assert pref.is_enabled() is False
    assert _get() == (200, {"ok": True, "enabled": False})


def test_f1_non_utf8_file_means_off(pref_file):
    pref_file.write_bytes(b'\xff\xfe{"enabled": true}')
    assert pref.is_enabled() is False


def test_f1_default_matches_the_agent_boot_default():
    """The UI shows the agent's CONFIG; with no stored pref the in-process
    gate must agree with what the UI shows when the agent has just booted."""
    tools_dir = str(_ROOT / "tools")
    if tools_dir not in sys.path:
        sys.path.insert(0, tools_dir)
    import lcu_agent
    from dashboard import _lcu_inprocess
    assert pref._DEFAULT_ENABLED is lcu_agent.CONFIG["auto_accept"]
    assert pref._DEFAULT_ENABLED is _lcu_inprocess._AGENT_CONFIG_DEFAULTS["auto_accept"]


def test_f1_route_get_with_no_file_reports_off(pref_file):
    assert _get() == (200, {"ok": True, "enabled": False})


# ------------------------------------------------------------------ F2
def test_f2_transient_read_error_keeps_the_stored_choice(pref_file, monkeypatch):
    pref.set_enabled(True)
    assert pref.is_enabled() is True
    monkeypatch.setattr(Path, "read_text", _fail_read(PermissionError(13, "busy")))
    assert pref.is_enabled() is True


def test_f2_transient_read_error_keeps_a_stored_off(pref_file, monkeypatch):
    pref.set_enabled(False)
    monkeypatch.setattr(Path, "read_text", _fail_read(PermissionError(13, "busy")))
    assert pref.is_enabled() is False


def test_f2_transient_error_with_no_prior_read_is_off(pref_file, monkeypatch):
    pref_file.write_text(json.dumps({"enabled": True}), encoding="utf-8")
    monkeypatch.setattr(Path, "read_text", _fail_read(PermissionError(13, "busy")))
    assert pref.is_enabled() is False


def test_f2_a_good_read_refreshes_the_memo(pref_file, monkeypatch):
    # Another process (or the route) flipped the file: the memo follows the
    # file, not this process's last write.
    pref.set_enabled(True)
    pref_file.write_text(json.dumps({"enabled": False}), encoding="utf-8")
    assert pref.is_enabled() is False
    monkeypatch.setattr(Path, "read_text", _fail_read(OSError(5, "busy")))
    assert pref.is_enabled() is False


def test_f2_corrupt_content_does_not_reuse_the_memo(pref_file):
    pref.set_enabled(True)
    pref_file.write_text("}{", encoding="utf-8")
    assert pref.is_enabled() is False


# ------------------------------------------------------------------ F3
def _warnings(caplog):
    return [r for r in caplog.records
            if r.name == "rc.lcu" and r.levelno >= logging.WARNING]


def test_f3_corrupt_file_logs_once(pref_file, caplog):
    caplog.set_level(logging.DEBUG, logger="rc.lcu")
    pref_file.write_text("}{", encoding="utf-8")
    for _ in range(5):
        pref.is_enabled()
    assert len(_warnings(caplog)) == 1


def test_f3_good_read_rearms_the_warning(pref_file, caplog):
    caplog.set_level(logging.DEBUG, logger="rc.lcu")
    pref_file.write_text("}{", encoding="utf-8")
    pref.is_enabled()
    pref_file.write_text(json.dumps({"enabled": False}), encoding="utf-8")
    pref.is_enabled()
    pref_file.write_text("[]", encoding="utf-8")
    pref.is_enabled()
    assert len(_warnings(caplog)) == 2


def test_f3_absent_file_is_not_a_warning(pref_file, caplog):
    caplog.set_level(logging.DEBUG, logger="rc.lcu")
    pref.is_enabled()
    assert _warnings(caplog) == []


def test_f3_unreadable_file_logs_once(pref_file, monkeypatch, caplog):
    caplog.set_level(logging.DEBUG, logger="rc.lcu")
    monkeypatch.setattr(Path, "read_text", _fail_read(PermissionError(13, "busy")))
    for _ in range(3):
        pref.is_enabled()
    assert len(_warnings(caplog)) == 1


def test_f3_warning_never_carries_file_content(pref_file, caplog):
    caplog.set_level(logging.DEBUG, logger="rc.lcu")
    pref_file.write_text("SENTINEL-CONTENT-83 }{", encoding="utf-8")
    pref.is_enabled()
    assert "SENTINEL-CONTENT-83" not in caplog.text


# ------------------------------------------------------------------ F4
@pytest.mark.parametrize("val", ["false", "true", 1, 0, None, [], {}])
def test_f4_set_enabled_refuses_non_bool(pref_file, val):
    with pytest.raises(TypeError):
        pref.set_enabled(val)
    assert not pref_file.exists()


def test_f4_set_enabled_returns_and_memoizes_the_bool(pref_file):
    assert pref.set_enabled(False) is False
    assert pref._last_good is False
    assert pref.set_enabled(True) is True
    assert pref._last_good is True


def test_f4_failed_write_does_not_move_the_memo(pref_file, monkeypatch):
    pref.set_enabled(False)

    def boom(path, content):
        raise PermissionError(5, "denied")
    monkeypatch.setattr(pref, "atomic_write_text", boom)
    with pytest.raises(PermissionError):
        pref.set_enabled(True)
    assert pref._last_good is False


# ------------------------------------------------------------------ F5
def test_f5_post_unknown_key_is_400_and_writes_nothing(pref_file):
    status, payload = _post({"enabled": False, "extra": 1})
    assert status == 400 and payload["ok"] is False
    assert "extra" not in payload["error"]
    assert not pref_file.exists()


def test_f5_post_exact_body_still_works(pref_file):
    assert _post({"enabled": True}) == (200, {"ok": True, "enabled": True})
    assert pref.is_enabled() is True


# ------------------------------------------------------------------ F6
def test_f6_save_oserror_is_503_with_traceback(pref_file, monkeypatch, caplog):
    caplog.set_level(logging.DEBUG, logger="rc.web_dashboard")

    def boom(enabled):
        raise PermissionError(5, "SECRET-PATH-83 denied")
    monkeypatch.setattr(pref, "set_enabled", boom)
    status, payload = _post({"enabled": False})
    assert status == 503 and payload["ok"] is False
    assert "SECRET-PATH-83" not in json.dumps(payload)
    recs = [r for r in caplog.records if r.name == "rc.web_dashboard"]
    assert recs and recs[-1].exc_info is not None


def test_f6_unexpected_error_is_500_with_traceback(pref_file, monkeypatch, caplog):
    caplog.set_level(logging.DEBUG, logger="rc.web_dashboard")

    def boom(enabled):
        raise RuntimeError("RAW-83")
    monkeypatch.setattr(pref, "set_enabled", boom)
    status, payload = _post({"enabled": True})
    assert status == 500 and payload["ok"] is False
    assert "RAW-83" not in json.dumps(payload)
    recs = [r for r in caplog.records if r.name == "rc.web_dashboard"]
    assert recs and recs[-1].exc_info is not None


def test_f6_get_unexpected_error_is_500_with_traceback(monkeypatch, caplog):
    caplog.set_level(logging.DEBUG, logger="rc.web_dashboard")

    def boom():
        raise RuntimeError("RAW-GET-83")
    monkeypatch.setattr(pref, "is_enabled", boom)
    status, payload = _get()
    assert status == 500 and payload["ok"] is False
    assert "RAW-GET-83" not in json.dumps(payload)
    recs = [r for r in caplog.records if r.name == "rc.web_dashboard"]
    assert recs and recs[-1].exc_info is not None
