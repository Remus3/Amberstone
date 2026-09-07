"""
tests/test_dark_values_ratchet_oq6.py

OQ6 (QA48, operator-queue 2026-07-01) - the LOCK half of the dark-values
grep-and-lock audit (docs/DARK_VALUES_AUDIT_2026-07-01.md).

Mechanism: a RATCHET. Every web/css file's count of dark/saturated hex
literals (6- or 3-digit hex starting 0/1/2; rgba(0,0,0,x) shadows are out
of scope and unmatched by the pattern) is pinned at its audited ceiling.
A new hardcoded dark literal anywhere fails CI; re-skinning an audited
offender to a token LOWERS the pin (update the map downward in the same
change - never upward without an operator-approved audit-doc row).

The 94 RESKIN-CANDIDATE rows in the audit doc are each a VISIBLE change
(old fintech/tailwind palette -> Hextech tokens) and stay operator-gated
FUTURE; the pins hold the line meanwhile.
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CSS_DIR = ROOT / "web" / "css"

_DARK = re.compile(r"#[0-2][0-9a-fA-F]{5}\b|#[0-2][0-9a-fA-F]{2}\b")

# Audited ceilings (2026-07-01, after the coach_choices.css exact-lock).
# Keys are posix paths relative to the repo root.
PINS = {
    "web/css/overlay.css": 5,
    "web/css/panels/active_match.css": 3,
    "web/css/panels/base.css": 7,
    "web/css/panels/build_module.css": 1,
    "web/css/panels/build_order.css": 1,
    "web/css/panels/champ_benchmarks.css": 4,
    # QA 2026-07-03 slice A: 52 -> 47 (ghost bans / mood / YOUR RECORD /
    # ally-mirror CSS blocks removed took their dark literals with them).
    # LEDGER 824: 47 -> 44 (the .csv-arch* archetype-picker CSS was removed
    # and took its dark literals - #a78bfa / #4c3a82 / #1a1230 / ... - with it).
    # LEDGER 863: 44 -> 42 (item-1 Phase 5 removed the in-panel push-control
    # CSS - the [PUSH] button + .csv-builds-push-* checkboxes - and took its
    # dark literals with it; the pin was not lowered in that change).
    "web/css/panels/champ_select_view.css": 42,
    "web/css/panels/coach_choices.css": 2,
    "web/css/panels/coach_decisions.css": 1,
    "web/css/panels/ds_statcheck.css": 0,
    "web/css/panels/duration_winrate.css": 4,
    "web/css/panels/header.css": 5,
    "web/css/panels/home.css": 2,
    "web/css/panels/op_score.css": 8,
    "web/css/panels/perf_curve.css": 6,
    "web/css/panels/pgr_winprob.css": 1,
    "web/css/panels/primitives.css": 1,
    "web/css/panels/right_now.css": 3,
    "web/css/panels/spike_curve.css": 1,
    "web/css/panels/ward_heat.css": 1,
    "web/css/tokens.css": 1,
    # LEDGER (2026-07-23 headless): themes.css is the 6-theme OKLCH swap
    # SOURCE layer (commit cc1df8b5) - the 36 dark literals ARE the per-theme
    # canvas/surface/accent ramps (the palette must live somewhere, same as
    # tokens.css:40). JUSTIFIED audit-doc section added; the ratchet still
    # blocks any 37th stray literal.
    "web/css/themes.css": 36,
}


def _count(p: Path) -> int:
    return len(_DARK.findall(p.read_text(encoding="utf-8", errors="replace")))


def test_no_file_exceeds_its_dark_literal_ceiling():
    over = []
    for p in sorted(CSS_DIR.rglob("*.css")):
        rel = p.relative_to(ROOT).as_posix()
        n = _count(p)
        ceiling = PINS.get(rel, 0)
        if n > ceiling:
            over.append(f"{rel}: {n} > ceiling {ceiling}")
    assert not over, (
        "new hardcoded dark color literal(s) - use the token layers "
        "(base.css --canvas/--surface-*, tokens.css --prim-*) instead, or "
        "add an operator-approved audit-doc row: " + "; ".join(over)
    )


def test_pins_not_stale_high():
    """A pin more than a whole file above reality means someone re-skinned
    without lowering the ceiling - tighten it so the ratchet keeps teeth."""
    stale = []
    for rel, ceiling in PINS.items():
        p = ROOT / rel
        if not p.is_file():
            stale.append(f"{rel}: pinned file missing")
            continue
        n = _count(p)
        if n < ceiling:
            stale.append(f"{rel}: count {n} < pin {ceiling} - lower the pin")
    assert not stale, "; ".join(stale)


def test_audit_doc_exists():
    doc = ROOT / "docs" / "DARK_VALUES_AUDIT_2026-07-01.md"
    assert doc.is_file(), "audit artifact missing"
    text = doc.read_text(encoding="utf-8")
    assert "EXACT-LOCK" in text and "RESKIN-CANDIDATE" in text
    assert not any(ord(c) > 0x7F for c in text), "audit doc must be ASCII"
