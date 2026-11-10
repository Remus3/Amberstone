"""
tests/test_start_daemon_slayer_hardening_s144t703.py.

S144-T-703 (true-audit lane, s144 cycle 269): tools/start_daemon_slayer.py is
the script RC's DsWatchdog starts windowless as DS's own child
(core/daemon_slayer_client.py _LAUNCHER / _spawn_child). It runs under
pythonw, so the startup log is the ONLY trace a failed start leaves. Three
weaknesses broke that promise:

1. main() wrapped only serve() in its try. Any raise from the port
   preflight (await_port: require_loopback's ValueError on a non-loopback
   host, socket.socket()'s OSError when the stack has no buffers) escaped
   main() with nothing logged - a silent death under pythonw.
2. _write_log_line opened the log with strict utf-8, so a message holding a
   lone surrogate (an exception text naming an undecodable path) raised
   UnicodeEncodeError - a ValueError, not the OSError it caught - out of
   _log_startup, whose contract is "never raises". On main()'s crash path
   that lost the UNHANDLED EXCEPTION line and the exit code 1.
3. The stderr echo caught bare Exception (the BLE001 class); it now names
   the failures a real stream produces (AttributeError for sys.stderr None
   under pythonw, OSError, ValueError) and lets a programming error surface.
"""
from __future__ import annotations

import importlib.util
import io
import os
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent


def _load():
    # The module chdirs to the project root at import; restore cwd.
    cwd = Path.cwd()
    try:
        spec = importlib.util.spec_from_file_location(
            "start_daemon_slayer_s144t703", _ROOT / "tools" / "start_daemon_slayer.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod
    finally:
        os.chdir(cwd)


SDS = _load()


@pytest.fixture
def logs(tmp_path, monkeypatch):
    monkeypatch.setattr(SDS, "_LOG_FILE", tmp_path / "logs" / "ds.log")
    monkeypatch.setattr(SDS, "_FALLBACK_LOG_FILE", tmp_path / "pd" / "ds.log")
    monkeypatch.setattr(sys, "stderr", io.StringIO())
    return tmp_path


def _never_serve(**_kw):
    raise AssertionError("serve() must not run when the preflight failed")


# -- 1. preflight raise is logged, exit 1, nothing started -------------------

def test_non_loopback_host_is_logged_and_exits_1():
    lines: list[str] = []
    code = SDS.main(host="192.0.2.5", port=8860, serve=_never_serve,
                    log=lines.append, window_s=0, poll_s=0,
                    holder_live=lambda: False)
    assert code == 1
    text = "\n".join(lines)
    assert "preflight" in text
    assert "ValueError" in text
    assert "non-loopback" in text


def test_bind_probe_oserror_is_logged_and_exits_1(monkeypatch):
    def boom(*_a, **_kw):
        raise OSError(10055, "no buffer space available")

    monkeypatch.setattr(SDS, "await_port", boom)
    lines: list[str] = []
    code = SDS.main(serve=_never_serve, log=lines.append, window_s=0,
                    poll_s=0, holder_live=lambda: False)
    assert code == 1
    text = "\n".join(lines)
    assert "preflight" in text
    assert "OSError" in text
    assert "no buffer space available" in text


def test_preflight_failure_reaches_the_real_log_file(logs, monkeypatch):
    def boom(*_a, **_kw):
        raise OSError("probe exploded")

    monkeypatch.setattr(SDS, "await_port", boom)
    assert SDS.main(serve=_never_serve, window_s=0, poll_s=0) == 1
    body = SDS._LOG_FILE.read_text(encoding="utf-8")
    assert "probe exploded" in body


def test_free_port_still_serves_and_returns_its_code(monkeypatch):
    # Characterization: the happy path is unchanged.
    monkeypatch.setattr(SDS, "await_port", lambda *a, **k: _free_handoff())
    lines: list[str] = []
    seen = {}

    def serve(**kw):
        seen.update(kw)
        return 3

    assert SDS.main(host="127.0.0.1", port=8860, serve=serve,
                    log=lines.append) == 3
    assert seen == {"host": "127.0.0.1", "port": 8860}
    assert any("starting serve_forever()" in ln for ln in lines)
    assert any("serve_forever() returned 3" in ln for ln in lines)


# -- 2. a non-encodable message is still written, never raised ---------------

def test_lone_surrogate_message_is_written_not_raised(logs):
    written = SDS._log_startup("bad path data/x/\udcff.json")
    assert written == SDS._LOG_FILE
    body = SDS._LOG_FILE.read_text(encoding="utf-8")
    assert "bad path data/x/\\udcff.json" in body


def test_write_log_line_survives_a_lone_surrogate(tmp_path):
    target = tmp_path / "a" / "log.txt"
    assert SDS._write_log_line(target, "x\udcffy\n") is True
    assert target.read_text(encoding="utf-8") == "x\\udcffy\n"


def test_crash_path_is_graded_with_a_free_port(logs, monkeypatch):
    # Force the FREE branch so the crash path runs whatever holds :8860.
    monkeypatch.setattr(SDS, "await_port", lambda *a, **k: _free_handoff())

    def serve(**_kw):
        raise RuntimeError("cannot open \udcff")

    assert SDS.main(serve=serve) == 1
    body = SDS._LOG_FILE.read_text(encoding="utf-8")
    assert "UNHANDLED EXCEPTION (exit 1)" in body
    assert "RuntimeError: cannot open \\udcff" in body


def _free_handoff():
    from core.port_handoff import FREE, Handoff
    return Handoff(FREE, 0.0)


# -- 3. the stderr echo names its expected failures --------------------------

def test_stderr_none_under_pythonw_is_tolerated(logs, monkeypatch):
    monkeypatch.setattr(sys, "stderr", None)
    assert SDS._log_startup("no console") == SDS._LOG_FILE
    assert "no console" in SDS._LOG_FILE.read_text(encoding="utf-8")


def test_stderr_oserror_is_tolerated(logs, monkeypatch):
    class Broken:
        def write(self, _s):
            raise OSError(22, "invalid handle")

        def flush(self):
            raise OSError(22, "invalid handle")

    monkeypatch.setattr(sys, "stderr", Broken())
    assert SDS._log_startup("bad handle") == SDS._LOG_FILE


def test_unexpected_stderr_error_surfaces_after_the_file_line(logs, monkeypatch):
    class Buggy:
        def write(self, _s):
            raise RuntimeError("programming error")

        def flush(self):
            pass

    monkeypatch.setattr(sys, "stderr", Buggy())
    with pytest.raises(RuntimeError, match="programming error"):
        SDS._log_startup("written first")
    # The durable trace was already on disk before the echo failed.
    assert "written first" in SDS._LOG_FILE.read_text(encoding="utf-8")
