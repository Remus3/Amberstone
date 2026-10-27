"""s144 lane 8 true-audit of core/vision_token.py.

Findings, each pinned red-first:
- F1: an EMPTY config/vision_token.txt raised IndexError out of ``_resolve``
  (``"".splitlines()[0]``). The module's contract is RuntimeError, and it runs
  at import in the dashboard and the vision server, so callers that catch
  RuntimeError got an unnamed IndexError traceback instead.
- F2: a config file that EXISTS but is unreadable, not UTF-8 (a PowerShell 5.1
  ``"tok" > file`` writes UTF-16) or has an empty first line raised "no token
  configured ... write a token to <path>" - false, a file is there. The error
  now names what is wrong with it, never its content.
- F3: ``debug()`` is documented to PRINT the source and masked token, but it
  only logged at INFO, so ``python -c "from core.vision_token import debug;
  debug()"`` printed nothing at all.
- F4: ``debug()`` "never prints the full secret", but masked any token of 8+
  chars as first4...last4 - the WHOLE of an 8-char token and 8 of 9. It now
  shows first4...last4 only from 32 chars up (at most a quarter revealed).
"""
from __future__ import annotations

import logging
import sys
import traceback
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core import vision_token as vt  # noqa: E402

SECRET = "SEKRETPART"


@pytest.fixture
def cfg(tmp_path, monkeypatch):
    path = tmp_path / "vision_token.txt"
    monkeypatch.delenv("RC_VISION_TOKEN", raising=False)
    monkeypatch.setattr(vt, "_CONFIG_PATH", path)
    return path


def _raise_text(exc: BaseException) -> str:
    return "".join(traceback.format_exception(exc))


# ---------------------------------------------------------------- F1


def test_empty_config_file_raises_runtime_error_not_index_error(cfg):
    cfg.write_bytes(b"")
    with pytest.raises(RuntimeError) as ei:
        vt._resolve()
    assert "empty" in str(ei.value)
    assert "no token configured" not in str(ei.value)


# ---------------------------------------------------------------- F2


def test_blank_first_line_names_the_empty_line_and_not_line_two(cfg):
    cfg.write_bytes(f"\n{SECRET}\n".encode("ascii"))
    with pytest.raises(RuntimeError) as ei:
        vt._resolve()
    assert "first line is empty" in str(ei.value)
    assert SECRET not in _raise_text(ei.value)


def test_whitespace_only_first_line_is_the_empty_case(cfg):
    cfg.write_bytes(b"   \t \r\n")
    with pytest.raises(RuntimeError) as ei:
        vt._resolve()
    assert "first line is empty" in str(ei.value)


def test_utf16_config_names_the_encoding_without_leaking_bytes(cfg):
    cfg.write_bytes(f"dead{SECRET}\r\n".encode("utf-16"))
    with pytest.raises(RuntimeError) as ei:
        vt._resolve()
    msg = str(ei.value)
    assert "not UTF-8" in msg
    assert "no token configured" not in msg
    assert SECRET not in _raise_text(ei.value)


def test_non_utf8_byte_is_never_echoed_in_the_traceback(cfg):
    # The UnicodeDecodeError text names the offending byte ("0xe9") - a byte
    # of the token. It must not ride along as the exception context.
    cfg.write_bytes(b"dead\xe9beef\n")
    with pytest.raises(RuntimeError) as ei:
        vt._resolve()
    text = _raise_text(ei.value)
    assert "0xe9" not in text
    assert "UnicodeDecodeError" not in text


def test_unreadable_config_names_the_error_class_only(cfg, monkeypatch):
    cfg.write_bytes(b"deadbeef\n")

    def _denied(self, *a, **k):
        raise PermissionError(13, f"Access is denied {SECRET}")

    monkeypatch.setattr(type(cfg), "read_text", _denied)
    with pytest.raises(RuntimeError) as ei:
        vt._resolve()
    msg = str(ei.value)
    assert "could not be read (PermissionError)" in msg
    assert "no token configured" not in msg
    assert SECRET not in _raise_text(ei.value)


def test_directory_at_the_config_path_is_unreadable_not_absent(cfg):
    cfg.mkdir()
    with pytest.raises(RuntimeError) as ei:
        vt._resolve()
    assert "could not be read (" in str(ei.value)
    assert "no token configured" not in str(ei.value)


def test_missing_config_still_says_no_token_configured(cfg):
    assert not cfg.exists()
    with pytest.raises(RuntimeError) as ei:
        vt._resolve()
    assert "no token configured" in str(ei.value)
    assert "RC_VISION_TOKEN" in str(ei.value)


def test_bom_config_still_fails_loud_like_the_first_run_mirror(cfg):
    # Parity with ops/launcher/first_run.py valid_token and tools/lcu_agent.py,
    # which would send the BOM: a BOM file is refused, never silently accepted.
    cfg.write_bytes(b"\xef\xbb\xbfdeadbeef\n")
    with pytest.raises(RuntimeError) as ei:
        vt._resolve()
    assert "non-ASCII" in str(ei.value)


# ---------------------------------------------------------------- characterization


def test_env_wins_over_config(cfg, monkeypatch):
    cfg.write_bytes(b"fromconfig\n")
    monkeypatch.setenv("RC_VISION_TOKEN", "fromenv")
    assert vt._resolve() == ("fromenv", "env")
    assert vt.get_vision_token() == "fromenv"
    assert vt.get_vision_token_source() == "env"


def test_blank_env_falls_through_to_config(cfg, monkeypatch):
    cfg.write_bytes(b"  fromconfig  \nignored\n")
    monkeypatch.setenv("RC_VISION_TOKEN", "   ")
    assert vt._resolve() == ("fromconfig", "config")


def test_bad_env_never_falls_back_to_config(cfg, monkeypatch):
    cfg.write_bytes(b"fromconfig\n")
    monkeypatch.setenv("RC_VISION_TOKEN", "a b")
    with pytest.raises(RuntimeError) as ei:
        vt._resolve()
    assert "env token" in str(ei.value)


def test_crlf_config_resolves(cfg):
    cfg.write_bytes(b"deadbeef\r\nsecond\r\n")
    assert vt._resolve() == ("deadbeef", "config")


# ---------------------------------------------------------------- F3 / F4


def test_debug_prints_to_stdout(cfg, monkeypatch, capsys):
    tok = "0123456789abcdef0123456789abcdef"
    monkeypatch.setenv("RC_VISION_TOKEN", tok)
    vt.debug()
    out = capsys.readouterr().out
    assert "source=env" in out
    assert "token=0123...cdef" in out
    assert "len=32" in out
    assert tok not in out


def test_debug_also_logs_the_masked_line(cfg, monkeypatch, caplog):
    tok = "0123456789abcdef0123456789abcdef"
    monkeypatch.setenv("RC_VISION_TOKEN", tok)
    caplog.set_level(logging.INFO, logger="core.vision_token")
    vt.debug()
    msgs = [r.getMessage() for r in caplog.records]
    assert any("token=0123...cdef" in m for m in msgs)
    assert all(tok not in m for m in msgs)


@pytest.mark.parametrize("n", [1, 7, 8, 9, 12, 16, 31])
def test_debug_reveals_nothing_of_a_short_token(cfg, monkeypatch, capsys, n):
    tok = "".join("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghij"[i] for i in range(n))
    monkeypatch.setenv("RC_VISION_TOKEN", tok)
    vt.debug()
    out = capsys.readouterr().out
    assert "(short)" in out
    assert f"len={n}" in out
    assert tok[:4] not in out
    assert tok[-4:] not in out
