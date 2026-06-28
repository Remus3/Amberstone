"""phase3_setup must NOT wipe the accreted locked-decision register on re-run.

Regression for the 2026-06-28 idempotency bug: main() did an unconditional
atomic_write of RESOLVED_DECISIONS, which carries no `decisions` array, so a
re-run silently dropped every decision the audit backfills had accreted into
agents/state/resolved_decisions.json (the charter-L18 source of truth).
"""
from __future__ import annotations

from ops.phase3_setup import RESOLVED_DECISIONS, merge_resolved_decisions


def test_merge_preserves_existing_decision_register() -> None:
    existing = {
        "version": "phase3-1.1",
        "locked_at": "2026-06-28",
        "decisions": [{"id": "phase3-d001"}, {"id": "phase3-d025"}],
        "topology": {"stale": "should be refreshed from generator"},
    }
    out = merge_resolved_decisions(existing)
    # Locked register survives a re-run verbatim.
    assert [d["id"] for d in out["decisions"]] == ["phase3-d001", "phase3-d025"]
    assert out["version"] == "phase3-1.1"
    assert out["locked_at"] == "2026-06-28"
    # Static register blocks are refreshed from the generator, not the stale file.
    assert out["topology"] == RESOLVED_DECISIONS["topology"]


def test_merge_seeds_empty_register_when_file_absent() -> None:
    out = merge_resolved_decisions(None)
    assert out["decisions"] == []
    assert out["version"] == RESOLVED_DECISIONS["version"]
    assert "topology" in out


def test_merge_handles_existing_without_decisions_key() -> None:
    out = merge_resolved_decisions({"version": "phase3-1.1", "locked_at": "2026-04-22"})
    assert out["decisions"] == []
    assert out["locked_at"] == "2026-04-22"
