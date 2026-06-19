"""Drift-guard for the R4 (DIRECTOR REFILL 2026-06-19) typography audit of the
three core coaching panels: team_context.css, coach_choices.css, item_build.css.

UI_SCALE_SPEC_V2 (v2.1) floor: no hardcoded font-size below --fs-xs (16px)
without a documented operator-exception carrying an inline rationale comment.

This pins, per panel:

(a) The audit-flipped selectors carry a var(--fs-*) token (no regression to a
    sub-floor hardcoded px).
(b) The documented operator-exceptions stay sub-floor with their inline
    rationale comment present (so a future maintainer cannot silently bump them
    back to floor and break a density-constrained surface).
(c) The clickable A/B choice chip (.rc-chip) keeps its var(--hit-min) target.
(d) No new non-ASCII bytes (em/en-dash, smart quotes) introduced.

SCOPE NOTE: item_build.css also houses the cross-panel .kv / #nx-wave /
.minimap-grid / .obj-* rules that style the Right Now / Next / Active-Match /
minimap surfaces (already audited under C2). Those are OUT of R4 scope and are
NOT swept here; this test only targets the Item-Build-proper selectors, so it
deliberately does NOT run a blanket sub-floor scan over item_build.css.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PANELS = ROOT / "web" / "css" / "panels"
TEAM_CONTEXT = PANELS / "team_context.css"
COACH_CHOICES = PANELS / "coach_choices.css"
ITEM_BUILD = PANELS / "item_build.css"

# find_key -> expected token. find_key is the literal string located in the CSS
# (newline-anchored where the bare selector would otherwise match a compound
# sibling, e.g. "\n.build-label {" must not match ".ib-builds-block
# .build-label {").
_TEAM_CONTEXT_FLIPPED = {
    "\n.tc-label {": "var(--fs-xs)",
    "\n.tc-status {": "var(--fs-xs)",
    "\n.tc-team-label {": "var(--fs-xs)",
    "\n.tc-slot-name {": "var(--fs-xs)",
    "\n.tc-slot-rank {": "var(--fs-xs)",
    "\n.tc-slot-sub {": "var(--fs-xs)",
    "\n.tc-slot-tail {": "var(--fs-xs)",
}

_COACH_CHOICES_FLIPPED = {
    "\n.rc-src {": "var(--fs-xs)",
}

_ITEM_BUILD_FLIPPED = {
    "\n.ds-chip {": "var(--fs-xs)",
    "\n.ds-chip em {": "var(--fs-xs)",
    "\n.build-label {": "var(--fs-xs)",
    "\n.build-value {": "var(--fs-md)",
    ".item-tile.next-up .item-cost {": "var(--fs-xs)",
    "\n.ib-builds-status {": "var(--fs-xs)",
    ".ib-builds-block .cs-build-row .cs-build-label {": "var(--fs-xs)",
}

# (find_key, expected_px, rationale_substring) - density-constrained surfaces
# that stay below the 16px floor by design.
_ITEM_BUILD_EXCEPTIONS = (
    ("\n.item-name {", 14, "operator-exception"),
    (".ib-builds-block .cs-build-row .cs-build-runes {", 10, "operator-exception"),
)


def _strip_comments(text: str) -> str:
    """Drop /* ... */ comments so a brace inside a comment (e.g. the
    `.item-tiles:has(.next-up) { padding-top: 22px }` note in the .item-cost
    rule) cannot truncate a declaration block."""
    return re.sub(r"/\*.*?\*/", "", text, flags=re.DOTALL)


def _block(text: str, find_key: str) -> str:
    """Return the declaration block (between { and the next }) for find_key."""
    i = text.find(find_key)
    assert i != -1, f"selector {find_key!r} not found"
    brace = text.find("{", i)
    end = text.find("}", brace)
    assert brace != -1 and end != -1, f"malformed rule for {find_key!r}"
    return text[brace + 1:end]


def _assert_flipped(path: Path, mapping: dict[str, str]) -> None:
    text = _strip_comments(path.read_text(encoding="utf-8"))
    for find_key, token in mapping.items():
        block = _block(text, find_key)
        m = re.search(r"font-size:\s*([^;]+);", block)
        assert m is not None, (
            f"{path.name}: {find_key!r} has no font-size declaration"
        )
        value = m.group(1).strip()
        assert token in value, (
            f"{path.name}: {find_key!r} font-size={value!r}; expected to "
            f"consume {token!r}. R4 typography audit forbids a regression to a "
            f"sub-floor hardcoded px."
        )


def test_team_context_flipped_selectors_use_tokens() -> None:
    _assert_flipped(TEAM_CONTEXT, _TEAM_CONTEXT_FLIPPED)


def test_coach_choices_flipped_selectors_use_tokens() -> None:
    _assert_flipped(COACH_CHOICES, _COACH_CHOICES_FLIPPED)


def test_item_build_flipped_selectors_use_tokens() -> None:
    _assert_flipped(ITEM_BUILD, _ITEM_BUILD_FLIPPED)


def test_item_build_operator_exceptions_hold() -> None:
    text = ITEM_BUILD.read_text(encoding="utf-8")
    for find_key, expected_px, marker in _ITEM_BUILD_EXCEPTIONS:
        block = _block(text, find_key)
        m = re.search(r"font-size:\s*(\d+)px", block)
        assert m is not None, (
            f"item_build.css: operator-exception {find_key!r} no longer has a "
            f"hardcoded px font-size; if intentionally flipped, remove it from "
            f"_ITEM_BUILD_EXCEPTIONS."
        )
        actual_px = int(m.group(1))
        assert actual_px == expected_px, (
            f"item_build.css: operator-exception {find_key!r} drifted: expected "
            f"{expected_px}px got {actual_px}px."
        )
        assert marker.lower() in block.lower(), (
            f"item_build.css: operator-exception {find_key!r} is missing its "
            f"inline rationale ({marker!r}); without it a future maintainer "
            f"bumps the value back to floor."
        )


def test_coach_choice_chip_keeps_hit_min() -> None:
    """The A/B choice chip is the only clickable surface of the three panels;
    its tap target must stay >= --hit-min (42px)."""
    block = _block(_strip_comments(COACH_CHOICES.read_text(encoding="utf-8")),
                   "\n.rc-chip {")
    assert "var(--hit-min" in block, (
        "coach_choices.css: .rc-chip lost its var(--hit-min) min-height target"
    )


def test_no_blanket_sub_floor_in_single_panel_files() -> None:
    """team_context.css + coach_choices.css are single-panel files (no
    cross-panel rules), so a blanket scan is safe: every text font-size must be
    >= 16px. item_build.css is intentionally excluded (cross-panel .kv/#nx-wave
    rules live there, out of R4 scope)."""
    for path in (TEAM_CONTEXT, COACH_CHOICES):
        text = _strip_comments(path.read_text(encoding="utf-8"))
        for m in re.finditer(r"font-size:\s*(\d+)px", text):
            px = int(m.group(1))
            assert px >= 16, (
                f"{path.name}: hardcoded sub-floor font-size {px}px found. Flip "
                f"to a var(--fs-*) token (16px floor) or, for a density-"
                f"constrained surface, add a documented operator-exception."
            )


# em/en-dash + smart-quote bytes (chr() so this file stays ASCII-clean against
# its own scan, mirroring test_design_tokens_panel_consumption.py).
_BAD = {
    chr(0x2013): "EN DASH",
    chr(0x2014): "EM DASH",
    chr(0x2018): "LEFT SINGLE QUOTE",
    chr(0x2019): "RIGHT SINGLE QUOTE",
    chr(0x201C): "LEFT DOUBLE QUOTE",
    chr(0x201D): "RIGHT DOUBLE QUOTE",
}


def test_panels_ascii_clean() -> None:
    for path in (TEAM_CONTEXT, COACH_CHOICES, ITEM_BUILD):
        text = path.read_text(encoding="utf-8")
        hits = [name for ch, name in _BAD.items() if ch in text]
        assert hits == [], f"{path.name} contains forbidden non-ASCII: {hits}"
