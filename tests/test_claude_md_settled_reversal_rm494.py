"""RM-494: every CLAUDE.md Settled line states what would reverse it.

FLEET-COMMON item 5 requires every do-not-re-litigate entry to name its
reversal condition. CLAUDE.md recorded that gap as open; this guard keeps it
closed, so a new Settled line cannot land as a fence that reads as current
forever.
"""
from __future__ import annotations

from pathlib import Path

CLAUDE_MD = Path(__file__).resolve().parent.parent / "CLAUDE.md"
HEADER = "### Settled - do not re-litigate"


def _settled_bullets() -> list[str]:
    lines = CLAUDE_MD.read_text(encoding="utf-8").splitlines()
    start = next(i for i, ln in enumerate(lines) if ln.startswith(HEADER))
    out = []
    for ln in lines[start + 1:]:
        if ln.startswith("#"):
            break
        if ln.startswith("- "):
            out.append(ln)
    return out


def test_settled_block_is_found_and_non_empty():
    # Anchor: an empty enumeration must not pass the next test vacuously.
    assert len(_settled_bullets()) >= 10


def test_every_settled_line_names_its_reversal_condition():
    missing = [b[:80] for b in _settled_bullets() if "Reverses if:" not in b]
    assert not missing, f"Settled lines without 'Reverses if:': {missing}"


def test_overlap_note_no_longer_records_the_gap_as_open():
    text = CLAUDE_MD.read_text(encoding="utf-8")
    assert "do not yet carry a reversal condition (open gap)" not in text
