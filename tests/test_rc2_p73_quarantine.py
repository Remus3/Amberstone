"""RC2 stage 7.3 - dead-code / unused-asset removal (safety-verified).

Guard for the 8 provably-orphan one-shot tools quarantined to
_archive/2026-06-20-rc2-p73/ during P7.3. Each was verified (cycle probe)
to have ZERO live import / test / allowlist reference - only
dated-doc + docstring-lineage mentions. This locks the quarantine: the files
must stay OUT of tools/ and IN the archive, the reusable siblings must remain,
and nothing in live source may import the quarantined module names.

The bulk of the 7.2 census "archive-candidate" set was RETAINED (not moved)
because the safety-verification pass found it coupled to live regression tests
(tests/test_loadout_*, test_thin_aram_*, test_zaahen_*, test_bridge_dispatch_
enable_lanes, test_probe_101qq_script), living how-to docs
(docs/_archive/CAPTURE_101QQ_INSTRUCTIONS.md), the runtime allowlist
(dashboard/routes_static._AGENT_ALLOWED), immutable agent history, or the
P0/P1 audit baseline (hold til Phase 7 closes). See
docs/_archive/2026-07-28-research-consolidation/RC2_STALE_FILE_CENSUS.md.
"""
from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
ARCHIVE_DIR = ROOT / "_archive" / "2026-06-20-rc2-p73"
TOOLS = ROOT / "tools"

# The scratch-cleanup commit that removed the quarantine directory from the
# tree (2026-07-07). The archive was TRACKED until then - see
# test_quarantined_present_in_archive for why that correction matters.
ARCHIVE_REMOVED_AT = "f08ade78"

# The 7 one-shot scripts quarantined this stage (already-applied hotfixes,
# migrations, and loadout one-shots; refs only in dated docs + docstrings).
# NOTE: caveman_default.py was REMOVED from this list 2026-06-27 - it was revived
# (R29) as the live SessionStart output-dialect hook (tools/caveman_default.py,
# wired in .claude/settings.json), so it is intentionally present under tools/ and
# must NOT be quarantined.
QUARANTINED = [
    "hotfix_sr_adc_loadouts_item167.py",
    "hotfix_arena_mage_mislabel_item273.py",
    "migrate_abilities_units_2026_05_30.py",
    "champion_loadout_handcurate_merge.py",
    "champion_loadout_handcurate.py",
    "migrate_carry_summoners_flash_barrier.py",
    "champion_loadout_backfill_item208_carry.py",
]

# Reusable siblings that MUST stay live (CLAUDE.md-blessed drift checkers,
# loadout validators, the active align/invariants successors).
KEEP_TOOLS = [
    "ds_cond_pair_prefilter.py",
    "strip_em_dashes.py",
    "validate_loadouts.py",
    "champion_loadout_invariants.py",
    "champion_loadout_validate_meta.py",
    "champion_loadout_align.py",
]

# Live source trees to scan for a forbidden re-import of a quarantined module.
LIVE_SRC_DIRS = [
    "core", "dashboard", "tools", "agents", "coaches", "lib",
    "modes", "vision_server", "scripts", "game_reader",
]


def test_quarantined_gone_from_tools():
    for name in QUARANTINED:
        assert not (TOOLS / name).exists(), f"{name} still under tools/ - must be quarantined"


def _git(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=str(ROOT),
                          capture_output=True, text=True, timeout=60)


@pytest.mark.skipif(shutil.which("git") is None, reason="git not on PATH")
def test_quarantined_present_in_archive():
    """The quarantine is proven from git history, not from the local disk.

    RM-119 class B4, 2026-08-06. This used to read
    `if not ARCHIVE_DIR.is_dir(): pytest.skip(...)` on the premise that
    `_archive/` is gitignored machine-local state. That premise was wrong in
    the way that matters: `_archive/2026-06-20-rc2-p73/` WAS tracked, and it
    was removed at f08ade78 on 2026-07-07 - so the directory is not absent
    pending a local copy, it is gone from every checkout, and this assertion
    had stopped running everywhere rather than only on CI.

    Found by the historical-trackedness rule added to
    tests/test_skip_condition_hygiene.py in the same commit, which is the
    argument for that rule: this site had been hand-classified as legitimate
    machine-local state twice, and git history disagreed.

    The quarantine claim is still checkable, just not against the filesystem:
    each file must be present at the removal commit's parent and absent from
    HEAD. Both halves can fail, and `test_quarantined_gone_from_tools` plus
    `test_no_live_import_of_quarantined` continue to carry the live contract.
    """
    missing_from_history = [
        name for name in QUARANTINED
        if _git("cat-file", "-e",
                f"{ARCHIVE_REMOVED_AT}^:_archive/2026-06-20-rc2-p73/{name}"
                ).returncode != 0
    ]
    assert not missing_from_history, (
        f"these were never quarantined to {ARCHIVE_DIR} at "
        f"{ARCHIVE_REMOVED_AT}^, so the P7.3 record is wrong: "
        f"{missing_from_history}"
    )
    still_tracked = [
        name for name in QUARANTINED
        if _git("ls-files", "--error-unmatch",
                f"_archive/2026-06-20-rc2-p73/{name}").returncode == 0
    ]
    assert not still_tracked, (
        f"the quarantine archive is tracked again at HEAD: {still_tracked} - "
        "re-point this guard at the live directory if that was intended"
    )


def test_reusable_siblings_retained():
    for name in KEEP_TOOLS:
        assert (TOOLS / name).exists(), f"reusable tool {name} unexpectedly missing from tools/"


def test_no_live_import_of_quarantined():
    """No live .py may import a quarantined module name (fail-loud on re-add)."""
    stems = [name[:-3] for name in QUARANTINED]
    patterns = [
        re.compile(rf"(?:^|\b)import\s+{re.escape(s)}\b") for s in stems
    ] + [
        re.compile(rf"from\s+(?:tools\.)?{re.escape(s)}\s+import\b") for s in stems
    ] + [
        re.compile(rf"\btools\.{re.escape(s)}\b") for s in stems
    ]
    offenders = []
    for d in LIVE_SRC_DIRS:
        base = ROOT / d
        if not base.is_dir():
            continue
        for py in base.rglob("*.py"):
            if "_archive" in py.parts:
                continue
            try:
                text = py.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            for pat in patterns:
                if pat.search(text):
                    offenders.append(f"{py.relative_to(ROOT)} :: {pat.pattern}")
    assert not offenders, "live import of quarantined module(s): " + "; ".join(offenders)
