"""Audit L-02: _atomic_write_json retry + tmp cleanup; _reap_orphan_lockfile_tmps.

RM-777: _port_available's probe set SO_REUSEADDR on every OS. On Windows that
lets the probe bind a port another socket holds with the same option, so the
preflight reported a held port as free. The probe now sets SO_REUSEADDR only
where asyncio's create_server would (``_PROBE_REUSE_ADDRESS``: POSIX), i.e. it
binds the way the real servers bind.
"""
from __future__ import annotations

import os
import socket
import sys
import types
from unittest.mock import patch

import pytest

from agents import _supervisor_common as supcommon
from agents._supervisor_common import _atomic_write_json, _reap_orphan_lockfile_tmps
from tests._replace_faults import scoped_fs_fault
from tests._sleep_probe import record_sleeps


class TestAtomicWriteJsonRetry:
    def test_succeeds_on_first_attempt(self, tmp_path):
        target = tmp_path / "lockfile"
        _atomic_write_json(target, {"pid": 1})
        import json
        assert json.loads(target.read_text()) == {"pid": 1}

    def test_no_tmp_sibling_after_success(self, tmp_path):
        target = tmp_path / "lockfile"
        _atomic_write_json(target, {"pid": 2})
        tmps = list(tmp_path.glob("lockfile.*.tmp"))
        assert tmps == []

    def test_retries_permissionerror_twice_then_succeeds(self, tmp_path):
        target = tmp_path / "lockfile"
        def flaky_replace(real, src, dst, *a, **kw):
            if rec.attempts < 3:
                raise PermissionError("transient")
            real(src, dst, *a, **kw)

        # RM-464: thread scoping still faulted every same-thread replace in the
        # process; scoped_fs_fault keys on the destination under tmp_path and
        # proves it with a control replace outside tmp_path.
        with record_sleeps() as sleeps, \
             scoped_fs_fault("replace", tmp_path, flaky_replace) as rec:
            _atomic_write_json(target, {"pid": 3})

        assert rec.attempts == 3
        # Assert the VALUES, not a bare call_count. `patch("mod.time.sleep")`
        # is process-wide (mod.time IS the global time module), so a bare count
        # tallies every thread's sleeps - that is how this read 21378 on CI
        # against an implementation hard-bounded at 2. See tests/_sleep_probe.py.
        # RM-261: the writer delegates to core.polled_json, so the backoff is
        # that module's schedule (first two steps for two failures).
        from core import polled_json
        assert sleeps == list(polled_json._REPLACE_RETRY_DELAYS_S[:2])
        assert target.exists()
        tmps = list(tmp_path.glob("lockfile.*.tmp"))
        assert tmps == [], "tmp must be cleaned up even after retries"

    def test_final_failure_raises_and_cleans_tmp(self, tmp_path):
        target = tmp_path / "lockfile"
        def always_fail(real, src, dst, *a, **kw):
            raise PermissionError("always")

        # Scoping matters more here than in the retry test: an unscoped
        # `patch("os.replace", side_effect=PermissionError)` raises in EVERY
        # thread for the duration, so a concurrent atomic write anywhere else in
        # the worker process fails for a reason that has nothing to do with it.
        # RM-464: scoped by destination (tmp_path), not merely by thread.
        with record_sleeps(), \
             scoped_fs_fault("replace", tmp_path, always_fail):
            with pytest.raises(PermissionError):
                _atomic_write_json(target, {"pid": 4})

        tmps = list(tmp_path.glob("lockfile.*.tmp"))
        assert tmps == [], "tmp must be unlinked even on final failure"


class TestReapOrphanLockfileTmps:
    def test_dead_pid_file_removed(self, tmp_path, monkeypatch):
        monkeypatch.setattr("agents._supervisor_common.STATE_DIR", tmp_path)
        dead_tmp = tmp_path / "lockfile.99999.tmp"
        dead_tmp.write_text("{}", encoding="utf-8")

        with patch("agents._supervisor_common._pid_alive", return_value=False):
            _reap_orphan_lockfile_tmps()

        assert not dead_tmp.exists()

    def test_live_pid_file_preserved(self, tmp_path, monkeypatch):
        monkeypatch.setattr("agents._supervisor_common.STATE_DIR", tmp_path)
        live_tmp = tmp_path / f"lockfile.{os.getpid()}.tmp"
        live_tmp.write_text("{}", encoding="utf-8")

        with patch("agents._supervisor_common._pid_alive", return_value=True):
            _reap_orphan_lockfile_tmps()

        assert live_tmp.exists()

    def test_malformed_name_skipped(self, tmp_path, monkeypatch):
        monkeypatch.setattr("agents._supervisor_common.STATE_DIR", tmp_path)
        bad = tmp_path / "lockfile.notapid.tmp"
        bad.write_text("{}", encoding="utf-8")
        _reap_orphan_lockfile_tmps()
        assert bad.exists()

    def test_mixed_dead_and_live(self, tmp_path, monkeypatch):
        monkeypatch.setattr("agents._supervisor_common.STATE_DIR", tmp_path)
        dead = tmp_path / "lockfile.11111.tmp"
        live = tmp_path / "lockfile.22222.tmp"
        dead.write_text("{}", encoding="utf-8")
        live.write_text("{}", encoding="utf-8")

        def pid_alive(pid):
            return pid == 22222

        with patch("agents._supervisor_common._pid_alive", side_effect=pid_alive):
            _reap_orphan_lockfile_tmps()

        assert not dead.exists()
        assert live.exists()


class TestPortAvailableReuse:
    """RM-777. Every assertion compares against the module's own per-OS
    constant; only the two tests pinning the constant's value are OS-gated."""

    def test_reuse_option_follows_the_module_constant(self, monkeypatch):
        calls: list[tuple] = []

        class _FakeSock:
            def __init__(self, *_a):
                pass

            def setsockopt(self, *args):
                calls.append(("setsockopt",) + args)

            def bind(self, addr):
                calls.append(("bind", addr))

            def close(self):
                calls.append(("close",))

        fake = types.SimpleNamespace(
            AF_INET=socket.AF_INET, SOCK_STREAM=socket.SOCK_STREAM,
            SOL_SOCKET=socket.SOL_SOCKET, SO_REUSEADDR=socket.SO_REUSEADDR,
            socket=_FakeSock,
        )
        # Swap the module's socket REFERENCE only: patching socket.socket
        # itself would reach every thread in the worker.
        monkeypatch.setattr(supcommon, "socket", fake)
        assert supcommon._port_available("127.0.0.1", 1) is True
        reuse = [c for c in calls if c[0] == "setsockopt" and c[2] == socket.SO_REUSEADDR]
        assert bool(reuse) is supcommon._PROBE_REUSE_ADDRESS, calls
        assert calls[-2:] == [("bind", ("127.0.0.1", 1)), ("close",)]

    def test_constant_matches_asyncio_create_server_default(self):
        # asyncio.base_events.BaseEventLoop.create_server: reuse_address=None
        # means `os.name == "posix" and sys.platform != "cygwin"`.
        expected = os.name == "posix" and sys.platform != "cygwin"
        assert supcommon._PROBE_REUSE_ADDRESS is expected

    def test_port_held_with_so_reuseaddr_reads_as_busy(self):
        holder = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            holder.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            holder.bind(("127.0.0.1", 0))
            holder.listen()
            port = holder.getsockname()[1]
            assert supcommon._port_available("127.0.0.1", port) is False
        finally:
            holder.close()

    def test_port_held_without_options_reads_as_busy(self):
        holder = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            holder.bind(("127.0.0.1", 0))
            holder.listen()
            port = holder.getsockname()[1]
            assert supcommon._port_available("127.0.0.1", port) is False
        finally:
            holder.close()

    def test_port_with_only_a_time_wait_left_reads_as_free(self):
        # The restart shape (RM-761's reason not to go exclusive): the old
        # listener closed first on an accepted connection, so the port carries
        # a TIME_WAIT entry and no listener. The real bind succeeds here, so
        # the preflight must not read it as busy. The old listener binds the
        # way asyncio's create_server does on this OS: Linux keeps a TIME_WAIT
        # entry reusable only when the listener it came from set SO_REUSEADDR
        # too (measured under WSL: a plain listener reds this on Linux).
        srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        if supcommon._PROBE_REUSE_ADDRESS:
            srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        srv.bind(("127.0.0.1", 0))
        srv.listen()
        port = srv.getsockname()[1]
        cli = socket.create_connection(("127.0.0.1", port), timeout=5)
        try:
            conn, _ = srv.accept()
            conn.close()
            cli.recv(1)
        finally:
            cli.close()
            srv.close()
        assert supcommon._port_available("127.0.0.1", port) is True


@pytest.mark.skipif(os.name != "nt", reason="pins the Windows value")
def test_probe_reuse_constant_is_off_on_windows():
    assert supcommon._PROBE_REUSE_ADDRESS is False


@pytest.mark.skipif(os.name == "nt", reason="pins the POSIX value")
def test_probe_reuse_constant_is_on_off_windows():
    assert supcommon._PROBE_REUSE_ADDRESS is (sys.platform != "cygwin")
