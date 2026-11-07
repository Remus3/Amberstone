"""RM-2037: name each failing test the moment it fails, so a killed run still names it.

CI run 42383196203 (Linux, py3.12, xdist --dist loadfile) hit its 110 m step
ceiling at [ 95%] before pytest printed a summary: 72 failures were counted
from progress characters and none was named. pytest only names a failure in
its end-of-run sections, so any run that dies before them (a step ceiling, a
job kill, --session-timeout) loses every name.

This plugin prints, for every FAILED report (a call failure, a setup or a
teardown error, an xdist worker crash), one line at once and flushes it:

    RC-FAIL <when> <nodeid> :: <first error line, ASCII-safe, <= 200 chars>

It runs in the CONTROLLING process only. Under xdist the controller receives
every worker's report through `pytest_runtest_logreport`, and a worker's own
terminal output is not relayed, so `install` skips a worker
(`config.workerinput`) and each failure is named exactly once.

Gate (read once, at session start): on under CI (`CI=true` or
`GITHUB_ACTIONS=true`, which GitHub Actions sets for every job) or with
`RC_FAIL_FAST_NAMES=1`; `RC_FAIL_FAST_NAMES=0` turns it off even under CI;
off by default locally. It never changes an outcome: it only reads reports,
and nothing in it may raise into pytest.

Wiring: the rootdir conftest.py re-exports `pytest_sessionstart`, which
reaches both suites (`tests/` and `agents/daemon_slayer/tests/`); a run that
does not load that conftest can load this module with
`-p tests._fail_fast_names`. Pinned by tests/test_ci_fail_fast_names_rm2037.py.
"""

from __future__ import annotations

import os
import re
import sys

import pytest

PLUGIN_NAME = "rc-fail-fast-names"
ENV_SWITCH = "RC_FAIL_FAST_NAMES"
PREFIX = "RC-FAIL"
MAX_ERROR_CHARS = 200
_NO_TEXT = "(no error text)"
_ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")
# xdist's worker info line (xdist getworkerinfoline):
# "[gw1] win32 -- Python 3.14.4 C:\...\python.exe".
_WORKER_HEADER = re.compile(r"^\[[^\]\s]+\] \S+ -- Python \S+")


def enabled(environ=None) -> bool:
    """The gate: RC_FAIL_FAST_NAMES=1 on, =0 off, else on under CI."""
    env = os.environ if environ is None else environ
    switch = str(env.get(ENV_SWITCH, "")).strip()
    if switch == "1":
        return True
    if switch == "0":
        return False
    return any(str(env.get(name, "")).strip().lower() == "true" for name in ("CI", "GITHUB_ACTIONS"))


def ascii_safe(text) -> str:
    """One ASCII line: ANSI colour codes dropped, other control characters
    made spaces, anything past 7-bit written as a backslash escape."""
    text = _ANSI.sub("", str(text))
    text = text.encode("ascii", "backslashreplace").decode("ascii")
    return _CONTROL.sub(" ", text)


def _truncate(text: str, limit: int = MAX_ERROR_CHARS) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 3] + "..."


def _first_line(text) -> str:
    for line in str(text).splitlines():
        if line.strip():
            return line.strip()
    return ""


def first_error_line(report) -> str:
    """The line pytest's short summary would show for this report.

    A traceback longrepr carries `reprcrash.message` (the `E` line). Under
    xdist any other longrepr (a missing fixture, a collection-style error)
    arrives as plain text whose first line is the file, so the first `E` line
    wins there, then the first non-blank line.

    A plain-string longrepr (an XPASS(strict), an xdist worker crash) is read
    as itself: `longreprtext` renders it behind xdist's
    "[gw1] <platform> -- Python <ver> <exe>" worker header, and that header
    is never the message (verifier finding on 49ef0ccea).
    """
    try:
        crash = getattr(report.longrepr, "reprcrash", None)
        line = _first_line(getattr(crash, "message", "") or "")
        if line:
            return line
    except Exception:  # noqa: BLE001 - a report that cannot render still gets named
        pass
    text = ""
    try:
        if isinstance(report.longrepr, str):
            text = report.longrepr
    except Exception:  # noqa: BLE001
        text = ""
    if not text:
        try:
            text = report.longreprtext or ""
        except Exception:  # noqa: BLE001
            text = ""
    if not text:
        try:
            text = "" if report.longrepr is None else str(report.longrepr)
        except Exception:  # noqa: BLE001
            text = ""
    lines = [ln.strip() for ln in text.splitlines() if ln.strip() and not _WORKER_HEADER.match(ln.strip())]
    for ln in lines:
        if ln.startswith("E ") or ln == "E":
            found = ln[1:].strip()
            if found:
                return found
    return lines[0] if lines else ""


def format_line(report) -> str:
    when = ascii_safe(getattr(report, "when", None) or "?")
    nodeid = ascii_safe(getattr(report, "nodeid", None) or "?")
    try:
        error = _truncate(ascii_safe(first_error_line(report)))
    except Exception:  # noqa: BLE001
        error = ""
    return f"{PREFIX} {when} {nodeid} :: {error or _NO_TEXT}"


class FailFastNames:
    """The per-config plugin object `install` registers in the controller."""

    def __init__(self, config):
        self._config = config

    @pytest.hookimpl(trylast=True)
    def pytest_runtest_logreport(self, report):
        try:
            if not getattr(report, "failed", False):
                return
            self._emit(format_line(report))
        except Exception:  # noqa: BLE001 - never turn a report into an INTERNALERROR
            pass

    def _emit(self, line: str) -> None:
        reporter = None
        try:
            reporter = self._config.pluginmanager.get_plugin("terminalreporter")
        except Exception:  # noqa: BLE001
            reporter = None
        writer = getattr(reporter, "_tw", None)
        if reporter is not None and writer is not None:
            # trylast: the progress letter for this report is already out.
            # Start a fresh line (ensure_newline covers the default verbosity,
            # the width check -q's bare progress line), so RC-FAIL always
            # opens its own line and a grep for it never misses.
            reporter.ensure_newline()
            if getattr(writer, "width_of_current_line", 0):
                writer.line()
            writer.line(line)
            writer.flush()
            return
        sys.stderr.write(line + "\n")
        sys.stderr.flush()


def install(config) -> bool:
    """Register the plugin on ``config`` when the gate is on and this is the
    controlling process. Idempotent. Returns whether it registered."""
    if hasattr(config, "workerinput"):
        return False
    if not enabled():
        return False
    if config.pluginmanager.has_plugin(PLUGIN_NAME):
        return False
    config.pluginmanager.register(FailFastNames(config), PLUGIN_NAME)
    return True


def pytest_sessionstart(session):
    install(session.config)
