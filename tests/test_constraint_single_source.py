"""Guard: constraint single-source + no drift on consolidated rules.

Hard rules live once in the auto-loaded CLAUDE.md; the per-item ledger lives in
docs/LEDGER.md (CLAUDE.md "Active priorities" is a static pointer); the headless
agent-count is single-valued. A drift test is the enforcement mechanism, not
manual pointers restated in every doc.
"""
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[1]
NL = chr(10)


def _read(rel):
    return (ROOT / rel).read_text(encoding="utf-8")


def test_frozen_files_list_present_and_canonical():
    t = _read("CLAUDE.md")
    assert "Frozen files" in t
    for anchor in ("main.py", "ops/rc_supervisor.py", "core/moon_proxy.py"):
        assert anchor in t, f"frozen-list anchor missing: {anchor}"


def test_headless_agent_count_no_drift():
    t = _read("tools/headless-upgrade.md")
    assert "100 worktree" in t, "headless-upgrade.md must state 100 worktree agents"
    for stale in ("24 worktree agents", "24 worktree subagents", "24 parallel worktree"):
        assert stale not in t, f"stale agent-count drift in headless-upgrade.md: {stale}"


def test_claude_active_priorities_is_pointer_not_ledger():
    t = _read("CLAUDE.md")
    assert "docs/LEDGER.md" in t, "CLAUDE.md must point to docs/LEDGER.md"
    assert "Per-item completion ledger relocated" in t
    assert (NL + "278. ") not in t, "item ledger entry leaked into CLAUDE.md - use docs/LEDGER.md"
    assert (NL + "LW. ") not in t, "LW ledger block leaked into CLAUDE.md"


def test_ledger_holds_relocated_items():
    # Split-home layout (2026-06: items 1-324 deep-archived): LEDGER.md keeps
    # item 325+ and the LW block; history_notes.md holds the older anchors.
    t = _read("docs/LEDGER.md")
    assert (NL + "325. ") in t and "LW. " in t
    assert len(t) > 100000
    h = _read("docs/history_notes.md")
    assert (NL + "278. ") in h and (NL + "150. ") in h
