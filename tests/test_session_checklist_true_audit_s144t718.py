"""True-audit S144-T-718 - tools/session_checklist.py on a hand-off it did not author.

The counter is read at every session start (tools/rc_facts.py) and stamped by
/done (tools/done.md section 10 runs `--next`, `--stamp <n+1>`, `--current`).
The hand-off is LF-pinned in .gitattributes, but a writer can still put CRLF on
disk (`Path.write_text` on Windows, an editor) or a UTF-8 BOM, and the CLI is
driven by a sub-agent that can pass a bad argument. Each test below names the
weakness it pins:

* `--stamp` on a CRLF hand-off inserted a SECOND `SESSION:` line instead of
  replacing the first (the reader's universal newlines hid the CRLF, the
  stamper's byte read did not); the CRLF read tests are characterization;
* a BOM-led hand-off made `--stamp` insert the line ABOVE the BOM (the BOM
  ends up mid-file) and hid a first-line `SESSION:` from the reader;
* a counter too long for int() raised out of read_session, whose contract is
  None when unreadable;
* stamp_session(True) wrote `SESSION: 1` and stamp_session(3.9) wrote 3;
* the CLI died with a raw traceback on `--stamp` with no value, a non-number,
  a value < 1, a missing hand-off or an undecodable one;
* the local write_progress fallback took any task name (a path) and any
  status, where the kit refuses both.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tools import session_checklist as sc  # noqa: E402

LF = (
    "NEXT SESSION\n"
    "------------\n"
    "SESSION: 41\n"
    "Next action: re-probe live state.\n"
)
CRLF = LF.replace("\n", "\r\n")
BOM = b"\xef\xbb\xbf"


def _put(tmp_path, data: bytes) -> Path:
    p = tmp_path / "RC-NEXT-SESSION.txt"
    p.write_bytes(data)
    return p


# ------------------------------------------------------------------ CRLF

def test_crlf_handoff_counter_is_read(tmp_path):
    assert sc.read_session(_put(tmp_path, CRLF.encode("ascii"))) == 41


def test_crlf_stamp_replaces_the_line_and_keeps_crlf(tmp_path):
    p = _put(tmp_path, CRLF.encode("ascii"))
    sc.stamp_session(42, p)
    data = p.read_bytes()
    assert data.count(b"SESSION:") == 1
    assert data == CRLF.replace("SESSION: 41", "SESSION: 42").encode("ascii")
    assert sc.read_session(p) == 42


def test_crlf_next_cli_prints_n_plus_one(tmp_path, capsys):
    p = _put(tmp_path, CRLF.encode("ascii"))
    assert sc.main(["--next"], path=p) == 0
    assert capsys.readouterr().out.strip() == "42"


def test_crlf_session_start_block_does_not_report_missing(tmp_path):
    block = sc.session_start_block(_put(tmp_path, CRLF.encode("ascii")))
    assert block.startswith("Session 41 checklist")
    assert "counter missing" not in block


def test_lf_stamp_still_byte_exact(tmp_path):
    p = _put(tmp_path, LF.encode("ascii"))
    sc.stamp_session(42, p)
    assert p.read_bytes() == LF.replace("SESSION: 41", "SESSION: 42").encode("ascii")


def test_crlf_insert_keeps_crlf_on_the_new_line(tmp_path):
    body = b"NEXT SESSION\r\n------------\r\nNext action: x\r\n"
    p = _put(tmp_path, body)
    sc.stamp_session(7, p)
    assert p.read_bytes() == b"NEXT SESSION\r\n------------\r\nSESSION: 7\r\nNext action: x\r\n"


def test_crlf_insert_after_an_unterminated_underline_never_mixes_endings(tmp_path):
    p = _put(tmp_path, b"NEXT SESSION\r\n------")
    sc.stamp_session(5, p)
    assert p.read_bytes() == b"NEXT SESSION\r\n------\r\nSESSION: 5"
    assert sc.read_session(p) == 5


# ------------------------------------------------------------------ BOM

def test_bom_insert_goes_after_the_underline_and_bom_stays_first(tmp_path):
    body = "NEXT SESSION\n------------\nNext action: x\n"
    p = _put(tmp_path, BOM + body.encode("ascii"))
    sc.stamp_session(7, p)
    data = p.read_bytes()
    assert data.startswith(BOM + b"NEXT SESSION\n------------\nSESSION: 7\n")
    assert data.count(BOM) == 1
    assert sc.read_session(p) == 7


def test_bom_first_line_counter_is_read(tmp_path):
    p = _put(tmp_path, BOM + b"SESSION: 9\nNext action: y\n")
    assert sc.read_session(p) == 9
    sc.stamp_session(10, p)
    assert p.read_bytes() == BOM + b"SESSION: 10\nNext action: y\n"


# ------------------------------------------------------------------ junk counter

def test_overlong_counter_reads_as_none_not_a_raise(tmp_path):
    p = _put(tmp_path, ("SESSION: " + "9" * 5000 + "\n").encode("ascii"))
    assert sc.read_session(p) is None


@pytest.mark.parametrize("bad", [True, False, 3.9, 2.0, None, "x", "", "-3", chr(0x664) + chr(0x662)])
def test_stamp_refuses_a_non_integer_counter_and_leaves_the_file(tmp_path, bad):
    p = _put(tmp_path, LF.encode("ascii"))
    with pytest.raises((TypeError, ValueError)):
        sc.stamp_session(bad, p)
    assert p.read_bytes() == LF.encode("ascii")


def test_stamp_accepts_an_ascii_digit_string(tmp_path):
    p = _put(tmp_path, LF.encode("ascii"))
    sc.stamp_session("43", p)
    assert sc.read_session(p) == 43


# ------------------------------------------------------------------ CLI

@pytest.mark.parametrize("argv", [["--stamp"], ["--stamp", "abc"], ["--stamp", "0"],
                                  ["--stamp", "-2"], ["--stamp", "--show"]])
def test_cli_bad_stamp_value_is_a_usage_error_not_a_traceback(tmp_path, capsys, argv):
    p = _put(tmp_path, LF.encode("ascii"))
    assert sc.main(argv, path=p) == 2
    out = capsys.readouterr().out
    assert out.startswith("error:")
    assert "Traceback" not in out
    assert p.read_bytes() == LF.encode("ascii")


def test_cli_stamp_on_missing_handoff_is_exit_1(tmp_path, capsys):
    p = tmp_path / "absent.txt"
    assert sc.main(["--stamp", "5"], path=p) == 1
    assert capsys.readouterr().out.startswith("error:")
    assert not p.exists()


def test_cli_stamp_on_undecodable_handoff_is_exit_1_and_untouched(tmp_path, capsys):
    raw = b"NEXT SESSION\n------------\nSESSION: 4\n\xff\xfe bad\n"
    p = _put(tmp_path, raw)
    assert sc.main(["--stamp", "5"], path=p) == 1
    assert capsys.readouterr().out.startswith("error:")
    assert p.read_bytes() == raw


def test_cli_good_stamp_still_reads_back(tmp_path, capsys):
    p = _put(tmp_path, LF.encode("ascii"))
    assert sc.main(["--stamp", "50"], path=p) == 0
    assert capsys.readouterr().out.strip() == "50"


# ------------------------------------------------------------------ progress fallback

@pytest.mark.parametrize("task", ["../escape", "abc" + chr(10), "a/b", "a\\b", "", ".hidden", "x" * 65, 7])
def test_local_progress_refuses_a_task_that_is_not_a_file_stem(tmp_path, monkeypatch, task):
    monkeypatch.setattr(sc, "KIT_HEADLESS", tmp_path / "no_kit.py")
    with pytest.raises(ValueError):
        sc.write_progress(tmp_path, task, 5, "s", None, "running", [])
    assert not any(tmp_path.rglob("*.json"))


def test_local_progress_refuses_an_unknown_status(tmp_path, monkeypatch):
    monkeypatch.setattr(sc, "KIT_HEADLESS", tmp_path / "no_kit.py")
    with pytest.raises(ValueError):
        sc.write_progress(tmp_path, "inbox-responder", 5, "s", None, "bogus", [])
    assert not any(tmp_path.rglob("*.json"))


@pytest.mark.parametrize("status", ["running", "done", "failed", "blocked"])
def test_local_progress_accepts_the_kit_states(tmp_path, monkeypatch, status):
    monkeypatch.setattr(sc, "KIT_HEADLESS", tmp_path / "no_kit.py")
    doc = sc.write_progress(tmp_path, "inbox-responder", 5, "s", None, status, [])
    assert doc["status"] == status
    assert (tmp_path / sc.PROGRESS_REL / "inbox-responder.json").is_file()
