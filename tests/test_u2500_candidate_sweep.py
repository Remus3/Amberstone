"""Drift guard: assert the 9 CANDIDATE files swept by item 187 stay
U+2500-free, plus pre/post sweep counts pinned for forensic value.

Background (item 187, 2026-05-25): operator-gated sweep of U+2500 BOX
DRAWINGS LIGHT HORIZONTAL (UTF-8 bytes e2 94 80) on 9 candidate files
identified in item 186 Slice E read-only audit. Top 20 repo-wide were
classified as 19 INTENTIONAL (live source section dividers in tests,
tools, scripts, core, dashboard, web/js/main.js, etc.) + 1 CANDIDATE
(_archive/2026-05-01-audit/tft/comp_control.py). Beyond the top 20, an
additional 8 candidates were surfaced (6 more archived dead Tk files,
web/legacy_index.html, ops/rc_config.json) for a total of 9 swept files.

Per-file pre/post counts at item 187 sweep:
    _archive/2026-05-01-audit/tft/comp_control.py        pre=886 -> post=0
    _archive/2026-05-01-audit/ui/client_panel.py         pre=576 -> post=0
    _archive/2026-05-01-audit/modes/arena_overlay.py     pre=330 -> post=0
    _archive/2026-05-01-audit/ui/game_right_bot.py       pre=185 -> post=0
    _archive/2026-05-01-audit/tft/tft_overlay.py         pre=116 -> post=0
    _archive/2026-05-01-audit/core/tk_ai_bar_proxy.py    pre= 97 -> post=0
    _archive/2026-05-01-audit/ui/base.py                 pre= 59 -> post=0
    web/legacy_index.html                                pre=349 -> post=0
    ops/rc_config.json                                   pre=276 -> post=0
    -----                                                ----------------
    total                                                pre=2874 -> post=0

The horizontal rules in source comments + JSON section-divider value
strings were normalized from the box-drawing glyph to plain ASCII '-'.
Visual width changes (the box-drawing glyph is roughly em-dash width;
ASCII '-' is narrower), but the semantic intent of a horizontal rule
is preserved.

SCOPE NOTE: U+2500 is NOT a banned codepoint globally (unlike smart
quotes / em-dashes which are CLAUDE.md hard-rule). It appears
intentionally in many non-frozen authored files across the repo (test
fixtures, docstrings, ASCII-art separators, ASCII-art tree-diagrams).
This guard asserts ONLY on the 9 item-187 candidate files; it does NOT
do a repo-wide ban on U+2500. The companion guard
tests/test_u2500_hygiene.py covers the same files via the broader
_ASSERTED_CLEAN frozenset; this file pins each path individually +
locks the pre/post counts for forensic value.

If this test fails on a re-introduction, run:
    $env:LOCALAPPDATA/Programs/Python/Python314/python.exe tools/strip_u2500.py --allow-frozen <path> --dry-run
    $env:LOCALAPPDATA/Programs/Python/Python314/python.exe tools/strip_u2500.py --allow-frozen <path>
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent

# UTF-8 byte sequence for U+2500 BOX DRAWINGS LIGHT HORIZONTAL.
# Constructed via \xNN escapes so this test file stays 7-bit ASCII.
_U2500_BYTES = b"\xe2\x94\x80"

# 9 candidate files swept at item 187 (2026-05-25).
# Each entry: (rel_posix_path, pre_count) - the pre-count locks the
# forensic record of how many U+2500 chars existed before the sweep.
_ITEM_187_SWEPT: tuple[tuple[str, int], ...] = (
    ("_archive/2026-05-01-audit/tft/comp_control.py", 886),
    ("_archive/2026-05-01-audit/ui/client_panel.py", 576),
    ("_archive/2026-05-01-audit/modes/arena_overlay.py", 330),
    ("_archive/2026-05-01-audit/ui/game_right_bot.py", 185),
    ("_archive/2026-05-01-audit/tft/tft_overlay.py", 116),
    ("_archive/2026-05-01-audit/core/tk_ai_bar_proxy.py", 97),
    ("_archive/2026-05-01-audit/ui/base.py", 59),
    ("web/legacy_index.html", 349),
    ("ops/rc_config.json", 276),
)

_EXPECTED_TOTAL_PRE = 2874

# RM-119 class B4, 2026-08-06. The seven `_archive/2026-05-01-audit/**` entries
# above each had their own test that read `if not p.is_file(): pytest.skip(...)`,
# and all seven skipped on every run, so the drift guard they exist to be had
# been asserting nothing.
#
# CORRECTION, and the reason this comment is long. The first pass at this fix
# claimed the targets were "gitignored, NEVER tracked, permanently unreachable".
# That is FALSE, and a verifier caught it: the files were ADDED at 63ac0acb,
# MODIFIED at 5db053d0 (item 187 - the very sweep recorded above), and REMOVED
# at 8c2afe21 on 2026-07-07. `git cat-file -e 8c2afe21^:<path>` succeeds for all
# seven, and `git checkout 8c2afe21^ -- _archive/2026-05-01-audit/` restores
# them. They are decommissioned, not unreachable - a distinction that decides
# the remedy, because "gone forever" argues for deleting the record while "gone
# from HEAD, recoverable from history" argues for pinning it.
#
# The first pass then made it WORSE by replacing the seven skips with a
# parametrized `assert rel_posix in _DECOMMISSIONED` where `_DECOMMISSIONED` was
# DERIVED by `rel.startswith("_archive/")` from the very tuple being checked.
# For those seven that assertion was true by construction and could not fail:
# seven announced SKIPs became seven silent green dots, so visibility went DOWN.
# That is `feedback_fixture_parallel_by_construction` exactly.
#
# What is here now:
#   * `_DECOMMISSIONED` is an explicit LITERAL, not derived from the tuple it
#     is checked against, so the aggregate walk's absence rule can actually
#     fail.
#   * The per-file glyph check is parametrized over the REACHABLE entries only,
#     so every parameter is a real U+2500 count on a file that exists.
#   * The decommission itself is asserted against GIT rather than assumed:
#     each of the seven must be absent from HEAD and present at the removal
#     commit's parent. Re-adding one to git turns this red and says so.
_ARCHIVE_REMOVED_AT = "8c2afe21"   # 2026-07-07 scratch-cleanup commit

_DECOMMISSIONED: tuple[str, ...] = (
    "_archive/2026-05-01-audit/tft/comp_control.py",
    "_archive/2026-05-01-audit/ui/client_panel.py",
    "_archive/2026-05-01-audit/modes/arena_overlay.py",
    "_archive/2026-05-01-audit/ui/game_right_bot.py",
    "_archive/2026-05-01-audit/tft/tft_overlay.py",
    "_archive/2026-05-01-audit/core/tk_ai_bar_proxy.py",
    "_archive/2026-05-01-audit/ui/base.py",
)

_REACHABLE: tuple[tuple[str, int], ...] = tuple(
    (rel, pre) for rel, pre in _ITEM_187_SWEPT if rel not in _DECOMMISSIONED
)

# Sentinel count used by the aggregate walk to distinguish "file is gone" from
# "file is present and dirty"; a real U+2500 count is never negative.
_MISSING = -1


def _count_u2500(path: Path) -> int:
    try:
        raw = path.read_bytes()
    except OSError:
        return 0
    return raw.count(_U2500_BYTES)


# -------- Per-file U+2500-clean assertions --------

@pytest.mark.parametrize("rel_posix,pre", _REACHABLE)
def test_item_187_reachable_file_is_u2500_clean(rel_posix: str, pre: int) -> None:
    """The real glyph check, over the entries that actually exist at HEAD.

    Parametrized over `_REACHABLE`, never over the full tuple: a parameter for
    a decommissioned file could only ever assert something about its own
    absence, and an assertion that cannot fail is worse than the skip it would
    replace - it is invisible instead of merely silent.
    """
    p = _REPO_ROOT / rel_posix
    assert p.is_file(), (
        f"{rel_posix} is tracked and expected in every checkout but is not on "
        "disk - its glyph guard has silently retired"
    )
    n = _count_u2500(p)
    assert n == 0, (
        f"{rel_posix} contains {n} U+2500 chars (item 187 swept it clean, "
        f"pre={pre} -> post=0)."
    )


def _git(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=str(_REPO_ROOT),
                          capture_output=True, text=True, timeout=60)


@pytest.mark.skipif(shutil.which("git") is None, reason="git not on PATH")
@pytest.mark.parametrize("rel_posix", _DECOMMISSIONED)
def test_decommissioned_target_is_gone_from_head_and_present_in_history(
    rel_posix: str,
) -> None:
    """Prove the removal instead of asserting it, and keep it falsifiable.

    Two halves, both able to fail:

    * NOT tracked at HEAD. If someone re-adds one of these, this goes red and
      the per-file glyph guard has to come back with it - which is the whole
      reason the entry was allowed to leave the sweep.
    * PRESENT at the removal commit's parent. This is what makes the
      decommission a checked claim rather than a comment, and it is what the
      first pass got wrong by asserting these files had never been tracked.
    """
    tracked = _git("ls-files", "--error-unmatch", rel_posix)
    assert tracked.returncode != 0, (
        f"{rel_posix} is TRACKED at HEAD again - it is listed as "
        "decommissioned, so either restore its per-file glyph guard or drop it "
        "from _DECOMMISSIONED"
    )
    in_history = _git("cat-file", "-e", f"{_ARCHIVE_REMOVED_AT}^:{rel_posix}")
    assert in_history.returncode == 0, (
        f"{rel_posix} is not present at {_ARCHIVE_REMOVED_AT}^, so the removal "
        "record in _DECOMMISSIONED is wrong - re-derive it from "
        f"`git log --diff-filter=DR -- {rel_posix}` before trusting this list"
    )


def test_web_legacy_index_html_is_clean() -> None:
    p = _REPO_ROOT / "web" / "legacy_index.html"
    # TRACKED in git (unlike the _archive/ targets above, which really are
    # gitignored + decommissioned), so it is present in every checkout and a
    # skip here would silently retire the glyph guard on a live file.
    assert p.is_file(), f"tracked {p} is missing from this checkout"
    n = _count_u2500(p)
    assert n == 0, (
        f"web/legacy_index.html contains {n} U+2500 chars (item 187 "
        f"swept it clean, pre=349 -> post=0)."
    )


def test_ops_rc_config_json_is_clean() -> None:
    p = _REPO_ROOT / "ops" / "rc_config.json"
    # TRACKED in git - see the sibling web/legacy_index.html guard above.
    assert p.is_file(), f"tracked {p} is missing from this checkout"
    n = _count_u2500(p)
    assert n == 0, (
        f"ops/rc_config.json contains {n} U+2500 chars (item 187 swept "
        f"it clean, pre=276 -> post=0)."
    )


# -------- Aggregate + post-sweep invariants --------

def test_all_item_187_swept_files_are_u2500_free() -> None:
    """Walk _ITEM_187_SWEPT + verify every entry is U+2500-free.

    Parallels the per-file tests above but iterates so any future
    extension to the tuple is automatically covered.
    """
    violations: list[tuple[str, int]] = []
    for rel_posix, _pre in _ITEM_187_SWEPT:
        p = _REPO_ROOT / rel_posix
        if not p.is_file():
            # RM-119 B4: this used to `continue` on ANY absent entry, which
            # silently dropped a tracked file from the sweep as readily as a
            # decommissioned archive one. Absence is now only tolerated for the
            # seven cleared `_archive/` targets; anything else is a violation.
            if rel_posix not in _DECOMMISSIONED:
                violations.append((rel_posix, _MISSING))
            continue
        n = _count_u2500(p)
        if n > 0:
            violations.append((rel_posix, n))
    if violations:
        lines = [
            f"  {rel}: MISSING from this checkout and not decommissioned"
            if n == _MISSING else f"  {rel}: U+2500 x{n}"
            for rel, n in violations
        ]
        msg = (
            "U+2500 drift detected in item-187-swept candidate files. "
            "Run `$env:LOCALAPPDATA/Programs/Python/Python314/python.exe tools/strip_u2500.py --allow-frozen <path>` to "
            "repair. Violations:\n" + "\n".join(lines)
        )
        pytest.fail(msg)


def test_item_187_pre_count_total_pin() -> None:
    """Sanity-pin the aggregate pre-count (2874) - this is the forensic
    anchor for how much glyph-density was eliminated by the sweep.
    Future audits comparing repo-wide U+2500 totals against the pre/post
    delta should match this anchor.
    """
    total = sum(pre for _rel, pre in _ITEM_187_SWEPT)
    assert total == _EXPECTED_TOTAL_PRE, (
        f"item 187 aggregate pre-count drift: expected "
        f"{_EXPECTED_TOTAL_PRE}, got {total}"
    )


def test_item_187_swept_set_size() -> None:
    """Pin the candidate count at 9 (the item 187 sweep size)."""
    assert len(_ITEM_187_SWEPT) == 9


def test_this_drift_guard_is_ascii() -> None:
    """This test file MUST be 7-bit ASCII (no literal U+2500 glyph, no
    em-dash, no smart-quote, no other non-ASCII codepoint).
    """
    raw = Path(__file__).read_bytes()
    non_ascii = [(i, b) for i, b in enumerate(raw) if b > 127]
    assert not non_ascii, (
        f"tests/test_u2500_candidate_sweep.py has {len(non_ascii)} "
        f"non-ASCII bytes; first at offset {non_ascii[0][0]}"
    )
