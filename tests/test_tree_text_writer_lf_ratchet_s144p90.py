"""RM-481 residual (s144, RM-1362): a tree-wide ratchet on text-mode writers.

tests/test_tracked_writer_lf_sweep.py pins NAMED lists (SWEPT_WRITERS,
SWEPT_REPORT_WRITERS): a writer that is not on a list is invisible to it, so
the fix for a new writer was "remember to add it". This module inverts that,
the way the RM-258 atomic-write guard does for tools/: EVERY tracked non-test
.py is in scope, and the files below are the only ones allowed to carry a bare
write_text / write-mode open / csv writer (no explicit newline= or
lineterminator=). The set only shrinks: a new writer starts guarded, and an
entry that stops offending fails test_baseline_is_exact until it is dropped.

Measured 2026-11-04 over the git index with the sweep's own _violations:
12 files outside both lists. ops/loop/inbox_tick.py, ops/phase3_setup.py,
ops/rc_self_monitor.py, tools/bootstrap_env_check.py, tools/dev_cli.py and
tools/run_phase2_perf.py wrote newline-free payloads (a lock pid, an empty
placeholder, "paused", "x", one-line JSON), so the line ending was
unobservable; RM-1528 (2026-11-05) pinned newline="\\n" on all of them and
they left the baseline. tools/ci_watchdog.py wrote a multi-line
markdown context file and was converted (newline="\\n"). The five left are
frozen, kit-owned or byte-pinned and are the main session's to change.

RM-1540 closes the RM-481 residual by measurement: an AST walk over every
tracked non-test .py found no text-mode writer outside this set and the swept
lists. The detector's two blind spots are shut (a computed open() mode and a
text-mode NamedTemporaryFile / TemporaryFile / SpooledTemporaryFile were
invisible; tools/ci_impact_selector.py's `'a' if append else 'w'` open already
passes newline="\\n"), and the tree stays clean under the stricter detector.

Append-mode sinks stay out of scope, as the sweep module's docstring rules:
they are gitignored runtime logs, never tracked files.
"""
from __future__ import annotations

import pathlib


from tests._repo_walk import REPO_ROOT, relative_posix, repo_files
from tests.test_tracked_writer_lf_sweep import (
    SWEPT_REPORT_WRITERS,
    SWEPT_WRITERS,
    _violations,
    force_crlf,  # noqa: F401 - fixture re-exported for the behaviour test
)

# rel path -> why it may keep a bare text-mode write. Only shrinks.
_BASELINE = {
    # Frozen (CLAUDE.md): not edited without explicit operator approval.
    "core/log_setup.py": "frozen",
    "ops/rc_dev_runtime.py": "frozen",
    # Owned elsewhere: kit file, byte-pinned pair, excluded packaging tool.
    "ops/fleet_kit/fleet_lanes.py": "kit-owned (MAIN)",
    "ops/loop/slots.py": "SHARED_SHA256 byte pin",
    "tools/run_packaged_smoke.py": "packaging, main session owns",
    # RM-1528: the six newline-free-payload entries (inbox_tick, phase3_setup,
    # rc_self_monitor, bootstrap_env_check, dev_cli, run_phase2_perf) now pass
    # newline="\n", so a later edit that adds a "\n" to a payload cannot start
    # emitting CRLF; they left this set (sixteen call sites).
}


def _in_scope(rel: str) -> bool:
    name = rel.rsplit("/", 1)[-1]
    if rel.startswith("tests/") or "/tests/" in rel:
        return False
    return not (name.startswith("test_") or name == "conftest.py")


def _offenders() -> dict[str, list[str]]:
    swept = set(SWEPT_WRITERS) | set(SWEPT_REPORT_WRITERS)
    out: dict[str, list[str]] = {}
    for path in repo_files(REPO_ROOT, ("*.py",)):
        rel = relative_posix(path)
        if rel in swept or not _in_scope(rel):
            continue
        found = _violations(path.read_text(encoding="utf-8"))
        if found:
            out[rel] = found
    return out


def test_walk_is_not_vacuous():
    rels = {relative_posix(p) for p in repo_files(REPO_ROOT, ("*.py",))}
    assert "tools/ci_watchdog.py" in rels
    assert "core/polled_json.py" in rels
    assert len(rels) > 500


def test_no_unclassified_text_mode_writer():
    new = {r: v for r, v in _offenders().items() if r not in _BASELINE}
    assert not new, (
        "text-mode write without newline= / lineterminator= (CRLF on Windows): "
        f'{new}. Pass newline="\\n" (or write bytes); a payload with no '
        "newline joins _BASELINE with its reason.")


def test_baseline_is_exact():
    offenders = _offenders()
    stale = sorted(r for r in _BASELINE if r not in offenders)
    assert not stale, f"no longer offend - drop from _BASELINE: {stale}"
    missing = [r for r in _BASELINE if not (REPO_ROOT / r).is_file()]
    assert not missing, f"not tracked files: {missing}"


def test_baseline_does_not_overlap_the_swept_lists():
    assert not set(_BASELINE) & (set(SWEPT_WRITERS) | set(SWEPT_REPORT_WRITERS))


def test_ratchet_detects_a_new_writer():
    """The detector the ratchet leans on flags the shapes it must."""
    assert _violations("from pathlib import Path\nPath('x').write_text('a\\nb')\n")
    assert not _violations(
        "from pathlib import Path\n"
        "Path('x').write_text('a\\nb', encoding='utf-8', newline='\\n')\n")


def test_ci_watchdog_context_file_is_lf(tmp_path, force_crlf):  # noqa: F811
    """RM-1362: the context file the watchdog drops for claude is multi-line
    markdown; under the Windows translation it was CRLF."""
    from tools import ci_watchdog as cw

    cw._write_context(tmp_path, 7, "abc1234", "line1\nline2", "+a\n-b")
    raw = pathlib.Path(tmp_path / cw._CONTEXT_FILE).read_bytes()
    assert raw.count(b"\n") > 5
    assert b"\r" not in raw
