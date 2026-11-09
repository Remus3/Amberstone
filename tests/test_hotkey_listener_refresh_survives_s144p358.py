"""S144-P-358 - the hotkey listener's decision-refresh thread survives every transport fault.

``tools/hotkey_listener.py`` runs ``_refresh_loop`` on a daemon thread under ``pythonw.exe`` (the RC-HotkeyListener
logon task, no console). ``DecisionCache.refresh`` used to catch only ``urllib.error.URLError`` and ``ValueError``,
but ``urlopen`` wraps only the CONNECT phase in ``URLError``: a read timeout on the response body raises a bare
``TimeoutError`` / ``socket.timeout``, and a server that drops the socket mid-response raises
``http.client.RemoteDisconnected`` (an ``OSError``), ``http.client.IncompleteRead`` or ``BadStatusLine`` (plain
``HTTPException``). Any of those escaped ``refresh``, ended ``_refresh_loop`` and killed the thread silently, after which the
hotkeys read a frozen decision cache for the rest of the process lifetime. The dispatcher thread kept running, so
nothing in the log said the cache had stopped refreshing.

Pinned here: ``refresh`` returns quietly and keeps the last good cache on each of those faults, and the loop keeps
polling even if ``refresh`` itself raises something unforeseen.
"""
from __future__ import annotations

import http.client
import socket
import sys
import threading
from pathlib import Path

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

# tools.hotkey_listener binds user32 via ctypes.WinDLL at import (Windows-only)
if sys.platform != "win32":
    pytest.skip("Windows-only Win32 hotkey listener", allow_module_level=True)

import tools.hotkey_listener as hk  # noqa: E402
from tests._module_view import bind_urlopen  # noqa: E402
from tests._timing_budget import fleet_test_guard  # noqa: E402

_FAULTS = [
    TimeoutError("read timed out"),
    socket.timeout("read timed out"),
    ConnectionResetError("reset by peer"),
    http.client.RemoteDisconnected("closed without response"),
    http.client.IncompleteRead(b"par", 10),
    http.client.BadStatusLine("garbage"),
    UnicodeDecodeError("utf-8", b"\xff", 0, 1, "invalid start byte"),
]


class _Resp:
    def __init__(self, body: bytes | Exception):
        self._body = body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self):
        if isinstance(self._body, Exception):
            raise self._body
        return self._body


def _seed(cache: "hk.DecisionCache") -> None:
    cache._pending = [{"id": "d1", "created_at_unix": 1}]
    cache._last_fetch_ok = 5.0


@pytest.mark.parametrize("fault", _FAULTS, ids=lambda f: type(f).__name__)
def test_refresh_swallows_a_fault_raised_while_reading_the_body(monkeypatch, fault):
    bind_urlopen(monkeypatch, hk, lambda *a, **k: _Resp(fault))
    cache = hk.DecisionCache()
    _seed(cache)
    assert cache.refresh() is None
    assert cache.topmost() == {"id": "d1", "created_at_unix": 1}
    assert cache._last_fetch_ok == 5.0


@pytest.mark.parametrize("fault", _FAULTS, ids=lambda f: type(f).__name__)
def test_refresh_swallows_a_fault_raised_by_urlopen_itself(monkeypatch, fault):
    def boom(*a, **k):
        raise fault

    bind_urlopen(monkeypatch, hk, boom)
    cache = hk.DecisionCache()
    _seed(cache)
    assert cache.refresh() is None
    assert cache.topmost() == {"id": "d1", "created_at_unix": 1}


def test_refresh_still_publishes_a_good_payload(monkeypatch):
    """Positive control: the broadened guard must not swallow the success path."""
    body = b'{"pending": [{"id": "d2", "created_at_unix": 9}]}'
    bind_urlopen(monkeypatch, hk, lambda *a, **k: _Resp(body))
    cache = hk.DecisionCache()
    _seed(cache)
    cache.refresh()
    assert cache.topmost() == {"id": "d2", "created_at_unix": 9}
    assert cache._last_fetch_ok > 5.0


def test_refresh_loop_keeps_polling_after_refresh_raises(monkeypatch):
    """The loop is the last line: even a fault refresh does not know about must not end the thread."""
    monkeypatch.setattr(hk, "POLL_S", 0.001)
    stop = threading.Event()
    calls: list[int] = []

    class _Cache:
        def refresh(self):
            calls.append(1)
            if len(calls) == 1:
                raise RuntimeError("unforeseen")
            if len(calls) >= 3:
                stop.set()

    t = threading.Thread(target=hk._refresh_loop, args=(_Cache(), stop), daemon=True)
    t.start()
    t.join(timeout=fleet_test_guard.budget(5))
    assert not t.is_alive(), "the refresh loop did not stop on the event"
    assert len(calls) >= 3, "the loop ended after the first raise instead of polling on"
