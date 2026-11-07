"""S144-P-273 - a production .py never cites a repo module that no longer exists as if it were live.

A docstring or comment naming ``tools/foo.py`` reads as a pointer to working code. When ``foo.py`` was quarantined or
deleted, the cite stays and sends the next reader hunting (``agents/daemon_slayer/_item_ability_haste.py`` records the
cost: an earlier docstring cited a generator that never existed). Measured 2026-11-06 over the tracked production tree
(tests and the vendored fleet kit excluded): 19 cites of an untracked ``.py`` path in 12 files. Twelve say so in plain
words nearby (quarantined, removed, retired, never existed, ...); that is a history note, not a dangling pointer, and
the guard accepts it. Three were bare and are fixed with this guard (tools/champion_loadout_validate_meta.py,
tools/hotfix_kaisa_aram_ashe_sr_item263.py, tools/champion_loadout_align.py). The rest are the named exceptions below.

The rule: every cite of an untracked ``<top-dir>/<path>.py`` needs a history word within three lines either side, or an
entry in ``_ALLOWED`` (file, path) with the reason. ``_ALLOWED`` only shrinks: an entry that no longer matches a cite
fails ``test_allowlist_is_exact``. ``test_scanner_is_live`` proves the scan reports a bare cite, accepts a marked one
and ignores a tracked path, since an empty scan would pass for any reason.
"""
from __future__ import annotations

import re
import subprocess

from tests._repo_walk import REPO_ROOT, relative_posix, repo_files

_TOP_DIRS = (
    "core|tools|ops|app|lcu|dashboard|coaches|modes|agents|scripts|vision_server|coach_integration|lib|tft"
)
_CITE_RE = re.compile(rf"(?<![\w./-])((?:{_TOP_DIRS})/[A-Za-z0-9_./-]*[A-Za-z0-9_]\.py)(?![\w])")
_HISTORY_RE = re.compile(
    r"quarantin|remov|delet|retired|never existed|no longer|\bgone\b|was dropped|deprecat|sibling|history|"
    r"superseded|replaced|\bold\b|former|earlier|legacy",
    re.IGNORECASE,
)
_WINDOW = 3
_OUT_OF_SCOPE_PREFIXES = ("tests/", "ops/fleet_kit/", "docs/")

# (file, cited path) -> why it is not a dangling pointer. Only shrinks.
_ALLOWED = {
    # DS package, lane/ds territory (a docstring edit there is a FILING): mirrors the removed summoner-cooldown module.
    ("agents/daemon_slayer/ability_dps.py", "core/summoner_cooldowns.py"),
    # Illustrative placeholder paths inside the citation checker's own docs / the impact selector's examples.
    ("tools/ci_impact_selector.py", "core/x.py"),
    ("tools/ci_impact_selector.py", "tools/y.py"),
    ("tools/citation_audit.py", "tools/x.py"),
    ("tools/citation_audit.py", "core/NOSUCHFILE_zzz.py"),
    # A gitignored runtime artefact the tool writes at run time, not a tracked module.
    ("tools/pseudo_screen_overlay.py", "ops/runtime/ui_recon/recon.py"),
}


def scan_source(src: str, tracked: frozenset[str]) -> list[tuple[int, str]]:
    """(line, path) of every untracked repo .py cite with no history word within the window."""
    lines = src.split("\n")
    hits: list[tuple[int, str]] = []
    for i, line in enumerate(lines):
        for m in _CITE_RE.finditer(line):
            path = m.group(1)
            if path in tracked:
                continue
            window = "\n".join(lines[max(0, i - _WINDOW): i + _WINDOW + 1])
            if not _HISTORY_RE.search(window):
                hits.append((i + 1, path))
    return hits


def _tracked() -> frozenset[str]:
    out = subprocess.run(
        ["git", "ls-files"], cwd=REPO_ROOT, capture_output=True, text=True, check=True
    ).stdout
    return frozenset(line for line in out.split("\n") if line)


def _tree_hits() -> set[tuple[str, str]]:
    tracked = _tracked()
    found: set[tuple[str, str]] = set()
    for path in repo_files(patterns=("*.py",)):
        rel = relative_posix(path)
        if rel.startswith(_OUT_OF_SCOPE_PREFIXES) or rel not in tracked:
            continue
        try:
            src = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for _line, cited in scan_source(src, tracked):
            found.add((rel, cited))
    return found


def test_no_bare_cite_of_a_missing_module():
    new = sorted(_tree_hits() - _ALLOWED)
    assert not new, (
        "cite of a repo .py that is not tracked and carries no history word within "
        f"{_WINDOW} lines (say it was quarantined / removed, or drop the cite): {new}"
    )


def test_allowlist_is_exact():
    stale = sorted(_ALLOWED - _tree_hits())
    assert not stale, f"_ALLOWED entries that no longer match a bare cite - drop them: {stale}"


def test_scanner_is_live():
    tracked = frozenset({"tools/real.py"})
    assert scan_source("see tools/absent.py for the merge\n", tracked) == [(1, "tools/absent.py")]
    assert scan_source("see tools/absent.py\n# it was quarantined in P7.3\n", tracked) == []
    assert scan_source("see tools/real.py\n", tracked) == []
    far = "see tools/absent.py\n" + "x\n" * 4 + "removed\n"
    assert scan_source(far, tracked) == [(1, "tools/absent.py")]
    assert scan_source("see core/a/b/absent_two.py now\n", tracked) == [(1, "core/a/b/absent_two.py")]
