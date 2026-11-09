# arch: tests for the session_steer CLI exit-code contract (S144-P-311) | section=tests | frozen=no
"""tools/session_steer.py - the reader a ritual or a lane puts at its top.

Its docstring makes two promises a caller branches on and nothing pinned them
(tests/test_steer_channel.py covers ops/loop/steer.py, never this CLI):

  --peek   ALWAYS exits 0 and never writes, even when the channel cannot be
           loaded, so it can never be the thing that fails a ritual.
  --drain  returns the pending steers, advances the cursor, and exits 1 when
           there was nothing to take.

Each test runs main() against a tmp_path sandbox for the log + cursor.
"""
from __future__ import annotations

import importlib
import json

import pytest

steer = importlib.import_module("ops.loop.steer")
cli = importlib.import_module("tools.session_steer")


@pytest.fixture
def chan(tmp_path, monkeypatch):
    ctl = tmp_path / "control"
    ctl.mkdir()
    monkeypatch.setattr(steer, "CONTROL_DIR", ctl)
    monkeypatch.setattr(steer, "STEER_LOG", ctl / "STEER.jsonl")
    monkeypatch.setattr(steer, "STEER_CURSOR", ctl / "STEER.cursor")
    return ctl


def _out_json(capsys):
    return json.loads(capsys.readouterr().out)


def test_peek_on_an_empty_channel_exits_zero_and_writes_nothing(chan, capsys):
    assert cli.main(["--peek"]) == 0
    doc = _out_json(capsys)
    assert doc["pending"] == []
    assert doc["summary"]["pending"] == 0
    assert list(chan.iterdir()) == []


def test_peek_lists_guidance_and_leaves_the_cursor_alone(chan, capsys):
    steer.append("first", tier="note")
    steer.append("second", tier="steer")
    before = (chan / "STEER.jsonl").read_bytes()
    assert cli.main(["--peek"]) == 0
    doc = _out_json(capsys)
    assert [r["text"] for r in doc["pending"]] == ["first", "second"]
    assert not (chan / "STEER.cursor").exists()
    assert (chan / "STEER.jsonl").read_bytes() == before
    # peeking twice is idempotent: nothing was consumed
    assert cli.main(["--peek"]) == 0
    assert len(_out_json(capsys)["pending"]) == 2


def test_peek_tier_filter_narrows_to_one_tier(chan, capsys):
    steer.append("a note", tier="note")
    steer.append("a steer", tier="steer")
    assert cli.main(["--peek", "--tier", "steer"]) == 0
    assert [r["text"] for r in _out_json(capsys)["pending"]] == ["a steer"]


def test_peek_text_format_renders_tier_id_and_text(chan, capsys):
    steer.append("look at the lane", tier="steer")
    assert cli.main(["--peek", "--format", "text"]) == 0
    assert capsys.readouterr().out.strip() == "[STEER #1] look at the lane"


def test_peek_text_format_says_so_when_empty(chan, capsys):
    assert cli.main(["--peek", "--format", "text"]) == 0
    assert capsys.readouterr().out.strip() == "(no steers pending)"


def test_peek_exits_zero_even_when_the_channel_cannot_load(monkeypatch, capsys):
    def boom():
        raise ImportError("steer channel gone")

    monkeypatch.setattr(cli, "_load_steer", boom)
    assert cli.main(["--peek"]) == 0
    doc = _out_json(capsys)
    assert doc["pending"] == []
    assert "steer channel gone" in doc["error"]


def test_drain_returns_the_steers_advances_the_cursor_and_exits_zero(chan, capsys):
    steer.append("one", tier="note")
    steer.append("two", tier="steer")
    assert cli.main(["--drain"]) == 0
    rows = _out_json(capsys)
    assert [r["text"] for r in rows] == ["one", "two"]
    assert steer.cursor() == 2
    assert steer.pending() == []


def test_a_second_drain_exits_one_with_an_empty_list(chan, capsys):
    steer.append("only", tier="note")
    assert cli.main(["--drain"]) == 0
    capsys.readouterr()
    assert cli.main(["--drain"]) == 1
    assert _out_json(capsys) == []


def test_drain_on_an_empty_channel_exits_one(chan, capsys):
    assert cli.main(["--drain", "--format", "text"]) == 1
    assert capsys.readouterr().out.strip() == "(no steers pending)"
    assert not (chan / "STEER.cursor").exists()


def test_drain_hides_an_audit_row_but_still_advances_past_it(chan, capsys):
    steer.record("interrupt fired", tier="interrupt")
    steer.append("real guidance", tier="note")
    assert cli.main(["--drain"]) == 0
    assert [r["text"] for r in _out_json(capsys)] == ["real guidance"]
    assert steer.cursor() == 2


def test_drain_that_cannot_load_the_channel_exits_one_with_the_error(monkeypatch, capsys):
    def boom():
        raise ImportError("steer channel gone")

    monkeypatch.setattr(cli, "_load_steer", boom)
    assert cli.main(["--drain"]) == 1
    doc = _out_json(capsys)
    assert doc["ok"] is False
    assert "steer channel gone" in doc["error"]


def test_peek_and_drain_are_mutually_exclusive_and_one_is_required(capsys):
    for argv in ([], ["--peek", "--drain"]):
        with pytest.raises(SystemExit) as exc:
            cli.main(argv)
        assert exc.value.code == 2
    capsys.readouterr()
