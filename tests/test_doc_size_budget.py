"""Guard: keep auto-loaded / read-on-demand docs inside their byte budgets.

CLAUDE.md is prepended to context every turn - an oversized CLAUDE.md burns the
window before work starts. ROADMAP.md is read-on-demand but kept lean too.
Relocate per-item ledger entries to docs/LEDGER.md and shipped roadmap entries to
docs/ROADMAP_HISTORY.md; never let them grow back into the budgeted files.
"""
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[1]
CLAUDE_MAX = 60 * 1024
ROADMAP_MAX = 80 * 1024


def _size(rel):
    return (ROOT / rel).stat().st_size


def test_claude_md_under_budget():
    n = _size("CLAUDE.md")
    assert n <= CLAUDE_MAX, (
        f"CLAUDE.md is {n} bytes (> {CLAUDE_MAX}). It is auto-loaded every turn. "
        "Append item-ledger entries to docs/LEDGER.md, not here."
    )


def test_roadmap_md_under_budget():
    n = _size("ROADMAP.md")
    assert n <= ROADMAP_MAX, (
        f"ROADMAP.md is {n} bytes (> {ROADMAP_MAX}). Relocate shipped entries to "
        "docs/ROADMAP_HISTORY.md."
    )
