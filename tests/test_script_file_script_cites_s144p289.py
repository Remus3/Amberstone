"""S144-P-289 - a tracked shell / PowerShell / Node script never names a removed repo script.

Sibling of test_dangling_py_cite_ratchet_s144p273 (production .py prose), the doc guards p284 / p285 and the test-prose
guard p286. Those four read prose in files of one language; none reads a script written in another. A ``.ps1`` that
runs ``python tools/foo.py`` is not prose: when ``foo.py`` is removed the script fails at run time, so a stale cite
here is a live break, not just a misleading comment.

Measured 2026-11-06 over every tracked ``.ps1`` / ``.bat`` / ``.cmd`` / ``.sh`` / ``.js`` / ``.mjs`` file outside
``web/`` (its ``lib/x.js`` cites are relative to ``web/js``, not repo-rooted), ``tests/``, ``docs/_archive/``, the
vendored fleet kit and the PKG-owned ``rc-shell/`` and ``ops/launcher/``: 37 repo-rooted cites in 18 ``.ps1`` files
and 36 in 11 ``.js`` files, ZERO of an untracked path, and no ``.bat`` / ``.sh`` / ``.mjs`` cite at all. So the guard
ships at zero with nothing to fix and nothing to allow.

Known blind spot, measured the same day: a backslash-spelled cite (``ops\\loop\\x.ps1``) is not matched; there are none
in the scanned files today. A path assembled at run time (``Join-Path $root "tools"``) is invisible by construction.

The rule is the p273 rule (``scan_source``): an untracked cite needs a removed / retired / quarantined word within three
lines, else it fails. ``test_scanner_is_live`` proves the file selection and the scan each report a bare cite, since an
empty scan would pass for any reason.
"""
from __future__ import annotations

from tests.test_dangling_py_cite_ratchet_s144p273 import _tracked, scan_source
from tests._repo_walk import REPO_ROOT

_SUFFIXES = (".ps1", ".bat", ".cmd", ".sh", ".js", ".mjs")
_OUT_OF_SCOPE_PREFIXES = ("web/", "tests/", "docs/_archive/", "ops/fleet_kit/", "rc-shell/", "ops/launcher/")


def _scripts(tracked: frozenset[str]) -> list[str]:
    return sorted(
        rel for rel in tracked if rel.endswith(_SUFFIXES) and not rel.startswith(_OUT_OF_SCOPE_PREFIXES)
    )


def _tree_hits() -> set[tuple[str, str]]:
    tracked = _tracked()
    found: set[tuple[str, str]] = set()
    for rel in _scripts(tracked):
        try:
            src = (REPO_ROOT / rel).read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        found.update((rel, cited) for _line, cited in scan_source(src, tracked))
    return found


def test_no_script_names_a_missing_repo_script():
    hits = sorted(_tree_hits())
    assert not hits, (
        "a tracked script cites a repo script that is not tracked (restore it, drop the cite, or mark the cite "
        f"removed / retired within 3 lines): {hits}"
    )


def test_scanner_is_live():
    tracked = frozenset(
        {"ops/a.ps1", "tools/real.py", "web/js/x.js", "tests/t.sh", "rc-shell/y.js", "docs/_archive/z.bat", "ops/b.txt"}
    )
    picked = _scripts(tracked)
    assert picked == ["ops/a.ps1"]
    assert _scripts(frozenset({"tools/y.mjs", "ops/z.cmd", "ops/w.sh", "tools/x.py"})) == [
        "ops/w.sh", "ops/z.cmd", "tools/y.mjs",
    ]
    assert scan_source("& python tools/absent.py --go\n", tracked) == [(1, "tools/absent.py")]
    assert scan_source("& python tools/absent.py --go # it was removed\n", tracked) == []
    assert scan_source("& python tools/real.py --go\n", tracked) == []


def test_real_scripts_carry_cites_so_the_scan_is_not_empty():
    """The measured population: if no tracked script cites any repo path at all, the zero above proves nothing."""
    from tests.test_dangling_py_cite_ratchet_s144p273 import _CITE_RE

    tracked = _tracked()
    cites = 0
    for rel in _scripts(tracked):
        try:
            cites += len(_CITE_RE.findall((REPO_ROOT / rel).read_text(encoding="utf-8")))
        except (UnicodeDecodeError, OSError):
            continue
    assert cites >= 20, cites
