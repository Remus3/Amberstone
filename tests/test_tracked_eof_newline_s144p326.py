"""S144-P-326 - every tracked source / doc file ends in exactly one newline; the blank-line-at-EOF set only shrinks.

A file with no final newline makes ``git diff`` print ``\\ No newline at end of file``, makes ``cat a b`` glue two files'
last and first lines together, and is the usual way a lane's appended line lands on the previous line. A file that ends
in a blank line (W391) is the opposite drift: every later append diffs against an empty line. Neither is enforced by
ruff.toml (``E``/``F``/``I``/``UP``/``B``/``BLE`` only, no ``W``), and the markdown, JS, CSS, PowerShell and batch files
are outside ruff altogether.

Scope: the tracked source and doc suffixes below. ``.json`` / ``.jsonl`` / ``.txt`` are data written by tools (531 of 1084
tracked ``.json`` files carry no final newline by design, and ``data/daemon_slayer/current.txt`` is a one-line pointer),
and ``.xml`` / ``.svg`` are generated or exported artifacts (4 files lack one), so they are out of scope on purpose.

Measured 2026-11-07 over 5235 tracked files in scope:

- 0 non-empty files with no final newline (held at zero here; resolve the file, never widen the test);
- 29 files that end in a blank line, named in ``_BLANK_EOF_BASELINE``. The set only shrinks: a file that stops offending
  fails ``test_blank_eof_baseline_is_exact`` until it is dropped from the set, and a new offender fails the guard. The
  frozen ``ops/rc_supervisor.py`` and ``web_dashboard.py`` entries and the dated ``docs/_archive`` record stay named
  rather than fixed.

Each shape has a positive control, so a rule that stopped detecting fails loudly instead of passing for nothing.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from tests._repo_walk import REPO_ROOT, tracked_relpaths

_SCOPE_SUFFIXES = (
    ".py", ".md", ".js", ".mjs", ".css", ".html", ".yml", ".yaml", ".toml",
    ".ps1", ".bat", ".cmd", ".sh", ".ahk", ".vbs",
)

_BLANK_EOF_BASELINE = frozenset({
    "agents/daemon_slayer/ability_dps.py",
    "coach_integration/_coach.py",
    "coach_integration/_profiles.py",
    "coach_integration/_sr_prompt.py",
    "core/prom_metrics.py",
    "dashboard/_state_builder.py",
    "docs/_archive/2026-07-18-agent6-auditor-reports/20260714-140459-weekly-rc-health.md",
    "docs/_overlap/sample_60_blinded.md",
    "docs/_rescore/ROWS_PINNED.md",
    "docs/_rsc_score/rc198_blinded.md",
    "ops/audit/HZ_MISMATCH_DIAGNOSE.md",
    "ops/audit/ds_cross_eval/REPORT.md",
    "ops/rc_self_monitor.py",
    "ops/rc_supervisor.py",
    "tests/_lfs_policy.py",
    "tests/test_log_setup_prune_cap_rm162.py",
    "tests/test_redundant_collection_call_ratchet_s144p115.py",
    "tests/test_small_idiom_ratchet_s144p122.py",
    "tests/test_store_states_json_p25.py",
    "web/css/panels/base.css",
    "web/css/panels/grid.css",
    "web/css/panels/header.css",
    "web/css/panels/input_activity.css",
    "web/css/panels/item_build.css",
    "web/css/panels/map_state.css",
    "web/css/panels/next.css",
    "web/css/panels/primitives.css",
    "web/css/panels/right_now.css",
    "web_dashboard.py",
})


def _eof_problems(raw: bytes) -> list[str]:
    """The EOF problems in ``raw``: ``"no-newline"`` and / or ``"blank-eof"``. An empty file has none."""
    if not raw:
        return []
    if not raw.endswith(b"\n"):
        return ["no-newline"]
    if raw.endswith((b"\n\n", b"\r\n\r\n")):
        return ["blank-eof"]
    return []


def _scoped_paths() -> list[str]:
    tracked = tracked_relpaths(str(REPO_ROOT))
    assert tracked is not None, "git index unreadable: a guard must not pass on an unreadable index"
    return sorted(rel for rel in tracked if rel.lower().endswith(_SCOPE_SUFFIXES) and (Path(REPO_ROOT) / rel).is_file())


def _scan() -> dict[str, list[str]]:
    found: dict[str, list[str]] = {"no-newline": [], "blank-eof": []}
    for rel in _scoped_paths():
        for problem in _eof_problems((Path(REPO_ROOT) / rel).read_bytes()):
            found[problem].append(rel)
    return found


def test_enumeration_is_not_vacuous():
    paths = _scoped_paths()
    assert len(paths) > 3000
    assert sum(1 for p in paths if p.endswith(".py")) > 2000
    assert sum(1 for p in paths if p.endswith(".md")) > 400


def test_no_tracked_source_or_doc_file_lacks_a_final_newline():
    assert _scan()["no-newline"] == []


def test_no_new_file_ends_in_a_blank_line():
    new = sorted(set(_scan()["blank-eof"]) - _BLANK_EOF_BASELINE)
    assert new == [], "ends in a blank line (strip the trailing empty line): " + ", ".join(new)


def test_blank_eof_baseline_is_exact():
    """An entry that stopped offending (fixed, deleted or renamed) must leave the set."""
    stale = sorted(_BLANK_EOF_BASELINE - set(_scan()["blank-eof"]))
    assert stale == [], "no longer ends in a blank line, drop from _BLANK_EOF_BASELINE: " + ", ".join(stale)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (b"x = 1", ["no-newline"]),
        (b"x = 1\ny = 2", ["no-newline"]),
        (b"# note\n\n", ["blank-eof"]),
        (b"a {}\r\n\r\n", ["blank-eof"]),
        (b"x = 1\n\n\n", ["blank-eof"]),
    ],
)
def test_checker_flags_each_shape(raw, expected):
    assert _eof_problems(raw) == expected


@pytest.mark.parametrize(
    "raw",
    [b"", b"x = 1\n", b"a {}\r\n", b"x = 1\n\ny = 2\n", b"\n"],
)
def test_checker_passes_lookalikes(raw):
    # b"\n" is a single newline: not "no newline", and not a blank line AFTER content.
    assert _eof_problems(raw) == []
