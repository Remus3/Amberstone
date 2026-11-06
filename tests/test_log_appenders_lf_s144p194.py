"""RM-481 residual (s144, RM-1705): four more tools/ log appenders write LF.

Four text-mode append opens passed no ``newline=``, so on Windows every line
carried CRLF:

- tools/start_daemon_slayer.py ``_write_log_line`` (daemon_slayer_startup.log);
- tools/start_ds_matchdb_mcp.py ``_write_log_line`` (ds_matchdb_mcp_startup.log);
- tools/build_rank_baselines.py ``--log-file`` stdout/stderr sink;
- tools/sibling_name_sweep.py ``_append_bypass_log`` (the BYPASS log).

CI is Linux, where the text layer does not translate, so the behaviour tests
run under a harness that forces CRLF on any text-mode write that passes no
``newline=``; a positive control proves the harness bites. The AST scan is the
OS-independent half and reuses the RM-1701 scanner.
"""
from __future__ import annotations

import builtins
import io
import sys

import pytest

from tests._repo_walk import REPO_ROOT
from tests.test_shadow_appenders_lf_s144p190 import _append_offenders

_MODULES = (
    "tools/start_daemon_slayer.py",
    "tools/start_ds_matchdb_mcp.py",
    "tools/build_rank_baselines.py",
    "tools/sibling_name_sweep.py",
)


@pytest.mark.parametrize("rel", _MODULES)
def test_no_bare_text_mode_append(rel):
    path = REPO_ROOT / rel
    assert path.is_file(), f"{rel} missing - the scan would be vacuous"
    found = _append_offenders(path.read_bytes().decode("utf-8"))
    assert found == [], (
        f'{rel}: text-mode append without newline="\\n" writes CRLF rows on '
        f"Windows (lines {found})")


@pytest.fixture
def crlf_text_layer(monkeypatch):
    """Reproduce the Windows LF -> CRLF text translation on every OS."""
    orig_open = builtins.open

    def _open(file, mode="r", *args, **kwargs):
        if ("b" not in mode and any(c in mode for c in "wax+")
                and len(args) < 3 and kwargs.get("newline") is None):
            kwargs["newline"] = "\r\n"
        return orig_open(file, mode, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", _open)
    monkeypatch.setattr(io, "open", _open)


def test_positive_control_path_open_append_produces_crlf(tmp_path,
                                                         crlf_text_layer):
    target = tmp_path / "control.log"
    with target.open("a", encoding="utf-8") as fh:
        fh.write("a\nb\n")
    assert target.read_bytes() == b"a\r\nb\r\n", "harness failed to force CRLF"


@pytest.mark.parametrize("modname", ["start_daemon_slayer",
                                     "start_ds_matchdb_mcp"])
def test_startup_log_line_appends_lf(modname, tmp_path, crlf_text_layer):
    mod = __import__(f"tools.{modname}", fromlist=["_write_log_line"])
    target = tmp_path / "logs" / "startup.log"
    assert mod._write_log_line(target, "one\n") is True
    assert mod._write_log_line(target, "two\n") is True
    assert target.read_bytes() == b"one\ntwo\n"


def test_sibling_sweep_bypass_log_appends_lf(tmp_path, monkeypatch,
                                             crlf_text_layer):
    from tools import sibling_name_sweep as sweep
    monkeypatch.setenv(sweep.BYPASS_LOG_ENV, str(tmp_path / "bypass.log"))
    sweep._append_bypass_log("first")
    sweep._append_bypass_log("second")
    assert (tmp_path / "bypass.log").read_bytes() == b"first\nsecond\n"


def test_build_rank_baselines_log_file_sink_is_lf(tmp_path, monkeypatch,
                                                  crlf_text_layer):
    from tools import build_rank_baselines as brb
    log = tmp_path / "sub" / "run.log"
    monkeypatch.setattr(brb, "_others_running", lambda: False)
    monkeypatch.setattr(sys, "stdout", sys.stdout)
    monkeypatch.setattr(sys, "stderr", sys.stderr)

    class _Stop(Exception):
        pass

    def _boom(*_a, **_k):
        raise _Stop

    # The sink is installed before any network work; stop right after it by
    # making the first post-sink step (the cohort-file read) raise.
    monkeypatch.setattr(brb, "_existing_cohorts", _boom)
    try:
        with pytest.raises(_Stop):
            brb.main(["--log-file", str(log), "--out",
                      str(tmp_path / "out.json")])
        print("line one")
        print("line two", file=sys.stderr)
        sys.stdout.flush()
    finally:
        sink = sys.stdout
        if sink is not sys.__stdout__ and hasattr(sink, "close"):
            sys.stdout = sys.__stdout__
            sys.stderr = sys.__stderr__
            sink.close()
    raw = log.read_bytes()
    assert b"\r" not in raw
    assert raw.endswith(b"line one\nline two\n")
