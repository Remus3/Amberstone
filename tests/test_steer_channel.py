# arch: tests for the Mission Control steer channel (S7) | section=tests | frozen=no
"""S7 - free-text guidance that reaches a running session.

The channel is a FILE, not the AHK bridge, and that is the finding this stage
turns on. `docs/MISSION_CONTROL_PLAN.md` specified the transport as "the
existing AHK bridge writing control/_claude_in.txt"; measured 2026-07-31 both
halves were wrong (that file is the adjudicator's stdin, and the bridge polls
control/gemini.ready), the bridge was not running, and target_hwnd.txt held a
dead hwnd. Decisively: a headless lane worker has no window, so a GUI transport
could never steer the lanes S5 made real.

What the tests protect:
- APPEND-ONLY. Consuming advances a cursor; the log is never rewritten. A
  rewrite would race two readers into losing each other's entries and would
  destroy the record needed to audit a steer after the fact.
- `pending()` NEVER writes. It is the dashboard poll path.
- `drain()` advances to the highest id it RETURNED, so an entry appended
  between the read and the write stays pending instead of being swallowed.
- A steer executes nothing. That is what makes the tier safe to fire on one
  click, and it is why INTERRUPT is deliberately not in this module.
"""
from __future__ import annotations

import importlib
import json

import pytest

steer = importlib.import_module("ops.loop.steer")


@pytest.fixture
def chan(tmp_path, monkeypatch):
    """Point the log + cursor at a tmp sandbox."""
    ctl = tmp_path / "control"
    ctl.mkdir()
    monkeypatch.setattr(steer, "CONTROL_DIR", ctl)
    monkeypatch.setattr(steer, "STEER_LOG", ctl / "STEER.jsonl")
    monkeypatch.setattr(steer, "STEER_CURSOR", ctl / "STEER.cursor")
    return ctl


# --------------------------------------------------------------------------- append
def test_append_assigns_increasing_ids(chan):
    a = steer.append("first", tier="note")
    b = steer.append("second", tier="steer")
    assert a["id"] == 1 and b["id"] == 2
    assert a["tier"] == "note" and b["tier"] == "steer"


def test_append_rejects_empty_text(chan):
    for bad in ("", "   ", None):
        with pytest.raises(ValueError):
            steer.append(bad)
    assert not (chan / "STEER.jsonl").exists()


def test_an_unknown_tier_falls_back_to_note(chan):
    rec = steer.append("x", tier="INTERRUPT")
    assert rec["tier"] == "note", (
        "an unrecognised tier must degrade to the SAFEST one, never to the "
        "loudest - INTERRUPT is a different act and is not in this module")


def test_text_is_capped(chan):
    rec = steer.append("y" * (steer.MAX_TEXT + 500))
    assert len(rec["text"]) == steer.MAX_TEXT


def test_the_log_is_append_only(chan):
    steer.append("first")
    first_bytes = (chan / "STEER.jsonl").read_bytes()
    steer.append("second")
    after = (chan / "STEER.jsonl").read_bytes()
    assert after.startswith(first_bytes), "an earlier line was rewritten"


def test_records_are_ascii_on_disk(chan):
    # Escapes, not literals: the repo hard-rule is that authored SOURCE is
    # 7-bit ASCII, and the precommit gate enforces it. The runtime VALUE is
    # still non-ASCII, which is the thing under test.
    steer.append("caf\u00e9 and an arrow \u2192")
    raw = (chan / "STEER.jsonl").read_bytes()
    assert all(b < 128 for b in raw), (
        "json.dumps must escape non-ASCII so the log survives a PowerShell "
        "reader that ANSI-decodes it")


# --------------------------------------------------------------------------- read
def test_pending_never_writes(chan):
    steer.append("a")
    before = {p.name: (p.read_bytes(), p.stat().st_mtime_ns)
              for p in chan.iterdir()}
    for _ in range(3):
        steer.pending()
        steer.summary()
    after = {p.name: (p.read_bytes(), p.stat().st_mtime_ns)
             for p in chan.iterdir()}
    assert after == before, "the poll path mutated the channel"


def test_pending_filters_by_tier(chan):
    steer.append("n1", tier="note")
    steer.append("s1", tier="steer")
    steer.append("n2", tier="note")
    assert [r["text"] for r in steer.pending(tier="note")] == ["n1", "n2"]
    assert [r["text"] for r in steer.pending(tier="steer")] == ["s1"]
    assert len(steer.pending()) == 3


def test_a_malformed_line_is_skipped_not_fatal(chan):
    steer.append("good")
    with open(chan / "STEER.jsonl", "a", encoding="utf-8") as fh:
        fh.write("{ this is not json\n")
    steer.append("also good")
    assert [r["text"] for r in steer.pending()] == ["good", "also good"]


def test_a_missing_log_reads_empty(chan):
    assert steer.pending() == []
    assert steer.summary()["pending"] == 0


# --------------------------------------------------------------------------- drain
def test_drain_advances_the_cursor_and_empties_pending(chan):
    steer.append("a")
    steer.append("b")
    taken = steer.drain()
    assert [r["text"] for r in taken] == ["a", "b"]
    assert steer.cursor() == 2
    assert steer.pending() == []


def test_drain_on_an_empty_channel_writes_nothing(chan):
    assert steer.drain() == []
    assert not (chan / "STEER.cursor").exists()


def test_a_steer_appended_during_a_drain_is_not_swallowed(chan):
    """The cursor moves to the highest id RETURNED, not to the newest id.

    Advancing to `_next_id()` would silently consume an entry the caller never
    saw - the operator's steer would vanish with no trace of being acted on.
    """
    steer.append("a")
    seen = steer.pending()                 # what a caller has in hand

    # Simulate the race directly: an entry lands between the read and the write.
    real_pending = steer.pending
    monkeypatched = {"done": False}

    def once(tier=None):
        if not monkeypatched["done"]:
            monkeypatched["done"] = True
            out = real_pending(tier)
            steer.append("b")              # arrives AFTER drain's own read
            return out
        return real_pending(tier)

    steer.pending = once
    try:
        got = steer.drain()
    finally:
        steer.pending = real_pending

    assert [r["text"] for r in got] == ["a"]
    assert steer.cursor() == 1, "the cursor must not run ahead of what it returned"
    assert [r["text"] for r in steer.pending()] == ["b"], (
        "the entry that landed mid-drain must still be pending, not swallowed")
    assert [r["text"] for r in seen] == ["a"]


def test_the_log_survives_a_drain(chan):
    steer.append("keep me")
    steer.drain()
    raw = (chan / "STEER.jsonl").read_text(encoding="utf-8")
    assert "keep me" in raw, (
        "consuming must not erase the record - it is the only audit trail")


# --------------------------------------------------------------------------- contract
def test_the_module_executes_nothing():
    """A steer is guidance. Nothing in this module may run a process."""
    src = open(steer.__file__, encoding="utf-8").read()
    for forbidden in ("subprocess", "os.system", "Popen", "taskkill"):
        assert forbidden not in src, (
            f"{forbidden} in the steer channel - a queued steer must never be "
            "able to execute or kill anything")


def test_interrupt_is_not_a_tier():
    assert "interrupt" not in steer.TIERS
    assert steer.DEFAULT_TIER == "note"


def test_it_consumes_winmutex_rather_than_reimplementing_it():
    """winmutex.py is byte-identical-by-contract with the sibling repo."""
    src = open(steer.__file__, encoding="utf-8").read()
    assert "winmutex" in src
    assert "CreateMutex" not in src, "the primitive is consumed, not re-written"
