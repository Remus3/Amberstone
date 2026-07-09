"""RC2 stage 7.3 - dead-code / unused-asset removal (safety-verified).

Guard for the 8 provably-orphan one-shot tools quarantined to
_archive/2026-06-20-rc2-p73/ during P7.3. Each was verified (cycle probe)
to have ZERO live import / test / Share-mirror / allowlist reference - only
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
docs/research/RC2_STALE_FILE_CENSUS.md.
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ARCHIVE_DIR = ROOT / "_archive" / "2026-06-20-rc2-p73"
TOOLS = ROOT / "tools"

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


def test_quarantined_present_in_archive():
    assert ARCHIVE_DIR.is_dir(), f"missing quarantine dir {ARCHIVE_DIR}"
    for name in QUARANTINED:
        assert (ARCHIVE_DIR / name).exists(), f"{name} not found in {ARCHIVE_DIR}"


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
