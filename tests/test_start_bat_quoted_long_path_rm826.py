"""RM-826 (e): start.bat's quoted-PATH, long-PATH refusal, kept as an accepted
residual with a Reverses-if.

WHY THIS FILE EXISTS. The RM-810 key check (start.bat, scripts/restart.bat,
scripts/start_debug.bat; pinned line by line in
tests/test_launcher_key_read_rm810.py) finds its interpreter in three steps:
python-embed, then the PATH search of for (%%~$PATH:I), which finds nothing in
a QUOTED PATH entry, then the same search over a quote-stripped copy of PATH
built by `call set`. That copy puts the whole PATH on one command line, so at
a PATH of about 8179 characters or more it fails ("The input line is too
long."), and with python-embed absent and Python only behind a quoted entry
no interpreter is found. scripts/restart.bat and scripts/start_debug.bat go
ahead whatever the check says; start.bat refuses to start ("Could not check
the Anthropic API key"). 36b14cb73 accepted that refusal; RM-826 (e) asked to
close it or record it with a Reverses-if.

Recorded, not fixed (s144). A fix changes the shared check lines that
tests/test_launcher_key_read_rm810.py pins exactly (the copy line, the set of
values RC_KEY_PY may take, one shared check in all three launchers), and that
file is owned by the session 144 main session. The refusal fails safe: it
starts nothing and says what to do.

Measured 2026-10-27 with this harness (cmd.exe, no python-embed, the Python
folder quoted, then a pad entry): PATH lengths 300 to 8178 run the check;
8179, 8180, 8191, 8192, 9000 and 20000 refuse. The same PATHs with the folder
unquoted run the check at every length.

Pinned here:
  (a) static: start.bat carries the RM-826 (e) record, with its Reverses-if,
      on the comment lines right above its "Could not check" refusal;
  (b) behaviour: the residual is exactly as recorded - the check runs at a
      quoted PATH just under the limit, start.bat refuses (exit 1, the
      friendly message, nothing checked) at or past it, and an unquoted entry
      runs at every length. If (b) goes red the residual moved: re-measure,
      then fix or drop the record in start.bat (do not just re-pin numbers).
Every key value here is fake.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

from tests.test_launcher_key_read_rm810 import FILE_KEY, _is_comment, _line, _run

REPO = Path(__file__).resolve().parent.parent

_REFUSAL = "Could not check the Anthropic API key"
_RECORD = "RM-826 (e)"

win_only = pytest.mark.skipif(sys.platform != "win32", reason="runs start.bat under cmd.exe")


def _start_bat_lines() -> list[str]:
    return [ln.strip() for ln in (REPO / "start.bat").read_text(encoding="ascii").splitlines()]


def _record() -> list[str]:
    """The contiguous comment lines directly above start.bat's "Could not
    check" refusal block (its `if not ... "10" ... "11" (` line)."""
    lines = _start_bat_lines()
    at = next(i for i, ln in enumerate(lines)
              if ln.startswith("if not ") and '"%RC_KEY_EC%"=="10"' in ln)
    assert _REFUSAL in lines[at + 1], lines[at + 1]
    run = []
    i = at - 1
    while i >= 0 and lines[i] and _is_comment(lines[i]):
        run.append(lines[i])
        i -= 1
    return list(reversed(run))


def test_start_bat_records_the_quoted_long_path_residual():
    record = " ".join(ln.lstrip(":").strip() for ln in _record())
    assert _RECORD in record, (
        "start.bat does not record the RM-826 (e) residual above its refusal")
    assert "Reverses if:" in record, "the RM-826 (e) record carries no Reverses-if"
    for fact in ("quoted", "python-embed", "8179"):
        assert fact in record, f"the RM-826 (e) record does not name {fact!r}: {record}"


def test_the_record_holds_no_percent_sign():
    # A :: line is still read by cmd's first phase, so a %PATH% in it would be
    # expanded on every run - at a long PATH, into an over-long line.
    record = _record()
    assert record, "no record above the refusal; this check would pass on nothing"
    for ln in record:
        assert "%" not in ln, ln


def _path(length: int, quoted: bool) -> str:
    py = str(Path(sys.executable).parent)
    path = (f'"{py}"' if quoted else py) + ";C:\\Windows\\rc826e-pad-"
    path += "y" * (length - len(path))
    assert len(path) == length
    return path


@win_only
@pytest.mark.parametrize("length", [300, 8100, 8178])
def test_a_quoted_python_folder_is_found_under_the_limit(tmp_path, length):
    rc, out, seen = _run(tmp_path, "start.bat", "junk", _line(FILE_KEY),
                         path=_path(length, quoted=True))
    assert rc == 0, out
    assert seen == [{}], f"the check did not run: {out!r}"


@win_only
@pytest.mark.parametrize("length", [8179, 8191, 8192, 9000, 20000])
def test_start_bat_refuses_at_or_past_the_limit(tmp_path, length):
    # The accepted RM-826 (e) residual: no python-embed, Python only behind a
    # quoted entry, the quote-stripped copy fails, no interpreter is found.
    rc, out, seen = _run(tmp_path, "start.bat", "junk", _line(FILE_KEY),
                         path=_path(length, quoted=True))
    assert rc == 1, f"start.bat no longer refuses at {length}; re-measure RM-826 (e): {out!r}"
    assert _REFUSAL in out, out
    assert seen == [], f"start.bat went on past its refusal: {out!r}"


@win_only
@pytest.mark.parametrize("length", [8179, 20000])
def test_an_unquoted_python_folder_is_found_at_any_length(tmp_path, length):
    # The residual is the quoted entry only: the plain PATH search needs no
    # copy of PATH on a command line.
    rc, out, seen = _run(tmp_path, "start.bat", "junk", _line(FILE_KEY),
                         path=_path(length, quoted=False))
    assert rc == 0, out
    assert seen == [{}], f"the check did not run: {out!r}"
