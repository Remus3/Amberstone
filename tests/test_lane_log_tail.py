# arch: tests for the Mission Control lane-log tail | section=tests | frozen=no
"""What the RUNNING lane is saying, surfaced where the operator is looking.

WHY THIS EXISTS. Reported live 2026-08-02: "the lane is still held but the
output window in MC is not showing anything new." Nothing was broken - the
worker was alive with six node children - but MC's only log surface renders
`ops/loop/control/controller.log`, the LOOP CONTROLLER's log. That controller
has been stopped since 2026-07-28 ("operator halt via LW session"), so the
panel had been frozen for five days and would never move for a lane fire. It
looked like a hung lane and was a missing surface.

TWO THINGS THIS FILE PINS:

1. THE MIXED ENCODING. A lane log is not one encoding, it is two. run_lane.ps1
   writes its header with `Out-File -Encoding utf8` (UTF-8 + BOM) and then the
   worker's own output arrives via `*>>`, whose default on Windows PowerShell
   5.1 is UTF-16LE. MEASURED on the real file: bytes 0-2 are the UTF-8 BOM,
   the header is UTF-8, and from byte 119 it is UTF-16LE - 2066 NUL bytes in a
   4298-byte file. `read_text(encoding="utf-8")` returns mojibake for the
   second half ("C\x00y\x00c\x00l\x00e"), which is exactly what would have
   been rendered into the panel. The reader must handle a file that legitimately
   changes encoding mid-stream, because logs written before the runner fix
   still exist and are the ones an operator wants to read.

2. IT MUST NEVER BREAK THE POLL. This runs inside /api/loop-status, which the
   panel hits every 5s. Every failure answers None.
"""
from __future__ import annotations

import importlib
import time

import pytest

mod = importlib.import_module("dashboard.routes_loop_status")


@pytest.fixture
def logdir(tmp_path, monkeypatch):
    d = tmp_path / "reports"
    d.mkdir()
    monkeypatch.setattr(mod, "LANE_LOG_DIR", d)
    return d


def _mixed_bytes(header: str, body: str) -> bytes:
    """The real shape: UTF-8 BOM + UTF-8 header, then UTF-16LE body."""
    return b"\xef\xbb\xbf" + header.encode("utf-8") + body.encode("utf-16-le")


# ---- decoding --------------------------------------------------------------

def test_a_utf16_tail_after_a_utf8_header_decodes_to_real_text():
    raw = _mixed_bytes("lane start 2026-08-02T10:06:38\r\n",
                       "Cycle complete. 3 commits.\r\n")
    out = mod._decode_lane_log(raw)
    assert "lane start 2026-08-02T10:06:38" in out
    assert "Cycle complete. 3 commits." in out
    assert "\x00" not in out, "a NUL in the output is undecoded UTF-16 reaching the panel"
    assert "C\x00y" not in out


def test_the_real_three_segment_shape_including_the_utf8_FOOTER():
    """The shape the live file actually has, and the one that caught a bug.

    run_lane.ps1 writes a UTF-8 header, the worker's UTF-16LE output, and then
    a UTF-8 FOOTER carrying the exit code. A decoder that assumes a single
    encoding switch gets the first two right and turns the footer into CJK
    ("lane exit ..." decoded as CJK), which was visible in the live
    panel before this test existed. The footer is the single most important
    line in the file - it is the one that says whether the run succeeded.
    """
    # _seg rather than literals: naming each segment's encoding beside its text
    # is the whole point of the fixture, and a bytes literal would hide exactly
    # the detail under test. (It also keeps ruff's UP012 out of it, which would
    # otherwise rewrite the two UTF-8 segments and destroy the symmetry.)
    def _seg(text, enc):
        return text.encode(enc)

    raw = (b"\xef\xbb\xbf"
           + _seg("lane start 2026-08-02T10:26:42\r\n", "utf-8")
           + _seg("Cycle complete.\r\n", "utf-16-le")
           + _seg("lane exit 2026-08-02T10:40:19 code=0\r\n", "utf-8"))
    lines = mod._decode_lane_log(raw).splitlines()
    assert lines[0] == "lane start 2026-08-02T10:26:42"
    assert lines[1] == "Cycle complete."
    assert lines[-1] == "lane exit 2026-08-02T10:40:19 code=0", (
        f"the UTF-8 footer was mangled: {lines[-1]!r}")


def test_a_plain_utf8_log_is_unchanged():
    raw = b"\xef\xbb\xbflane start\r\nall good\r\n"
    out = mod._decode_lane_log(raw)
    assert out.splitlines() == ["lane start", "all good"]
    # chr(0xFEFF), never the literal character: an authored BOM is a banned
    # non-ASCII glyph repo-wide and tools/precommit_gate.py refuses it - it
    # caught this exact line. Naming it by codepoint asserts the same thing
    # and keeps this file 7-bit.
    assert not out.startswith(chr(0xFEFF)), "the BOM must not survive into a rendered line"


def test_undecodable_bytes_do_not_raise():
    assert isinstance(mod._decode_lane_log(b"\xff\xfe\x00\x80\x81\x82"), str)


# ---- selection -------------------------------------------------------------

def test_the_newest_lane_log_wins(logdir):
    old = logdir / "lane_ds_aaa.log"
    new = logdir / "lane_gated_bbb.log"
    old.write_bytes(b"old\r\n")
    new.write_bytes(b"new\r\n")
    past = time.time() - 600
    import os
    os.utime(old, (past, past))
    got = mod._lane_log()
    assert got is not None
    assert got["name"] == "lane_gated_bbb.log"
    assert got["lane"] == "gated" and got["run_id"] == "bbb"


def test_the_HELD_lanes_log_wins_over_a_newer_one(logdir, monkeypatch):
    """A held lane is the one the operator is watching.

    Newest-by-mtime is only the fallback. If another lane's log is touched
    while `gated` runs - a stale file copied in, a previous run appended to -
    the panel must keep showing the RUNNING lane, not whatever was written last.
    """
    held = logdir / "lane_gated_run1.log"
    held.write_bytes(b"held lane output\r\n")
    other = logdir / "lane_repo_zzz.log"
    other.write_bytes(b"unrelated\r\n")
    past = time.time() - 600
    import os
    os.utime(held, (past, past))
    monkeypatch.setattr(mod, "_lane_lock", lambda: {
        "state": "RUNNING", "lane": "gated", "run_id": "run1",
        "pid": 1, "worktree": None, "age_s": 1.0})
    got = mod._lane_log()
    assert got["name"] == "lane_gated_run1.log"
    assert got["held"] is True


def test_only_the_tail_is_returned(logdir):
    body = "".join(f"line {i}\r\n" for i in range(100))
    (logdir / "lane_gated_x.log").write_bytes(body.encode("utf-8"))
    got = mod._lane_log()
    assert len(got["lines"]) == mod.LANE_LOG_TAIL_LINES
    assert got["lines"][-1] == "line 99", "the NEWEST lines are the ones that matter"
    assert got["truncated"] is True


def test_a_short_log_is_not_marked_truncated(logdir):
    (logdir / "lane_gated_x.log").write_bytes(b"only line\r\n")
    got = mod._lane_log()
    assert got["lines"] == ["only line"]
    assert got["truncated"] is False


# ---- fail-soft -------------------------------------------------------------

def test_no_reports_dir_answers_none(tmp_path, monkeypatch):
    monkeypatch.setattr(mod, "LANE_LOG_DIR", tmp_path / "nope")
    assert mod._lane_log() is None


def test_a_dir_with_no_lane_logs_answers_none(logdir):
    (logdir / "mdclean-findings.md").write_bytes(b"not a lane log\r\n")
    (logdir / "loop.log").write_bytes(b"also not\r\n")
    assert mod._lane_log() is None


def test_the_payload_carries_the_field(logdir):
    """The route must actually expose it - a helper nothing calls is not a
    surface. This is the assertion that would have caught the original defect,
    which was not a broken reader but the absence of one."""
    (logdir / "lane_gated_x.log").write_bytes(b"hello\r\n")
    payload = mod.build_loop_status()
    assert "lane_log" in payload
    assert payload["lane_log"]["lines"] == ["hello"]
