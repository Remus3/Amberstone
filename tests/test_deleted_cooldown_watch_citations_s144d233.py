"""S144-D-233 - nothing cites the deleted cooldown_watch modules as live.

The Riot-compliance removal (538c61e4b, 2026-08-11; LEDGER 1238) deleted
``agents/daemon_slayer/cooldown_watch.py``, ``dashboard/routes_cooldown_watch.py``
and their two test files, because tracking enemy ability cooldowns is a
banned surface. 34 docstring and comment lines in 19 files kept describing them
as the live sibling a module "mirrors" (``Mirrors routes_cooldown_watch cache
discipline``, ``Mirrors cooldown_watch._load_abilities exactly``), so a reader
following the cite found nothing and a future author had a named template to
restore the banned module from. S144-D-230..232 repointed every such cite at a
live sibling; this guard keeps it that way.

Scope: tracked ``*.py`` under ``agents/``, ``core/``, ``dashboard/`` and
``tests/`` (subdirectory walks via ``git ls-files``, not a repo-root walk).
The identifier spelling ``cooldown_watch`` is what names a module, route or
test file; the hyphenated ``cooldown-watch`` card name in DOM placement prose
is a different class and is out of scope here. Every remaining hit must be a
pinned HISTORICAL line (it says the module was deleted or old), and every
pinned line must still be found exactly once, so the allow-list cannot go
stale silently.
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
THIS = Path(__file__).resolve().relative_to(REPO).as_posix()

SCAN_DIRS = ("agents", "core", "dashboard", "tests")
PATTERN = re.compile(r"cooldown_watch")

# The deleted files themselves: their return would restore a banned surface.
DELETED = (
    "agents/daemon_slayer/cooldown_watch.py",
    "agents/daemon_slayer/tests/test_cooldown_watch_2026_05_30.py",
    "dashboard/routes_cooldown_watch.py",
    "tests/test_routes_cooldown_watch.py",
    "tests/test_cooldown_watch_panel_dom.py",
)

# (path, substring) of every line allowed to keep the identifier. Each one
# records the deletion or the removed join in the past tense.
ALLOWED = (
    ("agents/daemon_slayer/tests/test_cc_conditional_forward_marker.py",
     "cooldown_watch.py was DELETED"),
    ("agents/daemon_slayer/tests/test_per_spell_cc_registry_integrity_s144d225.py",
     "the ``cooldown_watch`` reader named in older"),
    ("core/laning_scenario_precompute.py",
     "the old compute_cooldown_watch join"),
    ("tests/test_cc_threat_cell_riot_compliance.py",
     "``agents.daemon_slayer.cooldown_watch``:"),
    ("tests/test_lane_a_v4_verdicts.py",
     "not the deleted cooldown_watch join"),
    ("tests/test_status_helper_rc2.py",
     "the since-deleted cooldown_watch) has a pinned contract."),
)


def _tracked_py() -> list[str]:
    out = subprocess.run(
        ["git", "ls-files", "-z", "--", *[f"{d}/*.py" for d in SCAN_DIRS]],
        cwd=REPO, capture_output=True, check=True,
    ).stdout.decode("utf-8")
    return [p for p in out.split("\0") if p and p != THIS]


def _hits() -> list[tuple[str, int, str]]:
    found = []
    for rel in _tracked_py():
        path = REPO / rel
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        for n, line in enumerate(text.splitlines(), 1):
            if PATTERN.search(line):
                found.append((rel, n, line))
    return found


def test_scan_universe_is_not_empty():
    files = _tracked_py()
    # Anchor: an empty enumeration (wrong cwd, git missing) must not pass.
    assert len(files) > 1000, len(files)
    assert "agents/daemon_slayer/combo.py" in files
    assert "dashboard/routes_cc_pairing.py" in files


def test_deleted_cooldown_watch_files_stay_deleted():
    present = [p for p in DELETED if (REPO / p).exists()]
    assert present == [], f"banned cooldown-watch surface restored: {present}"


def test_no_route_dispatches_cooldown_watch():
    dispatch = (REPO / "dashboard" / "_dispatch.py").read_text(encoding="utf-8")
    assert "cooldown-watch" not in dispatch
    assert "cooldown_watch" not in dispatch


def test_every_cooldown_watch_citation_is_a_pinned_historical_line():
    stray = [
        f"{rel}:{n}: {line.strip()}"
        for rel, n, line in _hits()
        if not any(rel == p and s in line for p, s in ALLOWED)
    ]
    assert stray == [], (
        "a deleted cooldown_watch module is cited as live; repoint it at a "
        "live sibling (routes_cc_conditional_pressure for the route cache "
        "discipline):\n" + "\n".join(stray)
    )


def test_every_allowed_line_is_still_found_exactly_once():
    hits = _hits()
    for path, sub in ALLOWED:
        n = sum(1 for rel, _, line in hits if rel == path and sub in line)
        assert n == 1, (path, sub, n)
