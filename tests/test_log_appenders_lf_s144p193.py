"""RM-481 residual (s144, RM-1704): three more tools/ log appenders write LF.

Three text-mode ``open(..., "a", encoding="utf-8")`` sites passed no
``newline=``, so on Windows every line carried CRLF:

- tools/cost_health_watchdog.py ``_log_line`` (logs/cost_health_watchdog.log);
- tools/moon_sync_poller.py ``_log_line`` (poller.log in the state dir);
- tools/rofl_dedupe.py ``append_sample`` (data/rofl_archive_growth.jsonl).

CI is Linux, where the text layer does not translate, so the behaviour tests
run under a harness that forces CRLF on any text-mode write that passes no
``newline=``; a positive control proves the harness bites. The AST scan is the
OS-independent half and reuses the RM-1701 scanner.
"""
from __future__ import annotations

import builtins
import io
import json

import pytest

from tests._repo_walk import REPO_ROOT
from tests.test_shadow_appenders_lf_s144p190 import _append_offenders

_MODULES = (
    "tools/cost_health_watchdog.py",
    "tools/moon_sync_poller.py",
    "tools/rofl_dedupe.py",
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


def test_cost_health_watchdog_log_line_appends_lf(tmp_path, monkeypatch,
                                                  crlf_text_layer):
    from tools import cost_health_watchdog as chw
    log = tmp_path / "logs" / "cost_health_watchdog.log"
    monkeypatch.setattr(chw, "_LOG", log)
    chw._log_line("first")
    chw._log_line("second")
    raw = log.read_bytes()
    assert b"\r" not in raw
    lines = raw.decode("utf-8").split("\n")
    assert lines[-1] == ""
    assert [ln.split(" ", 1)[1] for ln in lines[:-1]] == ["first", "second"]


def test_moon_sync_poller_log_line_appends_lf(tmp_path, monkeypatch,
                                              crlf_text_layer):
    from tools import moon_sync_poller as poller
    monkeypatch.setattr(poller, "state_dir", lambda: tmp_path)
    poller._log_line("first")
    poller._log_line("second")
    raw = (tmp_path / "poller.log").read_bytes()
    assert b"\r" not in raw
    lines = raw.decode("utf-8").split("\n")
    assert lines[-1] == ""
    assert [ln.split(" ", 1)[1] for ln in lines[:-1]] == ["first", "second"]


def test_rofl_dedupe_growth_sample_appends_lf(tmp_path, monkeypatch,
                                              crlf_text_layer):
    from tools import rofl_dedupe
    monkeypatch.setattr(rofl_dedupe, "__file__",
                        str(tmp_path / "tools" / "rofl_dedupe.py"))
    root = tmp_path / "replays"
    root.mkdir()
    (root / "a.rofl").write_bytes(b"x" * 8)
    for stamp in ("t1", "t2"):
        dest = rofl_dedupe.append_sample(root, stamp)
    assert dest == tmp_path / "data" / "rofl_archive_growth.jsonl"
    raw = dest.read_bytes()
    assert b"\r" not in raw
    rows = [json.loads(r) for r in raw.decode("utf-8").split("\n") if r]
    assert [r["at"] for r in rows] == ["t1", "t2"]
