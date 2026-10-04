"""RM-278: two lock-holding writers could atomically CLOBBER root
`coaching_data.json` with `{}`. `read_json` returns `{}` on ANY failure (a
measured WinError 5 / ENOENT window against a concurrent replace) and on
non-dict content, and `/api/command "refresh"` plus `set_pregame` wrote that
value straight back - under `coaching_data_lock`, so nothing could repair it.

Fix: a CHECKED reader, `read_json_checked(rel) -> (dict, ok)`, that tells
"absent or empty" (ok - a first-run write must still land) from "unreadable"
(not ok). Both writers skip the write and log a WARNING when not ok.
`read_json` itself is unchanged for its many other callers.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

import pytest

from dashboard import _context, _writers

_GOOD = {"mode": "game", "pregame": "old", "log": ["x"], "action": "farm"}


@pytest.fixture()
def root(tmp_path, monkeypatch):
    monkeypatch.setattr(_context, "APP_DIR", tmp_path)
    monkeypatch.setattr(_writers, "APP_DIR", tmp_path)
    return tmp_path


def _write(root: Path, data) -> Path:
    p = root / "coaching_data.json"
    p.write_bytes(json.dumps(data).encode("utf-8") if not isinstance(data, bytes) else data)
    return p


class TestCheckedReader:
    def test_absent_is_ok_empty(self, root):
        assert _context.read_json_checked("coaching_data.json") == ({}, True)

    def test_empty_file_is_ok_empty(self, root):
        _write(root, b"")
        assert _context.read_json_checked("coaching_data.json") == ({}, True)

    def test_corrupt_is_not_ok(self, root):
        _write(root, b"{not json")
        assert _context.read_json_checked("coaching_data.json") == ({}, False)

    def test_non_dict_is_not_ok(self, root):
        _write(root, [1, 2])
        assert _context.read_json_checked("coaching_data.json") == ({}, False)

    def test_good_is_ok(self, root):
        _write(root, _GOOD)
        assert _context.read_json_checked("coaching_data.json") == (_GOOD, True)


def _unreadable(monkeypatch):
    monkeypatch.setattr(_writers, "read_json_checked", lambda rel: ({}, False))


def test_set_pregame_does_not_clobber_on_failed_read(root, monkeypatch, caplog):
    p = _write(root, _GOOD)
    before = p.read_bytes()
    _unreadable(monkeypatch)
    with caplog.at_level(logging.WARNING):
        _writers.set_pregame("new text")
    assert p.read_bytes() == before
    assert any("coaching_data.json" in r.getMessage() for r in caplog.records
               if r.levelno >= logging.WARNING)


def test_refresh_does_not_clobber_on_failed_read(root, monkeypatch, caplog):
    from dashboard import routes_state
    p = _write(root, _GOOD)
    before = p.read_bytes()
    monkeypatch.setattr(routes_state, "read_json_checked", lambda rel: ({}, False))

    class _H:
        def _send(self, code, body, ctype):
            self.code = code

    with caplog.at_level(logging.WARNING):
        routes_state._serve_command_post(_H(), {"command": "refresh"})
    assert p.read_bytes() == before
    assert any("coaching_data.json" in r.getMessage() for r in caplog.records
               if r.levelno >= logging.WARNING)


def test_set_pregame_first_run_still_writes(root):
    _writers.set_pregame("hello")
    data = json.loads((root / "coaching_data.json").read_text(encoding="utf-8"))
    assert data == {"pregame": "hello"}


def test_set_pregame_normal_path_keeps_other_fields(root):
    _write(root, _GOOD)
    _writers.set_pregame("new")
    data = json.loads((root / "coaching_data.json").read_text(encoding="utf-8"))
    assert data == {**_GOOD, "pregame": "new"}
