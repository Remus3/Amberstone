"""RM-713 (a) remainder: the last two dated, no-reader paths live under docs/_archive/<yyyy-mm>/.

The s151 landing archived three of RM-713 (a)'s five paths (pinned by
tests/test_rm713_dated_artifact_archive_s144p301.py and
tests/test_rm713_hold_corpus_archive_s144p302.py). The s153 read-back left two:

* docs/_archive/run_lan_bridge.bat - the launcher of the bridge decommissioned
  2026-06-24 (ADR-012), loose at the archive root instead of a dated folder.
* tools/AUTO_OPS_VERB_EXPANSION_GATE_PROBE.md - a 2026-05-25 one-shot probe
  report (verdict DEFERRED; RM-33 CLOSED-STALE) sitting in tools/.

Neither has a code reader. The doc cites that named them follow the move.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

MOVED = {
    "docs/_archive/run_lan_bridge.bat": "docs/_archive/2026-04/run_lan_bridge.bat",
    "tools/AUTO_OPS_VERB_EXPANSION_GATE_PROBE.md": "docs/_archive/2026-05/AUTO_OPS_VERB_EXPANSION_GATE_PROBE.md",
}

# Living docs that cited the old tools/ path; they must cite the archive path.
CITERS = ("docs/OVERLAY_BUILD_MASTER_PLAN.md", "docs/LIVE_GAME_GATED_SYNC.md")


def _tracked() -> set[str]:
    out = subprocess.run(
        ["git", "ls-files"], cwd=REPO, capture_output=True, text=True, check=True
    ).stdout
    return set(out.splitlines())


def test_old_paths_are_gone_and_archive_paths_are_tracked():
    tracked = _tracked()
    assert tracked, "git ls-files enumerated nothing"
    for old, new in MOVED.items():
        assert old not in tracked, f"{old} is still tracked"
        assert new in tracked, f"{new} is not tracked"


def test_archived_files_are_ascii_and_non_empty():
    for new in MOVED.values():
        raw = (REPO / new).read_bytes()
        assert raw, f"{new} is empty"
        raw.decode("ascii")


def test_probe_report_keeps_its_deferred_verdict():
    text = (REPO / MOVED["tools/AUTO_OPS_VERB_EXPANSION_GATE_PROBE.md"]).read_text(encoding="ascii")
    assert text.startswith("# Auto-Ops Verb Expansion Gate Probe")
    assert "## Gate verdict: DEFERRED" in text


def test_living_doc_citers_point_at_the_archive_path():
    old = "tools/AUTO_OPS_VERB_EXPANSION_GATE_PROBE.md"
    new = MOVED[old]
    for rel in CITERS:
        text = (REPO / rel).read_text(encoding="utf-8")
        assert old not in text, f"{rel} still cites {old}"
        assert new in text, f"{rel} does not cite {new}"
