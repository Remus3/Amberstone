"""s144 true-audit (RM-1043): core/anthropic_key.py hardening.

Findings pinned here, each RED against the pre-audit module:

F1  A key file saved by PowerShell 5.1 with ``>`` / ``Out-File`` (UTF-16LE
    with a BOM) or ``-Encoding BigEndianUnicode`` was rejected as undecodable,
    so a good key silently became "no coaching".
F2  ``usable_key`` let through ASCII control characters that are not
    whitespace (NUL, BEL, Ctrl-Z from ``copy con``, ESC, DEL) and the bare
    ``sk-ant-`` prefix. Such a value is header-hostile, so it failed every
    request instead of degrading - and an env value of that kind shadowed a
    good key file.
F3  The template install.bat writes when the key file is missing
    (``sk-ant-YOUR-KEY-HERE``) passed as a usable key.  # rc-credential-scan: allow-fixture
F4  The key file was read whole, however large.
F5  A key that was present but rejected degraded with nothing logged; the
    operator had no way to learn why coaching was off. It is now warned once
    per streak, naming the source and the reason, never the value.

The fixtures below are synthetic; none is a real key.
"""
from __future__ import annotations

import logging
import os
import subprocess
import sys

import pytest

from core import anthropic_key

ENV_VAR = anthropic_key.ENV_VAR
KEY_FILE = anthropic_key.KEY_FILENAME
FILE_KEY = "sk-ant-TESTONLYs144file"  # rc-credential-scan: allow-fixture
ENV_KEY = "sk-ant-TESTONLYs144env"  # rc-credential-scan: allow-fixture
SECRETISH = "sk-ant-TESTONLYs144secretmarker"  # rc-credential-scan: allow-fixture
LOGGER = "core.anthropic_key"


@pytest.fixture
def root(tmp_path, monkeypatch):
    monkeypatch.setattr(anthropic_key, "_KEY_ROOT", tmp_path)
    monkeypatch.delenv(ENV_VAR, raising=False)
    monkeypatch.setattr(anthropic_key, "_last_warning", None, raising=False)
    return tmp_path


def _write(root, raw: bytes) -> None:
    (root / KEY_FILE).write_bytes(raw)


# ---------------------------------------------------------------------------
# F1 - UTF-16 key files (PowerShell 5.1 defaults)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("raw", [
    pytest.param((FILE_KEY + "\r\n").encode("utf-16"), id="utf16-native-bom"),
    pytest.param(b"\xff\xfe" + (FILE_KEY + "\r\n").encode("utf-16-le"), id="utf16le-bom-crlf"),
    pytest.param(b"\xfe\xff" + (FILE_KEY + "\r\n").encode("utf-16-be"), id="utf16be-bom-crlf"),
    pytest.param(b"\xff\xfe" + FILE_KEY.encode("utf-16-le"), id="utf16le-bom-no-newline"),
])
def test_a_utf16_key_file_with_a_bom_is_read(root, raw):
    _write(root, raw)
    assert anthropic_key.read_anthropic_key() == FILE_KEY


def test_a_utf16_file_with_an_odd_byte_count_degrades(root):
    _write(root, b"\xff\xfe" + FILE_KEY.encode("utf-16-le") + b"\x00\x00\x41")
    assert anthropic_key.read_anthropic_key() == ""


def test_the_utf8_paths_still_read(root):
    _write(root, b"\xef\xbb\xbf  " + FILE_KEY.encode("ascii") + b"\r\n")
    assert anthropic_key.read_anthropic_key() == FILE_KEY
    _write(root, FILE_KEY.encode("ascii"))
    assert anthropic_key.read_anthropic_key() == FILE_KEY


# ---------------------------------------------------------------------------
# F2 - control characters and the bare prefix
# ---------------------------------------------------------------------------

_CONTROL = ["\x00", "\x01", "\x07", "\x08", "\x1a", "\x1b", "\x7f"]


@pytest.mark.parametrize("ch", _CONTROL, ids=[f"0x{ord(c):02x}" for c in _CONTROL])
def test_usable_key_refuses_a_control_character(ch):
    assert not anthropic_key.usable_key("sk-ant-abc" + ch + "def")
    assert not anthropic_key.usable_key("sk-ant-abcdef" + ch)


@pytest.mark.parametrize("ch", _CONTROL, ids=[f"0x{ord(c):02x}" for c in _CONTROL])
def test_a_key_file_with_a_control_character_degrades(root, ch):
    # Ctrl-Z (0x1a) is what `copy con` leaves at the end of a file.
    _write(root, (FILE_KEY + ch + "\r\n").encode("ascii"))
    assert anthropic_key.read_anthropic_key() == ""


@pytest.mark.parametrize("ch", ["\x01", "\x1a", "\x1b", "\x7f"])
def test_an_env_value_with_a_control_character_falls_through_to_the_file(
        root, monkeypatch, ch):
    monkeypatch.setenv(ENV_VAR, ENV_KEY + ch)
    _write(root, (FILE_KEY + "\r\n").encode("ascii"))
    assert anthropic_key.read_anthropic_key() == FILE_KEY


def test_the_bare_prefix_is_not_a_key(root, monkeypatch):
    assert not anthropic_key.usable_key(anthropic_key.KEY_PREFIX)
    _write(root, b"sk-ant-\r\n")
    assert anthropic_key.read_anthropic_key() == ""
    monkeypatch.setenv(ENV_VAR, "sk-ant-")
    _write(root, (FILE_KEY + "\r\n").encode("ascii"))
    assert anthropic_key.read_anthropic_key() == FILE_KEY


@pytest.mark.parametrize("key", [
    "sk-ant-a!b%PATH%c&d^e|f<g>h",  # rc-credential-scan: allow-fixture
    'sk-ant-x"&echo.INJECTED>injected.txt&rem."',  # rc-credential-scan: allow-fixture
    "sk-ant-api03-AAAA_bbbb-0123",  # rc-credential-scan: allow-fixture
    "sk-ant-~",  # rc-credential-scan: allow-fixture
])
def test_printable_ascii_keys_stay_usable(key):
    # The RM-810 launcher table keeps cmd-special keys usable; the check is
    # "survives an HTTP header", not a guess at Anthropic's alphabet.
    assert anthropic_key.usable_key(key)


@pytest.mark.parametrize("key", [None, 7, b"sk-ant-abc", ["sk-ant-abc"]])
def test_usable_key_refuses_a_non_str(key):
    assert not anthropic_key.usable_key(key)


# ---------------------------------------------------------------------------
# F3 - the install.bat template placeholder
# ---------------------------------------------------------------------------

def test_the_install_template_placeholder_is_not_a_key(root, monkeypatch):
    # install.bat step 3 writes exactly this line when the file is missing.
    assert anthropic_key.TEMPLATE_PLACEHOLDER == "sk-ant-YOUR-KEY-HERE"  # rc-credential-scan: allow-fixture
    assert not anthropic_key.usable_key("sk-ant-YOUR-KEY-HERE")  # rc-credential-scan: allow-fixture
    _write(root, b"sk-ant-YOUR-KEY-HERE\r\n")  # rc-credential-scan: allow-fixture
    assert anthropic_key.read_anthropic_key() == ""
    monkeypatch.setenv(ENV_VAR, "sk-ant-YOUR-KEY-HERE")  # rc-credential-scan: allow-fixture
    _write(root, (FILE_KEY + "\r\n").encode("ascii"))
    assert anthropic_key.read_anthropic_key() == FILE_KEY


def test_install_bat_still_writes_the_placeholder_this_module_refuses():
    text = (anthropic_key.REPO_ROOT / "install.bat").read_text(encoding="ascii")
    assert "echo " + anthropic_key.TEMPLATE_PLACEHOLDER + '> "%API_FILE%"' in text


# ---------------------------------------------------------------------------
# F4 - bounded read
# ---------------------------------------------------------------------------

def test_an_oversized_key_file_is_refused(root):
    cap = anthropic_key.MAX_KEY_FILE_BYTES
    assert 256 <= cap <= 65536
    raw = FILE_KEY.encode("ascii") + b"\r\n"
    _write(root, raw + b" " * (cap + 1 - len(raw)))
    assert anthropic_key.read_anthropic_key() == ""


def test_a_key_file_at_the_cap_is_still_read(root):
    cap = anthropic_key.MAX_KEY_FILE_BYTES
    raw = FILE_KEY.encode("ascii") + b"\r\n"
    _write(root, raw + b" " * (cap - len(raw)))
    assert anthropic_key.read_anthropic_key() == FILE_KEY


def test_the_read_never_pulls_more_than_the_cap(root, monkeypatch):
    cap = anthropic_key.MAX_KEY_FILE_BYTES
    _write(root, b"x" * (cap * 8))
    sizes = []
    real_open = anthropic_key.Path.open

    def spy_open(self, *a, **kw):
        fh = real_open(self, *a, **kw)
        real_read = fh.read

        def read(n=-1):
            sizes.append(n)
            return real_read(n)
        fh.read = read
        return fh

    monkeypatch.setattr(anthropic_key.Path, "open", spy_open)
    assert anthropic_key.read_anthropic_key() == ""
    assert sizes and all(0 <= n <= cap + 1 for n in sizes), sizes


# ---------------------------------------------------------------------------
# F5 - a rejected key is warned once per streak, never with its value
# ---------------------------------------------------------------------------

def _warnings(caplog):
    return [r for r in caplog.records
            if r.name == LOGGER and r.levelno == logging.WARNING]


def _all_text(caplog) -> str:
    parts = []
    for r in caplog.records:
        parts.append(r.getMessage())
        parts.append(repr(r.args))
        parts.append(repr(r.msg))
    return "\n".join(parts)


def test_a_rejected_key_file_is_warned_once_without_its_value(root, caplog):
    caplog.set_level(logging.DEBUG, logger=LOGGER)
    _write(root, (SECRETISH + " tail\r\n").encode("ascii"))
    for _ in range(3):
        assert anthropic_key.read_anthropic_key() == ""
    warns = _warnings(caplog)
    assert len(warns) == 1, [w.getMessage() for w in warns]
    msg = warns[0].getMessage()
    assert KEY_FILE in msg
    assert "whitespace or a control character" in msg
    assert SECRETISH not in _all_text(caplog)
    assert "TESTONLY" not in _all_text(caplog)


def test_a_rejected_env_value_is_warned_once_without_its_value(root, monkeypatch,
                                                               caplog):
    caplog.set_level(logging.DEBUG, logger=LOGGER)
    monkeypatch.setenv(ENV_VAR, "not-" + SECRETISH)
    _write(root, (FILE_KEY + "\r\n").encode("ascii"))
    for _ in range(3):
        assert anthropic_key.read_anthropic_key() == FILE_KEY
    warns = _warnings(caplog)
    assert len(warns) == 1, [w.getMessage() for w in warns]
    assert ENV_VAR in warns[0].getMessage()
    assert "prefix" in warns[0].getMessage()
    assert "TESTONLY" not in _all_text(caplog)


def test_a_usable_read_ends_the_streak_and_a_new_reason_warns(root, caplog):
    caplog.set_level(logging.DEBUG, logger=LOGGER)
    _write(root, b"sk-ant-YOUR-KEY-HERE\r\n")  # rc-credential-scan: allow-fixture
    anthropic_key.read_anthropic_key()
    anthropic_key.read_anthropic_key()
    assert len(_warnings(caplog)) == 1
    _write(root, (FILE_KEY + "\r\n").encode("ascii"))
    assert anthropic_key.read_anthropic_key() == FILE_KEY
    _write(root, b"sk-ant-YOUR-KEY-HERE\r\n")  # rc-credential-scan: allow-fixture
    anthropic_key.read_anthropic_key()
    assert len(_warnings(caplog)) == 2
    _write(root, b"\xff\xfe\x00")
    anthropic_key.read_anthropic_key()
    warns = _warnings(caplog)
    assert len(warns) == 3
    assert "UTF-8 or UTF-16" in warns[-1].getMessage()


@pytest.mark.parametrize("raw,reason", [
    pytest.param(b"sk-ant-YOUR-KEY-HERE\r\n", "placeholder", id="placeholder"),  # rc-credential-scan: allow-fixture
    pytest.param(b"sk-ant-\r\n", "nothing after", id="bare-prefix"),
    pytest.param(b"not-a-key\r\n", "prefix", id="no-prefix"),
    pytest.param("sk-ant-ab\u00e9c\r\n".encode(), "non-ASCII", id="non-ascii"),
    pytest.param(b"\r\n", "empty", id="blank"),
])
def test_each_rejection_names_its_reason(root, caplog, raw, reason):
    caplog.set_level(logging.DEBUG, logger=LOGGER)
    _write(root, raw)
    assert anthropic_key.read_anthropic_key() == ""
    warns = _warnings(caplog)
    assert len(warns) == 1
    assert reason in warns[0].getMessage()


def test_an_oversized_file_names_its_size_reason(root, caplog):
    caplog.set_level(logging.DEBUG, logger=LOGGER)
    _write(root, b"x" * (anthropic_key.MAX_KEY_FILE_BYTES + 1))
    assert anthropic_key.read_anthropic_key() == ""
    assert "larger than" in _warnings(caplog)[0].getMessage()


def test_no_key_anywhere_is_not_warned(root, caplog):
    # Both absent is the documented no-coaching state, not a rejection.
    caplog.set_level(logging.DEBUG, logger=LOGGER)
    assert anthropic_key.read_anthropic_key() == ""
    assert _warnings(caplog) == []


def test_a_usable_key_is_never_warned(root, monkeypatch, caplog):
    caplog.set_level(logging.DEBUG, logger=LOGGER)
    _write(root, (FILE_KEY + "\r\n").encode("ascii"))
    assert anthropic_key.read_anthropic_key() == FILE_KEY
    monkeypatch.setenv(ENV_VAR, ENV_KEY)
    assert anthropic_key.read_anthropic_key() == ENV_KEY
    assert _warnings(caplog) == []


def test_an_unreadable_file_names_only_the_error_class(root, monkeypatch,
                                                         caplog):
    caplog.set_level(logging.DEBUG, logger=LOGGER)
    _write(root, (FILE_KEY + "\r\n").encode("ascii"))

    def boom(self, *a, **kw):
        raise PermissionError(13, "denied", str(self))

    monkeypatch.setattr(anthropic_key.Path, "open", boom)
    assert anthropic_key.read_anthropic_key() == ""
    msg = _warnings(caplog)[0].getMessage()
    assert "PermissionError" in msg
    assert str(root) not in msg


def test_the_warning_never_reaches_a_handlerless_console(root, capsys):
    # start.bat / restart.bat / start_debug.bat run this file through
    # runpy with no logging configured: a warning must not print there.
    _write(root, b"not-a-key\r\n")
    root_logger = logging.getLogger()
    saved = root_logger.handlers[:]
    root_logger.handlers = []
    try:
        assert anthropic_key.read_anthropic_key() == ""
    finally:
        root_logger.handlers = saved
    err = capsys.readouterr().err
    assert "not usable" not in err and KEY_FILE not in err, err


_RUNPY_PROBE = (
    "import runpy,sys;k=runpy.run_path(sys.argv[1]);"
    "print('GOOD' if k['read_anthropic_key'](sys.argv[2]) == sys.argv[3] else 'BAD');"
    "print('JUNK' if k['read_anthropic_key'](sys.argv[4]) == '' else 'BAD');"
    "print('TEMPLATE' if not k['usable_key'](k['TEMPLATE_PLACEHOLDER']) else 'BAD')"
)


def test_a_runpy_load_still_works_standalone_and_prints_nothing_else(tmp_path):
    # The launchers run the module by path with `python -I` through runpy,
    # with no logging configured: it must stay stdlib-only, and a refused
    # key must not print a warning into the launcher console.
    good = tmp_path / "good"
    junk = tmp_path / "junk"
    good.mkdir()
    junk.mkdir()
    (good / KEY_FILE).write_bytes(b"\xff\xfe" + FILE_KEY.encode("utf-16-le"))
    (junk / KEY_FILE).write_bytes(b"not-a-key\r\n")
    env = {k: v for k, v in os.environ.items() if k.upper() != ENV_VAR}
    proc = subprocess.run(
        [sys.executable, "-I", "-c", _RUNPY_PROBE,
         str(anthropic_key.REPO_ROOT / "core" / "anthropic_key.py"),
         str(good), FILE_KEY, str(junk)],
        env=env, stdin=subprocess.DEVNULL, capture_output=True, timeout=60,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0), check=False)
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.decode("ascii").split() == ["GOOD", "JUNK", "TEMPLATE"]
    assert proc.stderr == b"", proc.stderr
