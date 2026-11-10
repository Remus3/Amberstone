# arch: lane 8 true-audit cycle 68 regressions for GET /api/loop-status | section=tests | frozen=no
"""Lane 8 (true-audit) s144 cycle 68 - dashboard/routes_loop_status.py.

Each test is named for the weakness it pins and was RED on the pre-fix file:

F1 a non-finite float in any source (budget.json, claude.done, a lock block)
   reached the wire as a bare NaN / Infinity token, which no browser JSON
   parser accepts - one junk value killed the whole Mission Control poll.
F2 a RUNNING.lock pid outside the Win32 DWORD range made slots.pid_alive
   raise ctypes.ArgumentError, which escaped _controller_lock and turned the
   whole poll into an HTTP 500; a bool pid read as pid 1.
F3 a non-finite or FUTURE lock ts gave age_s 0, so an unreadable holder was
   "presumed live" forever - RECLAIMABLE rendered as RUNNING, which the module
   header says must never happen.
F4 _controller_lock had no fail-soft net: any probe failure 500ed the poll.
F5 _last_commit decoded git's UTF-8 with the locale codec (cp1252 on the
   operator's box when UTF-8 mode is off), so a non-ASCII subject read as
   mojibake or dropped the whole last_commit block.
F6 claude.done fields were passed through unvalidated (a dict cycle, a list
   sha rendered as "['deadbe"), and config max_cycles accepted a bool.
F7 controller.log (an append log, 565 KB measured) was read WHOLE, twice, on
   every 4 s poll; a bounded tail read must give the same answer.
"""
from __future__ import annotations

import importlib
import json
import os
import shutil
import string
import subprocess
import sys
import time
from pathlib import Path

import pytest

from dashboard import routes_loop_status as mod

_lanes_mod = importlib.import_module("ops.loop.lanes")
_REPO = Path(__file__).resolve().parent.parent


class FakeHandler:
    def __init__(self) -> None:
        self.path = "/api/loop-status"
        self.sent = None

    def _send(self, status, body, ctype):
        self.sent = (status, body, ctype)


def _reject_constant(name):
    raise AssertionError(f"non-standard JSON token on the wire: {name}")


def _serve_strict():
    """Serve once and parse the body the way a browser does: NaN / Infinity
    are NOT JSON, so the parse must refuse them."""
    h = FakeHandler()
    mod._serve_loop_status(h)
    assert h.sent is not None
    status, body, _ctype = h.sent
    return status, json.loads(body.decode("utf-8"), parse_constant=_reject_constant)


@pytest.fixture
def loopdir(tmp_path, monkeypatch):
    ctl = tmp_path / "control"
    ctl.mkdir()
    cfg = tmp_path / "config.json"
    monkeypatch.setattr(mod, "CONTROL_DIR", ctl)
    monkeypatch.setattr(mod, "CONFIG_PATH", cfg)
    monkeypatch.setattr(mod, "CONTROLLER_LOG", ctl / "controller.log")
    monkeypatch.setattr(mod, "LANES_ROOT", tmp_path / "ops" / "loop" / "control" / "lanes")
    monkeypatch.setattr(mod, "LANE_LOG_DIR", tmp_path / "reports")
    monkeypatch.setattr(mod, "_last_commit", lambda: None)
    monkeypatch.setattr(mod, "_steer_summary", lambda: None)
    return ctl, cfg


# --------------------------------------------------------------------------- F1
def test_f1_nonfinite_budget_values_never_reach_the_wire_as_nan(loopdir):
    ctl, _ = loopdir
    (ctl / "budget.json").write_text(
        '{"claude_usd_info": NaN, "executor_usd": 1e999, "x": -Infinity, '
        '"nested": {"y": [NaN, 2.5]}, "cycle": 4}', encoding="utf-8")
    status, body = _serve_strict()
    assert status == 200
    b = body["budget"]
    assert b["claude_usd_info"] is None
    assert b["executor_usd"] is None
    assert b["x"] is None
    assert b["nested"] == {"y": [None, 2.5]}
    assert b["cycle"] == 4


def test_f1_a_nonfinite_float_from_a_lock_block_never_reaches_the_wire(
        loopdir, monkeypatch):
    # The lane-lock block comes from ops/loop/lanes.py, not from a file this
    # module parses - so the guard must sit on the WHOLE payload, not only on
    # the JSON reader.
    monkeypatch.setattr(mod, "_lane_lock", lambda: {
        "state": "RUNNING", "age_s": float("nan"), "pid": 1})
    status, body = _serve_strict()
    assert status == 200
    assert body["lanes"]["age_s"] is None
    assert body["lanes"]["state"] == "RUNNING"


def test_f1_a_json_bomb_budget_is_failsoft_not_a_500(loopdir):
    # json.loads raises RecursionError (not ValueError) on deep nesting, so
    # the reader's fail-soft catch never saw it and the whole poll 500ed.
    ctl, _ = loopdir
    (ctl / "budget.json").write_text("[" * 200000, encoding="utf-8")
    status, body = _serve_strict()
    assert status == 200
    assert body["budget"] is None


def test_f1_a_deep_but_loadable_budget_never_500s(loopdir):
    ctl, _ = loopdir
    (ctl / "budget.json").write_text(
        '{"deep": ' + "[" * 900 + "]" * 900 + ', "cycle": 3}', encoding="utf-8")
    status, body = _serve_strict()
    assert status == 200
    assert body["budget"]["cycle"] == 3


def test_f1_a_nesting_json_loads_accepts_but_python_cannot_walk_never_500s(loopdir):
    # Measured on 3.14: json.loads accepts 5000 levels (its C limit is far
    # above sys.getrecursionlimit()), so a Python-level walk of the parsed
    # value (the _json_safe sanitizer) would raise RecursionError inside the
    # handler without its depth cap. Passed pre-fix (the C encoder copes); it
    # guards the F1 sanitizer. Deep junk is cut, flat fields stay.
    ctl, _ = loopdir
    depth = 5000
    (ctl / "budget.json").write_text(
        '{"deep": ' + "[" * depth + "]" * depth + ', "cycle": 3}',
        encoding="utf-8")
    status, body = _serve_strict()
    assert status == 200
    assert body["budget"]["cycle"] == 3


# --------------------------------------------------------------------------- F2 / F4
def _old_lock(ctl, text):
    lock = ctl / "RUNNING.lock"
    lock.write_text(text, encoding="utf-8")
    old = time.time() - (_lanes_mod.WRITE_GRACE_S + 600)
    os.utime(lock, (old, old))
    return lock


def test_f2_a_pid_beyond_dword_range_never_500s_the_poll(loopdir):
    ctl, _ = loopdir
    _old_lock(ctl, json.dumps({"pid": 2 ** 32 + 5, "run_id": "r1",
                               "ts": time.time() - 3600}))
    status, body = _serve_strict()
    assert status == 200
    cl = body["controller_lock"]
    assert cl["pid"] is None
    assert cl["state"] == "RECLAIMABLE"


def test_f2_a_bool_pid_is_not_pid_1(loopdir):
    ctl, _ = loopdir
    _old_lock(ctl, json.dumps({"pid": True, "ts": time.time() - 3600}))
    status, body = _serve_strict()
    assert status == 200
    assert body["controller_lock"]["pid"] is None
    assert body["controller_lock"]["state"] == "RECLAIMABLE"


def test_f4_a_raising_pid_probe_degrades_only_the_lock_block(loopdir, monkeypatch):
    ctl, _ = loopdir
    _old_lock(ctl, json.dumps({"pid": 4242, "ts": time.time()}))
    (ctl / "cycle.txt").write_text("7", encoding="utf-8")

    def _boom(pid):
        raise OSError("probe failed")

    monkeypatch.setattr(_lanes_mod.slots, "pid_alive", _boom)
    monkeypatch.setattr(mod, "_lane_lock", lambda: None)
    status, body = _serve_strict()
    assert status == 200
    assert body["controller_lock"] is None
    assert body["state"] == "running"
    assert body["cycle"] == 7


# --------------------------------------------------------------------------- F3
@pytest.mark.parametrize("ts_text", ["1e999", "NaN", "true", "future"])
def test_f3_a_junk_or_future_ts_falls_back_to_the_file_mtime(loopdir, ts_text):
    if ts_text == "future":
        # Computed at run time, not at collection: a collection-time
        # time.time() gave every xdist worker a different test id, and xdist
        # aborts a run whose workers collect different tests.
        ts_text = str(time.time() + 10 ** 7)
    ctl, _ = loopdir
    _old_lock(ctl, '{"pid": "not-a-pid", "ts": ' + ts_text + "}")
    status, body = _serve_strict()
    assert status == 200
    cl = body["controller_lock"]
    assert cl["state"] == "RECLAIMABLE"
    assert cl["age_s"] is not None and cl["age_s"] > _lanes_mod.WRITE_GRACE_S


# --------------------------------------------------------------------------- F5
@pytest.mark.skipif(shutil.which("git") is None, reason="git not on PATH")
def test_f5_last_commit_reads_utf8_even_when_utf8_mode_is_off(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    no_window = 0x08000000 if os.name == "nt" else 0
    run = dict(capture_output=True, timeout=60, creationflags=no_window)
    # e-acute and A-acute: 0xC1 encodes as C3 81, and 0x81 is undefined in
    # cp1252, so the locale decode raised rather than merely garbling.
    subject = "caf" + chr(0xE9) + " " + chr(0xC1) + " ok"
    msg = tmp_path / "msg.txt"
    msg.write_bytes(subject.encode("utf-8") + b"\n")
    assert subprocess.run(["git", "init", "-q", str(repo)], **run, check=False).returncode == 0
    r = subprocess.run(
        ["git", "-C", str(repo), "-c", "user.name=t",
         "-c", "user.email=t@example.invalid", "-c", "commit.gpgsign=false",
         "commit", "-q", "--allow-empty", "-F", str(msg)], **run, check=False)
    assert r.returncode == 0, r.stderr
    # A child with UTF-8 mode OFF decodes subprocess text with the locale
    # codec, which is what RC's pythonw sees when PYTHONUTF8 is not in its
    # process environment.
    child = (
        "import json, sys; from pathlib import Path\n"
        f"sys.path.insert(0, {str(_REPO)!r})\n"
        "from dashboard import routes_loop_status as m\n"
        f"m.ROOT = Path({str(repo)!r})\n"
        "print(json.dumps(m._last_commit()))\n"
    )
    out = subprocess.run([sys.executable, "-X", "utf8=0", "-c", child],
                         text=True, encoding="ascii", **run, check=False)
    assert out.returncode == 0, out.stderr
    got = json.loads(out.stdout.strip().splitlines()[-1])
    assert got is not None
    assert got["subject"] == subject


def test_f5_a_subject_carrying_the_separator_keeps_the_real_date(monkeypatch):
    from tests._module_view import bind_subprocess

    class _Done:
        stdout = "abc1234\x1fa\x1fb\x1f2026-06-20T00:00:00-05:00"

    bind_subprocess(monkeypatch, mod, run=lambda cmd, **kw: _Done())
    got = mod._last_commit()
    assert got == {"sha": "abc1234", "subject": "a\x1fb",
                   "iso": "2026-06-20T00:00:00-05:00"}


# --------------------------------------------------------------------------- F6
def test_f6_sentinel_fields_of_the_wrong_type_are_dropped(loopdir):
    ctl, _ = loopdir
    (ctl / "claude.done").write_text(json.dumps({
        "cycle": {"n": 3}, "sha": ["deadbeefcafe"], "tests_pass": [1],
        "regressions": False, "ts": "noon"}), encoding="utf-8")
    status, body = _serve_strict()
    assert status == 200
    ld = body["last_done"]
    assert ld["source"] == "sentinel"
    assert ld["cycle"] is None
    assert ld["sha"] == ""
    assert ld["tests_pass"] is None
    assert ld["ts"] is None


def test_f6_sentinel_valid_fields_still_pass(loopdir):
    ctl, _ = loopdir
    (ctl / "claude.done").write_text(json.dumps({
        "cycle": 9, "sha": "0123456789abcdef", "tests_pass": "?",
        "regressions": True, "ts": 1717000000.5}), encoding="utf-8")
    _, body = _serve_strict()
    ld = body["last_done"]
    assert (ld["cycle"], ld["sha"], ld["tests_pass"], ld["regressions"],
            ld["ts"]) == (9, string.octdigits, "?", True, 1717000000.5)


def test_f6_a_non_hex_sha_is_dropped(loopdir):
    ctl, _ = loopdir
    (ctl / "claude.done").write_text(json.dumps({
        "cycle": 2, "sha": "<b>x</b>"}), encoding="utf-8")
    _, body = _serve_strict()
    assert body["last_done"]["sha"] == ""


@pytest.mark.parametrize("value", [True, -3])
def test_f6_max_cycles_rejects_a_bool_and_a_negative(loopdir, value):
    _, cfg = loopdir
    cfg.write_text(json.dumps({"max_cycles": value}), encoding="utf-8")
    _, body = _serve_strict()
    assert body["max_cycles"] is None


# --------------------------------------------------------------------------- F7
def test_f7_the_poll_never_reads_controller_log_whole(loopdir, monkeypatch):
    ctl, _ = loopdir
    log_path = ctl / "controller.log"
    lines = [f"2026-06-07T09:00:00 filler line {i:06d} " + "x" * 40
             for i in range(5000)]
    lines.append("2026-06-07T10:38:03 cycle 12: claude.done sha=abcdef12 "
                 "tests=9 regress=False")
    lines.append("2026-06-07T10:38:04 STOP written: done")
    log_path.write_bytes(("\n".join(lines) + "\n").encode("utf-8"))
    real = mod._read_text

    def _spy(path):
        assert Path(path) != log_path, "controller.log read whole"
        return real(path)

    monkeypatch.setattr(mod, "_read_text", _spy)
    monkeypatch.setattr(mod, "LOG_READ_CAP_BYTES", 8192)
    _, body = _serve_strict()
    assert body["log_tail"][-1] == "2026-06-07T10:38:04 STOP written: done"
    assert body["log_tail"] == lines[-mod.LOG_TAIL_LINES:]
    assert body["last_done"]["cycle"] == 12
    assert body["last_done"]["source"] == "log"


def test_f7_a_tail_cut_mid_line_never_shows_a_fragment(loopdir, monkeypatch):
    ctl, _ = loopdir
    lines = [f"row-{i:03d}-" + "y" * 20 for i in range(10)]
    (ctl / "controller.log").write_bytes(("\n".join(lines) + "\n").encode("utf-8"))
    monkeypatch.setattr(mod, "LOG_READ_CAP_BYTES", 100)
    _, body = _serve_strict()
    tail = body["log_tail"]
    assert tail, "a short cap must still yield the newest full lines"
    assert all(line in lines for line in tail), tail
    assert tail[-1] == lines[-1]
