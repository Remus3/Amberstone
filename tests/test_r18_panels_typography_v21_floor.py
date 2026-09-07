"""Drift-guard for the R18 (DIRECTOR REFILL 2026-06-22) typography audit of four
un-audited panels: build_order.css, augment_reco.css, the archetype-nudge-chip
block (housed in map_state.css), and the map_state.js canvas labels.

UI_SCALE_SPEC_V2 (v2.1) floor: no hardcoded font-size below --fs-xs (16px)
without a documented operator-exception carrying an inline rationale comment.

This pins, per panel:

(a) The audit-flipped selectors carry a var(--fs-*) token (no regression to a
    sub-floor hardcoded px).
(b) The documented operator-exceptions stay sub-floor with their inline
    rationale comment present (so a future maintainer cannot silently bump them
    back to floor and break a density-constrained surface).
(c) The clickable build-order push button keeps its var(--hit-min) target.
(d) No new non-ASCII bytes (em/en-dash, smart quotes) introduced.

SCOPE NOTE: map_state.css is a shared grab-bag that houses header pills
(augments/ds/trigger), the archetype-nudge-chip, the panel chrome, the STATS
view, the GAME SENSE block, the WHAT-WENT block, and the staleness pill - the
map-state PANEL itself styles its DOM via shared/global classes. Per
UI_SCALE_SPEC_V2 ("each page audit sweeps its own panels only"), this test does
NOT run a blanket sub-floor scan over map_state.css; it pins only the
archetype-nudge-chip block (already floor-clean at 17/19px) + the map_state.js
canvas-label operator-exceptions. The archetype-nudge-chip X dismiss button is a
density-constrained header-inline control (a 42px hit target would break the
header row); it is documented as a known exception in the R18 findings, not
forced here.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PANELS = ROOT / "web" / "css" / "panels"
BUILD_ORDER = PANELS / "build_order.css"
AUGMENT_RECO = PANELS / "augment_reco.css"
MAP_STATE_CSS = PANELS / "map_state.css"
MAP_STATE_JS = ROOT / "web" / "js" / "panels" / "map_state.js"

# find_key -> expected token. find_key is the literal string located in the CSS
# (newline-anchored where a bare selector would otherwise match a compound
# sibling).
_BUILD_ORDER_FLIPPED = {
    "\n.bo-tag {": "var(--fs-xs)",
    "\n.bo-chain {": "var(--fs-xs)",
    "\n.bo-ctx {": "var(--fs-xs)",
    "\n.bo-msg {": "var(--fs-xs)",
    "\n.bo-num {": "var(--fs-xs)",
    "\n.bo-safe,": "var(--fs-xs)",
    "\n.bo-expander {": "var(--fs-xs)",
}

_AUGMENT_RECO_FLIPPED = {
    ".ar-top-cue {": "var(--fs-xs)",
    ".ar-top-conf {": "var(--fs-xs)",
    ".ar-row {": "var(--fs-xs)",
    ".ar-rank {": "var(--fs-xs)",
    ".ar-score {": "var(--fs-xs)",
    ".ar-wr {": "var(--fs-xs)",
    ".ar-syn {": "var(--fs-xs)",
    ".ar-meta {": "var(--fs-xs)",
}

# (find_key, expected_px, rationale_substring) - density-constrained surfaces
# that stay below the 16px floor by design.
_BUILD_ORDER_EXCEPTIONS = (
    ("\n.bo-name {", 15, "operator-exception"),
    ("\n.bo-delta {", 15, "operator-exception"),
)


def _strip_comments(text: str) -> str:
    """Drop /* ... */ comments so a brace inside a comment cannot truncate a
    declaration block."""
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
            f"consume {token!r}. R18 typography audit forbids a regression to a "
            f"sub-floor hardcoded px."
        )


def test_build_order_flipped_selectors_use_tokens() -> None:
    _assert_flipped(BUILD_ORDER, _BUILD_ORDER_FLIPPED)


def test_augment_reco_flipped_selectors_use_tokens() -> None:
    _assert_flipped(AUGMENT_RECO, _AUGMENT_RECO_FLIPPED)


def test_build_order_operator_exceptions_hold() -> None:
    text = BUILD_ORDER.read_text(encoding="utf-8")
    for find_key, expected_px, marker in _BUILD_ORDER_EXCEPTIONS:
        block = _block(text, find_key)
        m = re.search(r"font-size:\s*(\d+)px", block)
        assert m is not None, (
            f"build_order.css: operator-exception {find_key!r} no longer has a "
            f"hardcoded px font-size; if intentionally flipped, remove it from "
            f"_BUILD_ORDER_EXCEPTIONS."
        )
        actual_px = int(m.group(1))
        assert actual_px == expected_px, (
            f"build_order.css: operator-exception {find_key!r} drifted: expected "
            f"{expected_px}px got {actual_px}px."
        )
        assert marker.lower() in block.lower(), (
            f"build_order.css: operator-exception {find_key!r} is missing its "
            f"inline rationale ({marker!r}); without it a future maintainer "
            f"bumps the value back to floor."
        )


def test_augment_reco_no_blanket_sub_floor() -> None:
    """augment_reco.css is a single-panel file (all .ib-aug-reco-* / .ar-*), so a
    blanket scan is safe: every text font-size must be >= 16px (above-floor
    literals like the 23px .ar-top-name headline are allowed; only sub-floor is a
    violation)."""
    text = _strip_comments(AUGMENT_RECO.read_text(encoding="utf-8"))
    for m in re.finditer(r"font-size:\s*(\d+)px", text):
        px = int(m.group(1))
        assert px >= 16, (
            f"augment_reco.css: hardcoded sub-floor font-size {px}px found. Flip "
            f"to a var(--fs-*) token (16px floor) or, for a density-constrained "
            f"surface, add a documented operator-exception."
        )


def test_archetype_nudge_chip_block_stays_removed() -> None:
    """(2026-07-04) The archetype-nudge-chip surface was retired with header
    row 2; its map_state.css block was deleted. Absence guard (4e5b2575
    removed-surface precedent) so a merge cannot resurrect the orphaned
    rules - a resurrected chip needs a new render surface + a fresh audit."""
    text = _strip_comments(MAP_STATE_CSS.read_text(encoding="utf-8"))
    for find_key in (
        "\n.archetype-nudge-chip {",
        "\n.archetype-nudge-chip-x {",
    ):
        assert find_key not in text, (
            f"map_state.css: retired block {find_key!r} resurrected."
        )


def test_build_order_push_button_keeps_hit_min() -> None:
    """The DS-vs-enemy-comp save+push button is the clickable surface of
    build_order.css; its tap target must stay >= --hit-min (42px)."""
    block = _block(_strip_comments(BUILD_ORDER.read_text(encoding="utf-8")),
                   "\n.bo-pushbtn {")
    assert "var(--hit-min" in block, (
        "build_order.css: .bo-pushbtn lost its var(--hit-min) min-height target"
    )


def test_map_state_canvas_labels_documented_exception() -> None:
    """The map_state.js minimap canvas labels (objective D/B/H markers + the YOU
    badge) are sub-floor (11px / 13px) by necessity: they are 2D-canvas spatial
    annotations sized to fit dot glyphs on a ~312px-rendered minimap, NOT DOM
    body text, so they cannot consume a CSS var(--fs-*) token. Pin that each
    carries an inline operator-exception rationale so a maintainer cannot bump
    them blind."""
    text = MAP_STATE_JS.read_text(encoding="utf-8")
    for needle in ('ctx.font = "bold 11px', 'ctx.font = "bold 13px'):
        assert needle in text, f"map_state.js: canvas font {needle!r} not found"
    assert "operator-exception" in text.lower(), (
        "map_state.js: the canvas sub-floor labels are missing their inline "
        "operator-exception rationale."
    )


# em/en-dash + smart-quote bytes (chr() so this file stays ASCII-clean against
# its own scan, mirroring test_core_panels_typography_v21_floor.py).
_BAD = {
    chr(0x2013): "EN DASH",
    chr(0x2014): "EM DASH",
    chr(0x2018): "LEFT SINGLE QUOTE",
    chr(0x2019): "RIGHT SINGLE QUOTE",
    chr(0x201C): "LEFT DOUBLE QUOTE",
    chr(0x201D): "RIGHT DOUBLE QUOTE",
}


def test_r18_files_ascii_clean() -> None:
    for path in (BUILD_ORDER, AUGMENT_RECO, MAP_STATE_JS):
        text = path.read_text(encoding="utf-8")
        hits = [name for ch, name in _BAD.items() if ch in text]
        assert hits == [], f"{path.name} contains forbidden non-ASCII: {hits}"
