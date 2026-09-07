"""Drift guard: assert no Unicode smart quotes / en-em dashes / NBSP / ellipsis
in authored source files.

Hard rule (CLAUDE.md, 2026-05-18): no em-dashes / en-dashes / smart quotes in
any authored text - keep authored content 7-bit ASCII. This test is the
companion drift guard for tools/strip_smart_quotes.py (same exclusion list).

If this test fails on a freshly added file, run:
    $env:LOCALAPPDATA/Programs/Python/Python314/python.exe tools/strip_smart_quotes.py            # dry-run report
    $env:LOCALAPPDATA/Programs/Python/Python314/python.exe tools/strip_smart_quotes.py --apply    # rewrite in place

Codepoints checked (mirrors strip_smart_quotes.py):
    U+201C  LEFT DOUBLE QUOTATION MARK
    U+201D  RIGHT DOUBLE QUOTATION MARK
    U+2018  LEFT SINGLE QUOTATION MARK
    U+2019  RIGHT SINGLE QUOTATION MARK
    U+2013  EN DASH
    U+2014  EM DASH
    U+2026  HORIZONTAL ELLIPSIS
    U+00A0  NON-BREAKING SPACE

EXCLUSIONS (parallel to the strip tool):
    - .git/, __pycache__/, _archive/, node_modules/
    - *.log / *.log.N, *.jsonl
    - binary: .pyc .pyd .db .png .jpg .jpeg .gif .webp .ico .zip .gz .exe
              .dll .lnk .woff .woff2 .ttf .bin .so .o
    - data/daemon_slayer/**/*.json (DDragon snapshots; external data)
    - data/meta_build/**/* (dated refresh artifacts; vendored third-party HTML)
    - data/meta/ddragon_champions.json (DDragon mirror; external data)
    - this test file itself + tools/strip_smart_quotes.py (both contain the
      codepoint constants intentionally, via chr() so they remain 7-bit ASCII)

MOJIBAKE allowance: files with U+201D bytes appearing in mojibake byte
context (e2 80 9d adjacent to e2 82 ac for U+20AC EURO sign) are flagged
to the report but allowed - those are pre-existing legacy mojibake of
em-dash / box-drawing characters that need separate hand-fix and are
NOT smart-quote drift.

FROZEN files: per CLAUDE.md the strip tool refuses to rewrite frozen
files. As of the RC2 P7.1 ASCII-sweep close (operator greenlight
2026-06-20, TOP-10 #10 "frozen INCLUDED"), this guard NO LONGER skips
frozen files - the banned-set walk now asserts on EVERY tracked authored
file including the frozen list, so a banned glyph cannot hide in a frozen
file undetected. The _FROZEN set is retained for the explicit per-file
regression lock test_frozen_files_clean_of_banned_glyphs.
"""
from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent

# Codepoints we ban. Built via chr() so this test file stays 7-bit ASCII.
_BANNED = {
    0x201C: "LEFT DOUBLE QUOTATION MARK",
    0x201D: "RIGHT DOUBLE QUOTATION MARK",
    0x2018: "LEFT SINGLE QUOTATION MARK",
    0x2019: "RIGHT SINGLE QUOTATION MARK",
    0x2013: "EN DASH",
    0x2014: "EM DASH",
    0x2026: "HORIZONTAL ELLIPSIS",
    0x00A0: "NON-BREAKING SPACE",
}

# UTF-8 byte sequences for each banned codepoint.
_BANNED_BYTES = {
    cp: chr(cp).encode("utf-8") for cp in _BANNED
}

# Mojibake neighbour for U+201D context check.
_MOJI_NEIGHBOUR = b"\xe2\x82\xac"  # U+20AC EURO SIGN bytes
_RDQUO_BYTES = b"\xe2\x80\x9d"

# Exclusions mirrored from tools/strip_smart_quotes.py
_SKIP_DIR_PARTS = {"_archive", "node_modules", "__pycache__", ".git"}
_SKIP_EXT = {
    ".pyc", ".pyd", ".db", ".png", ".jpg", ".jpeg", ".gif", ".webp",
    ".ico", ".zip", ".gz", ".exe", ".dll", ".lnk", ".woff", ".woff2",
    ".ttf", ".bin", ".so", ".o",
    ".jsonl",
}
_LOG_RE = re.compile(r"\.log(\.\d+)?$", re.IGNORECASE)

# Files that legitimately contain banned codepoints in chr() form (ASCII).
# These are the strip tool + this test itself - they reference the
# codepoints in docstrings as U+201C etc but never as literal glyphs.
# The test asserts on RAW BYTES so chr()-constructed runtime strings
# do not trigger.
_TEST_FILE = Path(__file__).resolve().as_posix()


def _is_external_data(rel_posix: str) -> bool:
    if rel_posix.startswith("data/daemon_slayer/") and rel_posix.endswith(".json"):
        return True
    if rel_posix.startswith("data/meta_build/"):
        return True
    if rel_posix == "data/meta/ddragon_champions.json":
        return True
    # DDragon-delivered item / spell catalogs may carry punctuation Riot
    # shipped (en-dashes in patch notes, etc); allowlist with the other
    # external-data mirrors.
    if rel_posix in {"data/meta/ddragon_items.json",
                     "data/meta/ddragon_runes.json",
                     "data/meta/ddragon_summoner_spells.json"}:
        return True
    return False


def _should_skip(path: Path, rel_posix: str) -> bool:
    abs_p = path.resolve().as_posix()
    if abs_p == _TEST_FILE:
        return True
    if rel_posix == "tools/strip_smart_quotes.py":
        return True
    if set(path.parts) & _SKIP_DIR_PARTS:
        return True
    name = path.name.lower()
    if _LOG_RE.search(name):
        return True
    if name.endswith((".db-shm", ".db-wal")):
        return True
    if path.suffix.lower() in _SKIP_EXT:
        return True
    if _is_external_data(rel_posix):
        return True
    return False


# Frozen files per CLAUDE.md hard-rule. The strip tool refuses to rewrite
# these by default. RC2 P7.1 (operator greenlight 2026-06-20, "frozen
# INCLUDED") promotes them INTO the main banned-set assertion - they are no
# longer skipped. This set now powers ONLY the explicit per-file regression
# lock test_frozen_files_clean_of_banned_glyphs (a banned glyph in any frozen
# file fails both that test and the tree-wide walk).
#
# (Item 156 note: ops/rc_supervisor.py is deliberately OMITTED from this
# set because it was repaired in item 156 - the drift guard NOW covers it
# so any re-introduction of smart quotes / em-dashes into rc_supervisor
# will be caught.)
_FROZEN = frozenset({
    "main.py",
    "core/log_setup.py",
    "core/moon_proxy.py",
    "lcu/lcu_client.py",
    "core/game_snapshot.py",
    "ops/rc_dev_runtime.py",
    "app/__init__.py",
    "app/_loop.py",
    "app/_health_monitor.py",
    "app/_remediation.py",
    "app/_state_authority.py",
    "app/_overlay_manager.py",
    "app/_game_lifecycle.py",
    "tools/diagnose.md",
    "tools/caveman.md",
})


# Files with pre-existing mojibake (mis-encoded em-dash sequences containing
# U+201D bytes in mojibake context). These are NOT smart-quote drift; they
# need separate mojibake repair. The strip tool flags them; this guard
# tolerates U+201D ONLY when 100% of occurrences are in mojibake context.
#
# (Item 156 note: empty as of 2026-05-23 - rc_self_monitor.py, rc_state_validator.py,
# tft_coach_engine.py, and ops/rc_supervisor.py were all repaired this run
# via tools/repair_mojibake.py extended to handle Variant B mojibake. The
# tolerance machinery is retained for forward use if new mojibake-tainted
# files are introduced before a repair pass.)
_MOJIBAKE_TOLERATED: frozenset[str] = frozenset()


def _tracked_files() -> list[Path]:
    out = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=_REPO_ROOT,
        capture_output=True,
        check=True,
    ).stdout
    return [_REPO_ROOT / p for p in out.decode("utf-8").split("\0") if p]


def _is_pure_mojibake_201d(raw: bytes) -> bool:
    """True if every U+201D byte in raw is in mojibake context."""
    total = raw.count(_RDQUO_BYTES)
    if total == 0:
        return True
    # find every U+201D byte position, check neighbours
    n_moji = 0
    i = 0
    while True:
        idx = raw.find(_RDQUO_BYTES, i)
        if idx < 0:
            break
        nxt = raw[idx + 3:idx + 6]
        prev = raw[max(0, idx - 3):idx]
        if nxt == _MOJI_NEIGHBOUR or prev == _MOJI_NEIGHBOUR:
            n_moji += 1
        i = idx + 3
    return n_moji == total


def test_no_smart_quotes_in_authored_source() -> None:
    """Walk every tracked source file and assert no banned codepoint bytes."""
    violations: list[tuple[str, int, str, int]] = []
    for p in _tracked_files():
        rel_posix = p.relative_to(_REPO_ROOT).as_posix()
        if _should_skip(p, rel_posix):
            continue
        # RC2 P7.1: frozen files are NO LONGER skipped (operator greenlight
        # 2026-06-20 "frozen INCLUDED"); the banned-set walk now covers them.
        try:
            raw = p.read_bytes()
        except OSError:
            continue
        # Decode-test: skip true binary (e.g. embedded raw bytes in some
        # font subsets in tests); the strip tool does the same.
        try:
            raw.decode("utf-8")
        except UnicodeDecodeError:
            continue
        for cp, name in _BANNED.items():
            byte_seq = _BANNED_BYTES[cp]
            n = raw.count(byte_seq)
            if not n:
                continue
            # Mojibake allowance for U+201D
            if cp == 0x201D and rel_posix in _MOJIBAKE_TOLERATED:
                if _is_pure_mojibake_201d(raw):
                    continue  # all U+201D are mojibake context; tolerated
            violations.append((rel_posix, cp, name, n))

    if violations:
        lines = [
            f"  {rel}: U+{cp:04X} ({name}) x{n}"
            for rel, cp, name, n in sorted(violations)
        ]
        msg = (
            "Smart-quote / em-dash / en-dash / NBSP / ellipsis drift detected. "
            "Run `$env:LOCALAPPDATA/Programs/Python/Python314/python.exe tools/strip_smart_quotes.py` to inspect, then `--apply` "
            "to rewrite. Violations:\n" + "\n".join(lines)
        )
        pytest.fail(msg)


def test_frozen_files_clean_of_banned_glyphs() -> None:
    """RC2 P7.1 regression lock: every tracked frozen file is free of the
    banned set (em/en-dash, smart quotes, NBSP, ellipsis). Frozen files were
    historically skipped by the tree-wide walk; the operator greenlit
    'frozen INCLUDED' (2026-06-20) so this asserts them explicitly. A miss
    here also surfaces in test_no_smart_quotes_in_authored_source now."""
    violations: list[tuple[str, int, str, int]] = []
    for rel_posix in sorted(_FROZEN):
        p = _REPO_ROOT / rel_posix
        if not p.is_file():
            continue
        raw = p.read_bytes()
        try:
            raw.decode("utf-8")
        except UnicodeDecodeError:
            continue
        for cp, name in _BANNED.items():
            n = raw.count(_BANNED_BYTES[cp])
            if n:
                violations.append((rel_posix, cp, name, n))
    assert not violations, (
        "Banned glyph(s) in frozen file(s) (operator-gated to fix):\n"
        + "\n".join(f"  {rel}: U+{cp:04X} ({name}) x{n}"
                    for rel, cp, name, n in violations)
    )


def test_strip_smart_quotes_tool_is_ascii() -> None:
    """The strip tool itself MUST be 7-bit ASCII (codepoints via chr())."""
    p = _REPO_ROOT / "tools" / "strip_smart_quotes.py"
    assert p.is_file(), f"strip tool missing at {p}"
    raw = p.read_bytes()
    non_ascii = [(i, b) for i, b in enumerate(raw) if b > 127]
    assert not non_ascii, (
        f"tools/strip_smart_quotes.py has {len(non_ascii)} non-ASCII bytes; "
        f"first at offset {non_ascii[0][0]}"
    )


def test_agent6_reports_are_ascii() -> None:
    """Weekly audit reports under agents/agent6_auditor/reports/ MUST be
    7-bit ASCII.

    These files are authored by CLOUD SCHEDULED ROUTINES that commit
    straight to main (author 'weekly-ddragon-audit@anthropic-routines'),
    so no in-session hook or PreToolUse gate ever sees them - CI is the
    only gate that can. The directory used to be blanket-exempted from
    the tree-wide banned-glyph walk on an 'immutable dated artifact'
    rationale; that exemption let three reports land carrying U+2713,
    U+2014 and U+00D7 (58 non-ASCII bytes) before the 2026-07-27 audit
    caught them by eye. The exemption is gone and this asserts the
    stricter full-ASCII bar, because the routines emit decorative
    checkmarks that the 8-codepoint banned set does not cover.

    A failure here means a routine prompt is emitting non-ASCII. Fix the
    landed file with:

        python tools/sanitize_agent6_reports.py --apply

    NOT with tools/strip_smart_quotes.py. That tool maps dashes, smart
    quotes, the ellipsis and NBSP and has no notion of U+2713, which is the
    DOMINANT glyph these routines emit (24 of 24 non-ASCII bytes on
    2026-08-04; 8 of 9 on 2026-08-25). This docstring pointed at it for
    both of those incidents, so the prescribed fix could not clear this
    guard and each one was repaired by hand instead - which is exactly why
    it kept recurring. tools/sanitize_agent6_reports.py covers the glyphs
    the routines actually produce and is pinned by
    tests/test_sanitize_agent6_reports.py.

    Then fix the routine prompt itself - the prompt lives in cloud
    scheduling config, not in this repo, so it needs an operator edit via
    /schedule. Until that happens this is a detect-and-repair loop, not
    prevention: the routines commit from a fresh clone where core.hooksPath
    is unset, so no local hook ever sees the file.
    """
    reports = _REPO_ROOT / "agents" / "agent6_auditor" / "reports"
    assert reports.is_dir(), f"tracked reports dir missing at {reports}"
    violations: list[tuple[str, int, int]] = []
    for p in sorted(reports.rglob("*")):
        if not p.is_file():
            continue
        raw = p.read_bytes()
        non_ascii = [(i, b) for i, b in enumerate(raw) if b > 127]
        if non_ascii:
            rel = p.relative_to(_REPO_ROOT).as_posix()
            violations.append((rel, len(non_ascii), non_ascii[0][0]))
    assert not violations, (
        "Non-ASCII byte(s) in agent6 audit report(s):\n"
        + "\n".join(f"  {rel}: {n} byte(s), first at offset {off}"
                    for rel, n, off in violations)
    )


def test_this_drift_guard_is_ascii() -> None:
    """This test file MUST be 7-bit ASCII."""
    raw = Path(__file__).read_bytes()
    non_ascii = [(i, b) for i, b in enumerate(raw) if b > 127]
    assert not non_ascii, (
        f"tests/test_smart_quote_hygiene.py has {len(non_ascii)} non-ASCII "
        f"bytes; first at offset {non_ascii[0][0]}"
    )
