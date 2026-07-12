"""Audit L-02: _atomic_write_json retry + tmp cleanup; _reap_orphan_lockfile_tmps."""
from __future__ import annotations

import os
from unittest.mock import patch

import pytest

from agents._supervisor_common import _atomic_write_json, _reap_orphan_lockfile_tmps


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
        calls = []
        real_replace = os.replace

        def flaky_replace(src, dst):
            calls.append(1)
            if len(calls) < 3:
                raise PermissionError("transient")
            real_replace(src, dst)

        with patch("agents._supervisor_common.time.sleep") as mock_sleep, \
             patch("os.replace", side_effect=flaky_replace):
            _atomic_write_json(target, {"pid": 3})

        assert len(calls) == 3
        assert mock_sleep.call_count == 2
        assert target.exists()
        tmps = list(tmp_path.glob("lockfile.*.tmp"))
        assert tmps == [], "tmp must be cleaned up even after retries"

    def test_final_failure_raises_and_cleans_tmp(self, tmp_path):
        target = tmp_path / "lockfile"

        with patch("os.replace", side_effect=PermissionError("always")), \
             patch("agents._supervisor_common.time.sleep"):
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
