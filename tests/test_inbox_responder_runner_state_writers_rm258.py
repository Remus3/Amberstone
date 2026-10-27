"""RM-258: the inbox responder runner's four JSON state records are atomic.

tools/inbox_responder_runner.py keeps four small records under ops/runtime/
that every RC-InboxResponder tick reads back: the spawn-attempt counter, the
refusal hold, the fleet-skip seen-record and the bounce allowance. Two of them
fail CLOSED on a torn read (`held_notes_of` and `bounces_of` return None, and
the tick then spawns, bounces and answers nothing), so a half-written file
stalls the channel until a human repairs it.

Each writer used to hand-roll `<name>.json.tmp` plus a bare Path.replace: a
destination-derived scratch name shared by every writer, no fsync and no
WinError 5 retry. They now route through core.polled_json, which supplies all
three. On-disk bytes are unchanged (json.dumps keeps ensure_ascii=True, so the
UTF-8 bytes equal the old write_text(newline="\n") output).

No process, no live inbox, no git: tmp roots only. The runner's own suite
(tests/test_inbox_responder_runner.py) builds a real git repo with a push and
covers the end-to-end hold-before-bounce ordering; these tests pin the writers.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

import core.polled_json as pj
from tools import inbox_responder_runner as runner

SHA = "0123456789ab"
ENTRY = {"stage": "input", "detail": "name-grammar", "note": "n.md", "ts": "T"}
NORMAL = "2026-10-03-1000-from-RSC-question.md"
TERMINAL = "2026-10-03-1001-from-LL-ack-TERMINAL.md"


def _dump(data) -> bytes:
    return json.dumps(data, indent=2, sort_keys=True).encode("utf-8")


def _record_writes(monkeypatch):
    seen = []
    real = pj._write_then_replace

    def rec(path, data):
        seen.append((Path(path).name, bytes(data)))
        return real(path, data)

    monkeypatch.setattr(pj, "_write_then_replace", rec)
    return seen


def _skip_terminal(monkeypatch):
    monkeypatch.setattr(runner, "fleet_skip_reason",
                        lambda name: "terminal" if "TERMINAL" in name else None)


def _write_attempt(root):
    assert runner._record_attempt(root, SHA) == 1
    return runner.attempts_path(root), {SHA: 1}


def _write_hold(root):
    assert runner._record_held_note(root, SHA, ENTRY) is True
    return runner.held_notes_path(root), {SHA: ENTRY}


def _write_skip(root):
    assert runner._drop_fleet_skips(root, [TERMINAL, NORMAL], "T1") == [NORMAL]
    expected = {runner.note_sha12(TERMINAL): {
        "note": runner.safe_name(TERMINAL), "reason": "terminal", "ts": "T1"}}
    return runner.skipped_path(root), expected


def _write_bounce(root):
    runner._record_bounce(root, "agr:" + SHA, ENTRY)
    return runner.bounces_path(root), {"agr:" + SHA: ENTRY}


WRITERS = {
    "attempts": _write_attempt,
    "held": _write_hold,
    "skipped": _write_skip,
    "bounces": _write_bounce,
}


@pytest.mark.parametrize("writer", sorted(WRITERS))
def test_rm258_state_writer_routes_through_polled_json(tmp_path, monkeypatch, writer):
    _skip_terminal(monkeypatch)
    seen = _record_writes(monkeypatch)
    path, data = WRITERS[writer](tmp_path)
    expected = _dump(data)
    assert seen == [(path.name, expected)]
    assert path.read_bytes() == expected
    assert b"\r" not in path.read_bytes()
    # No scratch left behind, shared or per-writer.
    assert [x.name for x in path.parent.iterdir()] == [path.name]


@pytest.mark.parametrize("writer", sorted(WRITERS))
def test_rm258_state_writer_survives_a_transient_rename_refusal(tmp_path, monkeypatch,
                                                               writer):
    _skip_terminal(monkeypatch)
    real = pj.os.replace
    refusals = [2]

    def flaky(src, dst):
        if refusals[0]:
            refusals[0] -= 1
            raise PermissionError(13, "Access is denied")
        return real(src, dst)

    monkeypatch.setattr(pj.os, "replace", flaky)
    monkeypatch.setattr(pj.time, "sleep", lambda _s: None)
    path, data = WRITERS[writer](tmp_path)
    assert refusals == [0]
    assert json.loads(path.read_text(encoding="utf-8")) == data


def _refuse_writes(monkeypatch):
    def refuse(path, data):
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(pj, "_write_then_replace", refuse)


def test_rm258_an_unpersistable_hold_reports_false(tmp_path, monkeypatch):
    """The hold is recorded BEFORE the bounce, and False suppresses the bounce
    (test_an_unrecordable_hold_suppresses_the_bounce in the runner suite)."""
    _refuse_writes(monkeypatch)
    assert runner._record_held_note(tmp_path, SHA, ENTRY) is False
    assert not runner.held_notes_path(tmp_path).exists()


def test_rm258_an_unpersistable_skip_record_never_costs_the_tick(tmp_path, monkeypatch):
    _skip_terminal(monkeypatch)
    _refuse_writes(monkeypatch)
    assert runner._drop_fleet_skips(tmp_path, [TERMINAL, NORMAL], "T1") == [NORMAL]
    assert not runner.skipped_path(tmp_path).exists()
