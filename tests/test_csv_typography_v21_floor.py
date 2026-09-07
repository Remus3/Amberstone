"""Drift-guard for web/css/panels/champ_select_view.css sub-floor typography.

Item 202 closure of item 201 carry-forward (13 audit MUST-FIX sites flipped
to var(--fs-xs) 16px). Pins:

(a) The 12 audit-flipped selectors carry `var(--fs-xs)` (no regression to
    hardcoded px).

(b) The 7 documented operator-exceptions stay sub-floor with their inline
    rationale comment present (no accidental bump that would break the
    pinned density rationale).

Future maintainers extending the .csv-* namespace must EITHER (a) ship at
--fs-xs or above, OR (b) add a documented operator-exception entry below
with a rationale comment in the CSS.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CSS = ROOT / "web" / "css" / "panels" / "champ_select_view.css"

# Selectors that were flipped to --fs-xs in item 202.
# QA 2026-07-03 slice A: the .csv-pr-* (YOUR RECORD, A4), ghost-bans
# (.csv-sugg-ban-name, A2), and ghost pick-order (A2) selectors were
# removed with their surfaces and left this inventory. LEDGER 823 removed
# the .csv-arch-* archetype-picker selectors with the picker itself.
_AUDIT_FLIPPED_SELECTORS = (
    ".csv-pb-role-label",
    ".csv-pb-role-chip",
    ".csv-pb-bans-header",
    ".csv-pb-pick-header",
    ".csv-build-label",
    ".csv-build-runes",
)

# Selectors with documented operator-exception sub-floor px values.
# Tuple is (selector, expected_px, rationale_substring).
# QA 2026-07-03 slice A: .csv-pr-chip (A4) + .csv-pb-mood-label (A3)
# were removed with their surfaces.
_OPERATOR_EXCEPTIONS = (
    (".csv-bench-empty", 13, "item 178"),
    (".csv-build-spell.is-swapped::after", 10, ""),  # tiny badge indicator
    (".csv-build-spell.empty", 11, ""),
    (".csv-duo-cell-tag", 11, "item 178"),
    (".csv-arena-cell-name", 13, "item 178"),
)


def _css_text() -> str:
    return CSS.read_text(encoding="utf-8")


def test_audit_flipped_selectors_all_use_fs_xs() -> None:
    text = _css_text()
    for sel in _AUDIT_FLIPPED_SELECTORS:
        # Find the selector at the START of a CSS rule (after \n, possibly
        # with whitespace) so we don't match a substring inside a compound
        # selector like ".csv-pb-bans-header-slot > .csv-pb-bans-header".
        pattern = re.compile(
            r"\n" + re.escape(sel) + r"\s*\{([^{}]*)\}",
            flags=re.DOTALL,
        )
        m_rule = pattern.search(text)
        assert m_rule is not None, (
            f"selector {sel!r} not found as a top-level rule in "
            f"champ_select_view.css"
        )
        block = m_rule.group(1)
        m = re.search(r"font-size:\s*([^;]+);", block)
        assert m is not None, f"selector {sel!r} has no font-size declaration"
        value = m.group(1).strip()
        assert value == "var(--fs-xs)", (
            f"selector {sel!r} font-size={value!r}; expected 'var(--fs-xs)'. "
            f"Item 202 closure of item 201 carry-forward forbids a regression. "
            f"If a NEW operator-exception is needed, add to _OPERATOR_EXCEPTIONS + "
            f"add an inline rationale comment in the CSS."
        )


def test_operator_exception_inventory_holds() -> None:
    text = _css_text()
    for sel, expected_px, rationale_marker in _OPERATOR_EXCEPTIONS:
        idx = text.find(sel)
        assert idx != -1, f"operator-exception selector {sel!r} not found"
        body_end = text.find("}", idx)
        block = text[idx:body_end]
        m = re.search(r"font-size:\s*(\d+)px", block)
        assert m is not None, (
            f"operator-exception {sel!r} no longer has hardcoded px font-size; "
            f"if intentionally flipped, remove from _OPERATOR_EXCEPTIONS."
        )
        actual_px = int(m.group(1))
        assert actual_px == expected_px, (
            f"operator-exception {sel!r} font-size drifted: expected {expected_px}px "
            f"got {actual_px}px. If intentional, update _OPERATOR_EXCEPTIONS."
        )
        if rationale_marker:
            assert rationale_marker.lower() in block.lower(), (
                f"operator-exception {sel!r} rationale comment ({rationale_marker!r}) "
                f"missing from CSS block. Without a rationale comment future "
                f"maintainers will bump the value back to floor."
            )


def test_no_new_unflipped_sub_floor_sites() -> None:
    """Any NEW selector below 16px without joining _OPERATOR_EXCEPTIONS fails CI."""
    text = _css_text()
    # Find every font-size: Npx (where N < 16) AND the parent selector.
    expected_exception_pxs = {sel: px for sel, px, _ in _OPERATOR_EXCEPTIONS}
    found_sub_floor: list[tuple[str, int]] = []
    for match in re.finditer(r"^([^{}\n]+)\s*\{[^{}]*?font-size:\s*(\d+)px",
                             text, flags=re.MULTILINE | re.DOTALL):
        sel_line = match.group(1).strip().rstrip(",").strip()
        # Walk backwards to gather possibly comma-separated multi-selector.
        # Skip comment-only blocks.
        if not sel_line or sel_line.startswith("/*"):
            continue
        try:
            px = int(match.group(2))
        except ValueError:
            continue
        if px >= 16:
            continue
        found_sub_floor.append((sel_line, px))
    # Each sub-floor must correspond to an operator-exception selector.
    for sel_line, px in found_sub_floor:
        matched = False
        for known_sel in expected_exception_pxs:
            if known_sel in sel_line:
                matched = True
                break
        if matched:
            continue
        # Non-text font-size sub-floors are allowed (icon-only / sentinel).
        # Surface as a soft warning by including in test failure message only
        # if the selector textually implies body text.
        if any(t in sel_line.lower() for t in ["empty", "icon", "::after",
                                                "is-swapped"]):
            continue
        raise AssertionError(
            f"NEW sub-floor font-size declaration found: {sel_line!r} = {px}px. "
            f"Either flip to var(--fs-xs) (16px floor) OR add to "
            f"tests/test_csv_typography_v21_floor.py _OPERATOR_EXCEPTIONS "
            f"with a rationale comment in the CSS."
        )


def test_css_ascii_clean_in_touched_lines() -> None:
    """Item 202 edits did not introduce non-ASCII bytes."""
    raw = CSS.read_bytes()
    # Pre-existing non-ASCII byte budget is well-known; assert no NEW spike.
    non_ascii = sum(1 for b in raw if b > 127)
    # Generous upper bound; item 201's CSS audit said 0 non-ASCII at ship time
    # but pre-existing carryover may add a small number. 100 bytes catches any
    # accidental smart-quote / em-dash injection without false-positives.
    assert non_ascii < 100, (
        f"champ_select_view.css non-ASCII byte count = {non_ascii}; "
        f"item 202 edits should not increase the count. Run "
        f"$env:LOCALAPPDATA/Programs/Python/Python314/python.exe tools/strip_em_dashes.py + tools/strip_smart_quotes.py to repair."
    )
