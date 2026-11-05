# arch: mc/auth.py true-audit regression pins (s144 cycle 129) | section=tests | frozen=no
"""mc/auth.py - the :8895 bearer gate never raises and fails closed visibly.

Findings this file pins (s144 true-audit cycle 129, RM-1608..RM-1612):

  RM-1608  A non-ASCII Authorization header (the stdlib decodes header
              bytes as iso-8859-1, so b"\\xe9" arrives as "\\u00e9") made
              ``hmac.compare_digest`` raise TypeError on str operands. An
              unauthenticated caller turned the documented byte-identical 401
              into a 500 "internal error" plus a WARNING traceback line.
  RM-1609  A token file written with a UTF-8 BOM (PowerShell 5.1
              ``Set-Content -Encoding UTF8``, Notepad) resolved to
              "\\ufeff<token>": ``str.strip`` keeps U+FEFF, so every POST -
              the CORRECT token included - raised TypeError and was a 500.
              The control plane was dead with a misleading error.
  RM-1610  A token file that is not UTF-8 raised UnicodeDecodeError (a
              ValueError, not the OSError the reader caught) out of
              ``resolve_token``: every POST was a 500 instead of the fail-closed
              503, and the handler logged the decode error, whose text quotes
              a BYTE OF THE SECRET ("can't decode byte 0xff in position 2").
  RM-1611  A token holding whitespace, control or non-ASCII characters
              (env or file) was accepted as configured. One that cannot be
              sent as a header value is now "unconfigured" (503, fail closed,
              never a fall-through to the other source) with a rate-limited
              WARNING naming the source and the problem - never the token.
  RM-1612  ``str.splitlines`` also breaks on U+2028, U+0085, \\x0b, \\x0c
              and \\x1c-\\x1e, so a token file "abc<U+2028>rest" resolved to
              the SHORTER token "abc" and accepted it. The first line now ends
              at a newline only; such a line is unusable (503).

The fake-request harness mirrors tests/test_mc_headless_control_plane.py.
"""
from __future__ import annotations

import json
import logging
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from mc import auth, handler, routes  # noqa: E402

TOKEN = "synthetic-mc-token-0123456789abcdef"  # rc-credential-scan: allow-fixture
UNAUTH = {"ok": False, "error": "unauthorized"}
UNCONF = {"ok": False, "error": "auth not configured"}
# Non-ASCII built with chr() so this source stays 7-bit ASCII.
E_ACUTE = chr(0xE9)   # what header byte 0xe9 decodes to (iso-8859-1)
Y_UMLAUT = chr(0xFF)
A_MACRON = chr(0x100)
BOM = chr(0xFEFF)


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.delenv("RC_MC_TOKEN", raising=False)
    monkeypatch.setattr(auth, "TOKEN_FILE", tmp_path / "absent.txt")
    auth._reset_warnings()
    yield
    auth._reset_warnings()


def _file(tmp_path, monkeypatch, data: bytes) -> Path:
    tf = tmp_path / "mission_control_token.txt"
    tf.write_bytes(data)
    monkeypatch.setattr(auth, "TOKEN_FILE", tf)
    return tf


def _warnings(caplog):
    return [r for r in caplog.records
            if r.name == "rc.mc.auth" and r.levelno == logging.WARNING]


# ------------------------------------------------ RM-1608 header side

@pytest.mark.parametrize("header", [
    "Bearer s3cr" + E_ACUTE + "t",   # iso-8859-1 decoded byte 0xe9
    "Bearer " + TOKEN + Y_UMLAUT,    # right prefix, one high byte appended
    "Bearer " + A_MACRON,            # beyond latin-1 (a direct caller)
    "Bearer \ud800",                 # lone surrogate
])
def test_non_ascii_header_is_the_plain_401(monkeypatch, header):
    monkeypatch.setenv("RC_MC_TOKEN", TOKEN)
    assert auth.check(header) == (False, 401, UNAUTH)
    assert auth.check(header)[2] == auth.check(None)[2]


@pytest.mark.parametrize("header", [123, b"Bearer x", ["Bearer", TOKEN]])
def test_non_str_header_is_the_plain_401(monkeypatch, header):
    monkeypatch.setenv("RC_MC_TOKEN", TOKEN)
    assert auth.check(header) == (False, 401, UNAUTH)


def test_correct_token_still_passes(monkeypatch):
    monkeypatch.setenv("RC_MC_TOKEN", TOKEN)
    assert auth.check("Bearer " + TOKEN) == (True, 200, {})
    assert auth.check("Bearer   " + TOKEN + "  ") == (True, 200, {})


def test_do_post_with_non_ascii_header_is_401_not_500(monkeypatch):
    """End to end through Handler.do_POST: the route never runs."""
    monkeypatch.setenv("RC_MC_TOKEN", TOKEN)
    reached = []
    monkeypatch.setattr(routes, "POST_ROUTES",
                        [(lambda p: True, lambda h, b: reached.append(b))])

    class Fake:
        path = "/api/loop-control"

        def __init__(self):
            self.sent = None
            self.rfile = None
            self.headers = {"Authorization": "Bearer s3cr" + E_ACUTE + "t",
                            "Content-Length": "2"}

        def _send(self, code, body, ctype, cache_control=None):
            self.sent = (code, body, ctype)

        _send_json = handler.Handler._send_json

    f = Fake()
    handler.Handler.do_POST(f)
    code, raw, _ = f.sent
    assert code == 401
    assert json.loads(raw.decode("utf-8")) == UNAUTH
    assert reached == []


# ------------------------------------------------ RM-1609 BOM file

def test_bom_token_file_resolves_without_the_bom(tmp_path, monkeypatch):
    _file(tmp_path, monkeypatch, b"\xef\xbb\xbf" + TOKEN.encode() + b"\r\n")
    assert auth.resolve_token() == TOKEN
    assert auth.check("Bearer " + TOKEN) == (True, 200, {})
    assert auth.check("Bearer wrong") == (False, 401, UNAUTH)


# ------------------------------------------------ RM-1610 non-UTF-8 file

def test_non_utf8_token_file_is_503_and_never_logs_a_byte(
        tmp_path, monkeypatch, caplog):
    _file(tmp_path, monkeypatch, b"s3\xffcret\n")
    caplog.set_level(logging.WARNING, logger="rc.mc.auth")
    assert auth.resolve_token() is None
    assert auth.check("Bearer s3cret") == (False, 503, UNCONF)
    recs = _warnings(caplog)
    assert len(recs) == 1
    msg = recs[0].getMessage()
    assert "config" in msg and "UTF-8" in msg
    for leak in ("0xff", "\\xff", "s3", "cret", "position"):
        assert leak not in msg


# ------------------------------------------------ RM-1611 unusable token

@pytest.mark.parametrize("bad", [
    "has space", "tab\there", "ctl\x01x", "caf" + E_ACUTE, BOM + "bom",
    "x\x7fy", "two\nlines",
])
def test_unusable_env_token_is_503_with_a_warning(monkeypatch, caplog, bad):
    monkeypatch.setenv("RC_MC_TOKEN", bad)
    caplog.set_level(logging.WARNING, logger="rc.mc.auth")
    assert auth.resolve_token() is None
    assert auth.check("Bearer " + bad) == (False, 503, UNCONF)
    recs = _warnings(caplog)
    assert len(recs) == 1
    msg = recs[0].getMessage()
    assert "RC_MC_TOKEN" in msg
    assert bad.strip() not in msg


@pytest.mark.parametrize("bad", [b"has space", b"tab\there", b"ctl\x01x",
                                 ("caf" + E_ACUTE).encode()])
def test_unusable_file_token_is_503_with_a_warning(
        tmp_path, monkeypatch, caplog, bad):
    _file(tmp_path, monkeypatch, bad + b"\n")
    caplog.set_level(logging.WARNING, logger="rc.mc.auth")
    assert auth.resolve_token() is None
    recs = _warnings(caplog)
    assert len(recs) == 1
    msg = recs[0].getMessage()
    assert "config" in msg
    assert bad.decode("utf-8").strip() not in msg


@pytest.mark.parametrize("sep", [chr(0x2028), chr(0x85), "\x0b", "\x0c",
                                 "\x1c", "\x1d", "\x1e"])
def test_a_unicode_line_break_never_truncates_the_file_token(
        tmp_path, monkeypatch, sep):
    """RM-1612: str.splitlines broke "abc<sep>rest" into the token "abc",
    so a SHORTER secret than the one written was accepted."""
    _file(tmp_path, monkeypatch, ("abc" + sep + "restofsecret\n").encode())
    assert auth.resolve_token() is None
    assert auth.check("Bearer abc") == (False, 503, UNCONF)


def test_crlf_and_lone_cr_still_end_the_first_line(tmp_path, monkeypatch):
    for data in (TOKEN.encode() + b"\r\nsecond\r\n",
                 TOKEN.encode() + b"\rsecond", TOKEN.encode()):
        _file(tmp_path, monkeypatch, data)
        assert auth.resolve_token() == TOKEN


def test_unusable_env_never_falls_through_to_a_good_file(
        tmp_path, monkeypatch):
    """Fail closed: the operator set the env token, so the file is not used."""
    monkeypatch.setenv("RC_MC_TOKEN", "bad token")
    _file(tmp_path, monkeypatch, TOKEN.encode() + b"\n")
    assert auth.resolve_token() is None
    assert auth.check("Bearer " + TOKEN) == (False, 503, UNCONF)


def test_warning_is_rate_limited_per_problem(monkeypatch, caplog):
    clock = [1000.0]
    monkeypatch.setattr(auth, "_now", lambda: clock[0])
    monkeypatch.setenv("RC_MC_TOKEN", "bad token")
    caplog.set_level(logging.WARNING, logger="rc.mc.auth")
    for _ in range(5):
        auth.check("Bearer x")
    assert len(_warnings(caplog)) == 1
    clock[0] += auth._WARN_INTERVAL_S + 1
    auth.check("Bearer x")
    assert len(_warnings(caplog)) == 2


def test_a_missing_or_blank_source_stays_silent(tmp_path, monkeypatch, caplog):
    """Unconfigured is a normal state, not a warning (characterization)."""
    caplog.set_level(logging.WARNING, logger="rc.mc.auth")
    assert auth.check("Bearer x") == (False, 503, UNCONF)
    _file(tmp_path, monkeypatch, b"\n")
    assert auth.check("Bearer x") == (False, 503, UNCONF)
    assert _warnings(caplog) == []


def test_check_never_raises_on_any_header_shape(tmp_path, monkeypatch):
    for data in (b"\xef\xbb\xbf\n", b"\xff\xfe", TOKEN.encode()):
        _file(tmp_path, monkeypatch, data)
        for header in (None, "", "Bearer", "Bearer " + E_ACUTE, "Bearer \ud800",
                       "Bearer " + TOKEN, 0, object()):
            ok, status, body = auth.check(header)
            assert status in (200, 401, 503)
            assert isinstance(body, dict)
