"""RM-713 (a) remainder: the last two of its five paths live under a dated archive.

RM-713 (a) named five dated, no-reader artifacts. The s144 repo lane archived
three (LEDGER 2060; pinned by tests/test_rm713_dated_artifact_archive_s144p301.py
and the hold-corpus move). The s153 read-back found two still tracked in place:

- docs/_archive/run_lan_bridge.bat - launcher for the decommissioned LAN bridge
  (ADR-012). It starts a lan_bridge.py that no longer exists and sat loose at
  the archive root instead of under a dated folder. Its content dates from the
  initial commit (2026-04-26), so it goes to docs/_archive/2026-04/, beside the
  retired-bridge note archived the same way.
- tools/AUTO_OPS_VERB_EXPANSION_GATE_PROBE.md - a dated (2026-05-25) one-shot
  probe report in tools/, whose gate was explicitly PARKED (RM-33 CLOSED-STALE).
  It goes to docs/_archive/2026-05/.

Both moves are git mv renames: the bytes are unchanged, so every claim the
files make is still true of them.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

MOVED = {
    "docs/_archive/run_lan_bridge.bat": "docs/_archive/2026-04/run_lan_bridge.bat",
    "tools/AUTO_OPS_VERB_EXPANSION_GATE_PROBE.md": (
        "docs/_archive/2026-05/AUTO_OPS_VERB_EXPANSION_GATE_PROBE.md"
    ),
}

# The living plan doc that cites the probe's verdict line by path:line.
PLAN = "docs/OVERLAY_BUILD_MASTER_PLAN.md"


def _tracked() -> set[str]:
    out = subprocess.run(
        ["git", "ls-files"], cwd=REPO, capture_output=True, text=True, check=True
    ).stdout
    return set(out.splitlines())


def test_old_paths_are_gone_and_archive_paths_are_tracked():
    tracked = _tracked()
    assert len(tracked) > 1000, "git ls-files enumerated too little to trust"
    for old, new in MOVED.items():
        assert old not in tracked, f"{old} is still tracked"
        assert new in tracked, f"{new} is not tracked"


def test_no_bat_or_dated_report_sits_loose_at_the_named_old_homes():
    tracked = _tracked()
    loose_bat = sorted(
        p for p in tracked
        if p.startswith("docs/_archive/") and p.count("/") == 2 and p.endswith(".bat")
    )
    assert loose_bat == [], f"loose .bat at the archive root: {loose_bat}"
    assert not any(
        p.startswith("tools/") and "GATE_PROBE" in p for p in tracked
    ), "a dated gate-probe report is still in tools/"


def test_archived_bytes_are_ascii_and_lf():
    # Read the INDEX blob, not the working-tree file: a checkout may convert
    # a .bat to CRLF on disk (no eol attribute under docs/_archive/), which
    # says nothing about the tracked bytes.
    for new in MOVED.values():
        raw = subprocess.run(
            ["git", "show", f":{new}"], cwd=REPO, capture_output=True, check=True
        ).stdout
        assert raw, f"{new} is empty"
        assert b"\r" not in raw, f"{new} has CR bytes"
        raw.decode("ascii")


def test_archived_probe_keeps_its_deferred_verdict_on_the_cited_line():
    lines = (REPO / MOVED["tools/AUTO_OPS_VERB_EXPANSION_GATE_PROBE.md"]).read_text(
        encoding="ascii"
    ).splitlines()
    assert lines[0] == "# Auto-Ops Verb Expansion Gate Probe"
    # The plan doc cites line 7 for the verdict; a move must not shift it.
    assert lines[6] == "## Gate verdict: DEFERRED"


def test_living_plan_cites_the_archived_probe_not_the_old_path():
    text = (REPO / PLAN).read_text(encoding="utf-8")
    assert "tools/AUTO_OPS_VERB_EXPANSION_GATE_PROBE.md" not in text
    assert text.count("docs/_archive/2026-05/AUTO_OPS_VERB_EXPANSION_GATE_PROBE.md:7") == 2
