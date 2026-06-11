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
    C:/Users/Administrator/AppData/Local/Programs/Python/Python314/python.exe tools/strip_u2500.py --allow-frozen <path> --dry-run
    C:/Users/Administrator/AppData/Local/Programs/Python/Python314/python.exe tools/strip_u2500.py --allow-frozen <path>
"""
from __future__ import annotations

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


def _count_u2500(path: Path) -> int:
    try:
        raw = path.read_bytes()
    except OSError:
        return 0
    return raw.count(_U2500_BYTES)


# -------- Per-file U+2500-clean assertions --------

def test_archive_comp_control_is_clean() -> None:
    p = _REPO_ROOT / "_archive" / "2026-05-01-audit" / "tft" / "comp_control.py"
    assert p.is_file(), f"target file missing at {p}"
    n = _count_u2500(p)
    assert n == 0, (
        f"_archive/2026-05-01-audit/tft/comp_control.py contains {n} "
        f"U+2500 chars (item 187 swept it clean, pre=886 -> post=0)."
    )


def test_archive_client_panel_is_clean() -> None:
    p = _REPO_ROOT / "_archive" / "2026-05-01-audit" / "ui" / "client_panel.py"
    assert p.is_file(), f"target file missing at {p}"
    n = _count_u2500(p)
    assert n == 0, (
        f"_archive/2026-05-01-audit/ui/client_panel.py contains {n} "
        f"U+2500 chars (item 187 swept it clean, pre=576 -> post=0)."
    )


def test_archive_arena_overlay_is_clean() -> None:
    p = _REPO_ROOT / "_archive" / "2026-05-01-audit" / "modes" / "arena_overlay.py"
    assert p.is_file(), f"target file missing at {p}"
    n = _count_u2500(p)
    assert n == 0, (
        f"_archive/2026-05-01-audit/modes/arena_overlay.py contains {n} "
        f"U+2500 chars (item 187 swept it clean, pre=330 -> post=0)."
    )


def test_archive_game_right_bot_is_clean() -> None:
    p = _REPO_ROOT / "_archive" / "2026-05-01-audit" / "ui" / "game_right_bot.py"
    assert p.is_file(), f"target file missing at {p}"
    n = _count_u2500(p)
    assert n == 0, (
        f"_archive/2026-05-01-audit/ui/game_right_bot.py contains {n} "
        f"U+2500 chars (item 187 swept it clean, pre=185 -> post=0)."
    )


def test_archive_tft_overlay_is_clean() -> None:
    p = _REPO_ROOT / "_archive" / "2026-05-01-audit" / "tft" / "tft_overlay.py"
    assert p.is_file(), f"target file missing at {p}"
    n = _count_u2500(p)
    assert n == 0, (
        f"_archive/2026-05-01-audit/tft/tft_overlay.py contains {n} "
        f"U+2500 chars (item 187 swept it clean, pre=116 -> post=0)."
    )


def test_archive_tk_ai_bar_proxy_is_clean() -> None:
    p = _REPO_ROOT / "_archive" / "2026-05-01-audit" / "core" / "tk_ai_bar_proxy.py"
    assert p.is_file(), f"target file missing at {p}"
    n = _count_u2500(p)
    assert n == 0, (
        f"_archive/2026-05-01-audit/core/tk_ai_bar_proxy.py contains {n} "
        f"U+2500 chars (item 187 swept it clean, pre=97 -> post=0)."
    )


def test_archive_ui_base_is_clean() -> None:
    p = _REPO_ROOT / "_archive" / "2026-05-01-audit" / "ui" / "base.py"
    assert p.is_file(), f"target file missing at {p}"
    n = _count_u2500(p)
    assert n == 0, (
        f"_archive/2026-05-01-audit/ui/base.py contains {n} U+2500 chars "
        f"(item 187 swept it clean, pre=59 -> post=0)."
    )


def test_web_legacy_index_html_is_clean() -> None:
    p = _REPO_ROOT / "web" / "legacy_index.html"
    assert p.is_file(), f"target file missing at {p}"
    n = _count_u2500(p)
    assert n == 0, (
        f"web/legacy_index.html contains {n} U+2500 chars (item 187 "
        f"swept it clean, pre=349 -> post=0)."
    )


def test_ops_rc_config_json_is_clean() -> None:
    p = _REPO_ROOT / "ops" / "rc_config.json"
    assert p.is_file(), f"target file missing at {p}"
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
            pytest.fail(f"asserted-swept file missing: {rel_posix}")
        n = _count_u2500(p)
        if n > 0:
            violations.append((rel_posix, n))
    if violations:
        lines = [f"  {rel}: U+2500 x{n}" for rel, n in violations]
        msg = (
            "U+2500 drift detected in item-187-swept candidate files. "
            "Run `C:/Users/Administrator/AppData/Local/Programs/Python/Python314/python.exe tools/strip_u2500.py --allow-frozen <path>` to "
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
