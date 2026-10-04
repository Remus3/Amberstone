"""RM-375: both Perseus vault readers looped forever on a stdout that emits
non-JSON lines indefinitely. They now share `tools/_perseus_rpc.py`
`read_json_reply`, bounded by a skipped-line budget AND a wall-clock
deadline; on either bound the reader returns None (the existing "no reply").
"""
from __future__ import annotations

import io
import itertools
import json

from tools import _perseus_rpc as rpc


def _spew():
    lines = itertools.repeat("vault: still warming up...\n")
    return lambda: next(lines)


def test_endless_non_json_hits_the_skip_budget():
    calls = itertools.count()
    src = _spew()

    def readline():
        next(calls)
        return src()

    assert rpc.read_json_reply(readline, max_skipped=50, deadline_s=1e9) is None
    assert next(calls) == 51


def test_endless_non_json_hits_the_deadline():
    t = itertools.count(0.0, 1.0)
    assert rpc.read_json_reply(_spew(), max_skipped=10**9, deadline_s=5.0,
                               clock=lambda: next(t)) is None


def test_reply_after_chatter_is_returned():
    buf = io.StringIO("banner\n\n" + json.dumps({"id": 1, "result": 2}) + "\n")
    assert rpc.read_json_reply(buf.readline) == {"id": 1, "result": 2}


def test_eof_is_none():
    assert rpc.read_json_reply(io.StringIO("").readline) is None


class _FakeProc:
    def __init__(self, *a, **k):
        self.stdin = io.StringIO()
        lines = itertools.repeat("not json\n")
        self.stdout = type("S", (), {"readline": staticmethod(lambda: next(lines))})()

    def terminate(self):
        pass


def test_perseus_recall_returns_instead_of_looping(monkeypatch):
    from tools import perseus_recall as pr
    monkeypatch.setattr(pr.os.path, "exists", lambda p: True)
    monkeypatch.setattr(pr.subprocess, "Popen", _FakeProc)
    assert pr.recall("anything") == []


def test_perseus_sync_vault_rpc_returns_instead_of_looping(monkeypatch):
    from tools import perseus_sync as ps
    monkeypatch.setattr(ps.subprocess, "Popen", _FakeProc)
    vault = ps.Vault()          # __init__ runs initialize through rpc()
    assert vault.rpc("tools/list", {}) is None
