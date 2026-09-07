"""Drift guard: assert no mojibake byte signatures in tracked source files.

Background (item 154 / item 155 / item 156, 2026-05-23): two 8-byte
mojibake signatures are observed in the repo. Both are dash-class
glyphs that survived a cp1252-misdecode then UTF-8 re-encode round
trip:

    Variant A: c3 a2 e2 80 9d e2 82 ac  (orig: U+2500 box draw)
    Variant B: c3 a2 e2 82 ac e2 80 9d  (orig: U+2014 em-dash)

Both have been repaired via tools/repair_mojibake.py followed by
tools/strip_smart_quotes.py to normalize the resulting em-dashes to
ASCII ' - '.

This drift guard asserts neither signature ever reappears in any
tracked authored source file. FROZEN files (per CLAUDE.md hard-rule
list) are excluded because the repair tool refuses to rewrite them by
default - any remaining mojibake in a frozen file is operator-gated
to fix via --allow-frozen.

If this test fails on a freshly added file, run:
    $env:LOCALAPPDATA/Programs/Python/Python314/python.exe tools/repair_mojibake.py            # dry-run report (both variants)
    $env:LOCALAPPDATA/Programs/Python/Python314/python.exe tools/repair_mojibake.py --apply    # rewrite in place
    $env:LOCALAPPDATA/Programs/Python/Python314/python.exe tools/strip_smart_quotes.py --apply # follow-through to ASCII ' - '

EXCLUSIONS (parallel to the repair tool):
    - .git/, __pycache__/, _archive/, node_modules/
    - *.log / *.log.N, *.jsonl
    - binary: .pyc .pyd .db .png .jpg .jpeg .gif .webp .ico .zip .gz .exe
              .dll .lnk .woff .woff2 .ttf .bin .so .o
    - data/daemon_slayer/**/*.json (DDragon snapshots; external data)
    - data/meta_build/**/* (dated refresh artifacts; vendored third-party HTML)
    - data/meta/ddragon_champions.json (DDragon mirror; external data)
    - this test file itself + tools/repair_mojibake.py (both reference the
      signature via \\xNN byte literals so they stay 7-bit ASCII)

FROZEN files: item 156 repaired ops/rc_supervisor.py (1368 Variant A +
12 Variant B) with operator grant; it now passes this drift guard.
Other frozen files remain excluded so a stray mojibake byte there does
not trip the guard until the operator grants a repair pass.
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent

# 8-byte mojibake signatures, via \xNN byte literals to keep this file ASCII.
#   Variant A: c3 a2 e2 80 9d e2 82 ac  (orig: U+2500 box draw)
#   Variant B: c3 a2 e2 82 ac e2 80 9d  (orig: U+2014 em-dash)
_MOJIBAKE_SIG = b"\xc3\xa2\xe2\x80\x9d\xe2\x82\xac"
_MOJIBAKE_SIG_B = b"\xc3\xa2\xe2\x82\xac\xe2\x80\x9d"
_MOJIBAKE_SIGS: tuple[bytes, ...] = (_MOJIBAKE_SIG, _MOJIBAKE_SIG_B)

# Exclusions mirrored from tools/repair_mojibake.py
_SKIP_DIR_PARTS = {"_archive", "node_modules", "__pycache__", ".git"}
_SKIP_EXT = {
    ".pyc", ".pyd", ".db", ".png", ".jpg", ".jpeg", ".gif", ".webp",
    ".ico", ".zip", ".gz", ".exe", ".dll", ".lnk", ".woff", ".woff2",
    ".ttf", ".bin", ".so", ".o",
    ".jsonl",
}
_LOG_RE = re.compile(r"\.log(\.\d+)?$", re.IGNORECASE)

_TEST_FILE = Path(__file__).resolve().as_posix()


def _is_external_data(rel_posix: str) -> bool:
    if rel_posix.startswith("data/daemon_slayer/") and rel_posix.endswith(".json"):
        return True
    if rel_posix.startswith("data/meta_build/"):
        return True
    if rel_posix == "data/meta/ddragon_champions.json":
        return True
    return False


def _should_skip(path: Path, rel_posix: str) -> bool:
    abs_p = path.resolve().as_posix()
    if abs_p == _TEST_FILE:
        return True
    # The repair tool itself references the signature via \xNN literals.
    if rel_posix == "tools/repair_mojibake.py":
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


# Frozen files per CLAUDE.md hard-rule. The repair tool refuses to rewrite
# these by default; this test also excludes them from the assertion (any
# stray mojibake inside a frozen file is operator-gated to fix separately
# via --allow-frozen).
#
# (Item 156 note: ops/rc_supervisor.py is deliberately OMITTED from this
# set because it was repaired in item 156 - the drift guard NOW covers it
# so any re-introduction of mojibake into rc_supervisor will be caught.)
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


def _tracked_files() -> list[Path]:
    out = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=_REPO_ROOT,
        capture_output=True,
        check=True,
    ).stdout
    return [_REPO_ROOT / p for p in out.decode("utf-8").split("\0") if p]


def test_no_mojibake_signature_in_authored_source() -> None:
    """Walk every tracked source file and assert no mojibake signature."""
    violations: list[tuple[str, int, int]] = []  # (rel, n_a, n_b)
    for p in _tracked_files():
        rel_posix = p.relative_to(_REPO_ROOT).as_posix()
        if _should_skip(p, rel_posix):
            continue
        if rel_posix in _FROZEN:
            continue
        try:
            raw = p.read_bytes()
        except OSError:
            continue
        n_a = raw.count(_MOJIBAKE_SIG)
        n_b = raw.count(_MOJIBAKE_SIG_B)
        if n_a or n_b:
            violations.append((rel_posix, n_a, n_b))

    if violations:
        lines = [
            f"  {rel}: A={n_a} B={n_b} (A=c3a2 e2809d e282ac, "
            f"B=c3a2 e282ac e2809d)"
            for rel, n_a, n_b in sorted(violations)
        ]
        msg = (
            "Mojibake byte signature drift detected. "
            "Run `$env:LOCALAPPDATA/Programs/Python/Python314/python.exe tools/repair_mojibake.py` to inspect, then `--apply` "
            "followed by `$env:LOCALAPPDATA/Programs/Python/Python314/python.exe tools/strip_smart_quotes.py --apply` to "
            "normalize. Violations:\n" + "\n".join(lines)
        )
        pytest.fail(msg)


def test_repair_mojibake_tool_is_ascii() -> None:
    """The repair tool itself MUST be 7-bit ASCII (signature via \\xNN)."""
    p = _REPO_ROOT / "tools" / "repair_mojibake.py"
    assert p.is_file(), f"repair tool missing at {p}"
    raw = p.read_bytes()
    non_ascii = [(i, b) for i, b in enumerate(raw) if b > 127]
    assert not non_ascii, (
        f"tools/repair_mojibake.py has {len(non_ascii)} non-ASCII bytes; "
        f"first at offset {non_ascii[0][0]}"
    )


def test_this_drift_guard_is_ascii() -> None:
    """This test file MUST be 7-bit ASCII."""
    raw = Path(__file__).read_bytes()
    non_ascii = [(i, b) for i, b in enumerate(raw) if b > 127]
    assert not non_ascii, (
        f"tests/test_mojibake_hygiene.py has {len(non_ascii)} non-ASCII "
        f"bytes; first at offset {non_ascii[0][0]}"
    )
