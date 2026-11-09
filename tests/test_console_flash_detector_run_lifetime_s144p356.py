"""S144-P-356 - tools/console_flash_detector.run() closes its log stream on EVERY exit path.

``run`` opens the append-only log (``_Stream``) first, then builds the ``_Win32`` binding and installs the
SetWinEventHook. The file-open census (``test_file_open_lifetime_census_s144p355``) names the ``_Stream`` handle as
owned by ``run``, "closed on both of its exit paths". Measured 2026-11-07 that was not true: ``_Win32()`` (two
``ctypes.WinDLL`` loads and the argtypes setup), the ``SetWinEventHook`` call, the START line and the hook-lost
branch all ran OUTSIDE any try/finally, so a raise from any of them stranded the open log handle (and, for a
raise after the hook was installed, the hook itself). These tests drive ``run`` with a fake Win32 binding and a
recording stream and pin the repaired contract: whatever raises, the stream is closed, and an installed hook is
unhooked exactly once.
"""
from __future__ import annotations

import sys

import pytest

from tools import console_flash_detector as det

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="the detector is Windows-only")


class _RecordingStream(det._Stream):
    """A real ``_Stream`` that remembers close() and can fail a chosen write."""

    fail_on: str | None = None
    instances: list["_RecordingStream"] = []

    def __init__(self, path):
        super().__init__(path)
        self.closed = 0
        self.lines: list[str] = []
        type(self).instances.append(self)

    def write(self, line):
        if self.fail_on and line.startswith(self.fail_on):
            raise OSError("disk full (injected)")
        self.lines.append(line)
        super().write(line)

    def close(self):
        self.closed += 1
        super().close()


class _FakeUser32:
    def __init__(self, hook):
        self._hook = hook
        self.unhooked: list[object] = []

    def SetWinEventHook(self, *_a):  # noqa: N802 - mirrors the Win32 name
        return self._hook

    def PeekMessageW(self, *_a):  # noqa: N802
        return 0

    def TranslateMessage(self, *_a):  # noqa: N802
        return 0

    def DispatchMessageW(self, *_a):  # noqa: N802
        return 0

    def UnhookWinEvent(self, hook):  # noqa: N802
        self.unhooked.append(hook)
        return 1


def _install(monkeypatch, *, hook=1234, win32_raises=False, fail_on=None):
    _RecordingStream.instances = []
    _RecordingStream.fail_on = fail_on
    monkeypatch.setattr(det, "_Stream", _RecordingStream)
    user32 = _FakeUser32(hook)

    class _FakeWin32:
        def __init__(self):
            if win32_raises:
                raise OSError("user32 unavailable (injected)")
            self.user32 = user32

    monkeypatch.setattr(det, "_Win32", _FakeWin32)
    return user32


def test_normal_run_closes_stream_and_unhooks_once(tmp_path, monkeypatch):
    user32 = _install(monkeypatch)
    out = tmp_path / "cap.log"
    assert det.run(0.0, out) == 0
    (stream,) = _RecordingStream.instances
    assert stream.closed == 1
    assert user32.unhooked == [1234]
    assert stream.lines[0].startswith("START ") and stream.lines[-1].startswith("END ")
    assert out.read_bytes().count(b"\r") == 0


def test_win32_binding_failure_still_closes_stream(tmp_path, monkeypatch):
    _install(monkeypatch, win32_raises=True)
    with pytest.raises(OSError, match="user32 unavailable"):
        det.run(0.0, tmp_path / "cap.log")
    (stream,) = _RecordingStream.instances
    assert stream.closed == 1


def test_hook_not_installed_returns_1_closes_stream_and_never_unhooks(tmp_path, monkeypatch):
    user32 = _install(monkeypatch, hook=0)
    assert det.run(0.0, tmp_path / "cap.log") == 1
    (stream,) = _RecordingStream.instances
    assert stream.closed == 1
    assert user32.unhooked == []
    assert any(line.startswith("HOOK LOST") for line in stream.lines)
    assert stream.lines[-1].startswith("END ")


def test_write_failure_on_the_hook_lost_line_still_closes_stream(tmp_path, monkeypatch):
    _install(monkeypatch, hook=0, fail_on="HOOK LOST")
    with pytest.raises(OSError, match="disk full"):
        det.run(0.0, tmp_path / "cap.log")
    (stream,) = _RecordingStream.instances
    assert stream.closed == 1


def test_write_failure_on_the_start_line_still_closes_stream_and_installs_no_hook(tmp_path, monkeypatch):
    user32 = _install(monkeypatch, fail_on="START ")
    with pytest.raises(OSError, match="disk full"):
        det.run(0.0, tmp_path / "cap.log")
    (stream,) = _RecordingStream.instances
    assert stream.closed == 1
    # START is written BEFORE the hook is installed, so a failing START line leaves no hook behind to unhook.
    assert user32.unhooked == []
