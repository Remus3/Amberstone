"""Minimap CLEAR-ON-EXIT guard (arena stale-box bug, measured live 2026-07-20).

BUG. The operator played an ARAM game (minimap outline box painted, correctly)
and then an Arena/CHERRY game. The ARAM w-mmrect box stayed painted over the
Arena minimap for the WHOLE game - visible in screenshots from round 1 through
round 9.

ROOT CAUSE. setupMinimapPoller in web/js/main.js gates the minimap block on a
NARROW mode set ["sr", "aram", "brawl"]. That gate is CORRECT and must NOT
widen (arena / tft have no minimap; their renderers must never fire there).
The defect is that nothing ran when the gate went FALSE:

  * this poller is the ONLY unconditional in-game feed of the three minimap
    siblings (minimap_rect / minimap_dots / zoi) - the :8891 WS push does not
    carry them and the HTTP-fallback / LCU / SSE paths short-circuit while the
    WS feed is fresh (see the poller's own docstring);
  * so on an aram -> arena flip state.latest.minimap_rect kept the LAST ARAM
    rect, and the UNGATED onState dispatch
    (renderMinimapRect((state.latest && state.latest.minimap_rect) || null))
    happily repainted that stale rect on every frame.

FIX (pinned here). A latched clear-on-exit inside the same poller: on the first
tick whose mode_key is out of the narrow set, null the three siblings and call
both renderers with null so the mounts hide - once per transition, re-armed on
re-entry, and never on a failed fetch (a transient poll error must not blank a
live minimap - feedback_no_reflow_on_data_absence).

TWO renderer facts this test pins, because the fix depends on them:
  1. minimap_rect.renderMinimapRect has an idempotency guard (sig === _lastSig)
     BEFORE its null check. It does NOT swallow the clear: the signature of a
     null rect is the empty string, which can never equal a painted signature,
     so the first null call falls through and hides the mount.
  2. minimap_zoi.renderMinimapZoi debounces TRANSIENT nulls - it clears the
     canvas only after _NULL_CLEAR_STREAK consecutive null ticks. A single null
     call would leave the last ZOI scene painted, so the fix repeats the null
     at least _NULL_CLEAR_STREAK times on the exit transition. This test pins
     main.js's repeat count >= the module's streak constant so the two cannot
     drift apart.

Grep-style contract test, mirroring tests/test_overlay_a3_coach_tag_strip.py +
tests/test_overlay_poller_mode_gate.py: pathlib reads + substring/index asserts
over the .js source, no DOM emulation (there is no jsdom harness in the tree).
main.js is a side-effectful boot module and the poller is a non-exported IIFE,
so a source-pin is the strongest headless proof available.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
MAIN_JS = REPO / "web" / "js" / "main.js"
MINIMAP_RECT_JS = REPO / "web" / "js" / "panels" / "minimap_rect.js"
MINIMAP_ZOI_JS = REPO / "web" / "js" / "panels" / "minimap_zoi.js"

NARROW_GATE = '["sr", "aram", "brawl"].includes(st.mode_key)'
WIDE_GATE = '["sr", "aram", "brawl", "arena", "tft"].includes(st.mode_key)'

PAINT_CALLS = (
    "renderMinimapRect(state.latest.minimap_rect)",
    "renderMinimapZoi(state.latest.zoi)",
)
CLEAR_NULLS = (
    "state.latest.minimap_rect = null",
    "state.latest.minimap_dots = null",
    "state.latest.zoi = null",
)
EXIT_BRANCH = "} else if (st && !mmCleared && !_amIsMock()) {"


def _poller_region() -> str:
    """Slice out the setupMinimapPoller IIFE body (up to the next IIFE)."""
    js = MAIN_JS.read_text(encoding="utf-8")
    start = js.index("function setupMinimapPoller")
    end = js.index("function setupVoiceToggle", start)
    return js[start:end]


def _fn_body(src: str, head: str) -> str:
    """Source of the function whose declaration line starts with `head`, up to
    its closing brace at the SAME indentation as the declaration."""
    i = src.index(head)
    line_start = src.rfind("\n", 0, i) + 1
    indent = src[line_start:i]
    close = f"\n{indent}}}"
    j = src.index(close, i)
    return src[i:j + len(close)]


def _js_rect_sig(rect, iw: int, ih: int, z: float) -> str:
    """Reference re-impl of minimap_rect._sig (same expression as the JS)."""
    if rect is None:
        return ""
    flip = 1 if rect.get("flip") else 0
    return (f"{rect['x']},{rect['y']},{rect['w']},{rect['h']},{flip}"
            f"|{iw}x{ih}@{z}")


def _int_const(src: str, name: str) -> int:
    m = re.search(rf"const\s+{re.escape(name)}\s*=\s*(\d+)\s*;", src)
    assert m is not None, f"const {name} not found"
    return int(m.group(1))


class GateStaysNarrow(unittest.TestCase):
    """The gate itself must NOT widen - the whole point of the fix is that
    arena/tft still never PAINT a minimap widget."""

    def setUp(self):
        self.region = _poller_region()

    def test_narrow_gate_still_present_once(self):
        self.assertEqual(1, self.region.count(NARROW_GATE))

    def test_paint_calls_stay_inside_the_narrow_block(self):
        narrow = self.region.index(NARROW_GATE)
        wide = self.region.index(WIDE_GATE)
        for token in PAINT_CALLS:
            with self.subTest(token=token):
                self.assertEqual(
                    1, self.region.count(token),
                    f"{token} must paint from exactly one site",
                )
                idx = self.region.index(token)
                self.assertGreater(idx, narrow)
                self.assertLess(
                    idx, wide,
                    f"{token} leaked past the wider gate - would paint on "
                    "arena/tft which have no minimap",
                )


class ClearOnExitWired(unittest.TestCase):
    """A dedicated clear helper drops the stale siblings AND hides both
    widgets."""

    def setUp(self):
        self.region = _poller_region()

    def test_clear_helper_exists(self):
        self.assertIn("function clearMinimapWidgets()", self.region)

    def test_clear_helper_nulls_all_three_siblings(self):
        body = _fn_body(self.region, "function clearMinimapWidgets()")
        for token in CLEAR_NULLS:
            with self.subTest(token=token):
                self.assertIn(
                    token, body,
                    "the stale sibling must be dropped from state.latest - "
                    "the UNGATED onState dispatch repaints straight off it",
                )

    def test_clear_helper_calls_both_renderers_with_null(self):
        body = _fn_body(self.region, "function clearMinimapWidgets()")
        self.assertIn("renderMinimapRect(null)", body)
        self.assertIn("renderMinimapZoi(null)", body)

    def test_clear_helper_is_ascii(self):
        body = _fn_body(self.region, "function clearMinimapWidgets()")
        self.assertTrue(body.isascii(), "7-bit ASCII only (repo hard rule)")


class ClearIsLatchedOncePerTransition(unittest.TestCase):
    """Fire once per exit, re-arm on re-entry, never on a failed fetch."""

    def setUp(self):
        self.region = _poller_region()

    def test_latch_declared_false(self):
        self.assertIn("let mmCleared = false;", self.region)

    def test_exit_branch_is_latched_and_requires_a_live_payload(self):
        # `st &&` -> a failed/empty fetch never clears (no reflow on absence);
        # `!mmCleared` -> one clear per transition, not a per-tick storm;
        # `!_amIsMock()` -> see UiMockIsExempt below.
        self.assertIn(EXIT_BRANCH, self.region)

    def test_latch_is_set_before_clearing(self):
        exit_idx = self.region.index(EXIT_BRANCH)
        set_idx = self.region.index("mmCleared = true;", exit_idx)
        call_idx = self.region.index("clearMinimapWidgets();", exit_idx)
        self.assertLess(set_idx, call_idx)

    def test_latch_rearms_inside_the_narrow_block(self):
        narrow = self.region.index(NARROW_GATE)
        wide = self.region.index(WIDE_GATE)
        rearm = self.region.index("mmCleared = false;", narrow)
        self.assertLess(
            rearm, wide,
            "the latch must re-arm while in a minimap mode so a LATER exit "
            "clears again",
        )


class UiMockIsExempt(unittest.TestCase):
    """?ui_mock=1 paints both widgets from the LOCAL fixture
    (_amMockData.minimap_rect / .zoi), not from /api/state - and the UI-audit
    harness (tests/snapshot_panels/test_overlay_view.py::_open_overlay) serves
    an EMPTY /api/state. Without the exemption the poller reads mode_key
    undefined, calls that "out of the minimap set" and blanks the very box the
    audit capture exists to show (caught by
    test_overlay_minimap_rect_is_clickthrough_outline_widget)."""

    def test_exit_branch_skips_ui_mock(self):
        self.assertIn("!_amIsMock()", _poller_region())

    def test_ui_mock_helper_still_exists(self):
        self.assertIn(
            "function _amIsMock()", MAIN_JS.read_text(encoding="utf-8"),
        )


class ZoiNullDebounceSatisfied(unittest.TestCase):
    """renderMinimapZoi only clears its canvas after _NULL_CLEAR_STREAK
    consecutive nulls; a mode exit is definitive, not transient, so the clear
    repeats the null at least that many times."""

    def test_module_streak_constant_is_readable(self):
        zoi = MINIMAP_ZOI_JS.read_text(encoding="utf-8")
        self.assertGreaterEqual(_int_const(zoi, "_NULL_CLEAR_STREAK"), 1)

    def test_main_repeat_count_meets_or_exceeds_the_streak(self):
        zoi = MINIMAP_ZOI_JS.read_text(encoding="utf-8")
        streak = _int_const(zoi, "_NULL_CLEAR_STREAK")
        ticks = _int_const(_poller_region(), "MM_ZOI_NULL_TICKS")
        self.assertGreaterEqual(
            ticks, streak,
            "one null call would leave the last ZOI scene painted - the exit "
            "clear must satisfy minimap_zoi._NULL_CLEAR_STREAK",
        )

    def test_clear_helper_loops_the_null_call(self):
        body = _fn_body(_poller_region(), "function clearMinimapWidgets()")
        self.assertIn("MM_ZOI_NULL_TICKS", body)


class RectIdempotencyGuardDoesNotSwallowTheClear(unittest.TestCase):
    """minimap_rect._sig(null) is "" - never equal to a painted signature - so
    the sig-dedup early return cannot swallow the hide."""

    def setUp(self):
        self.src = MINIMAP_RECT_JS.read_text(encoding="utf-8")

    def test_null_signature_is_empty_string(self):
        self.assertEqual("", _js_rect_sig(None, 1920, 1080, 1))

    def test_painted_signature_is_never_empty(self):
        rect = {"x": 1462, "y": 764, "w": 302, "h": 302, "flip": False}
        self.assertNotEqual("", _js_rect_sig(rect, 1920, 1080, 1))

    def test_js_sig_returns_empty_for_a_null_rect(self):
        body = _fn_body(self.src, "function _sig(r, iw, ih, z)")
        self.assertIn("return r ?", body)
        self.assertIn(': "";', body)

    def test_js_null_branch_hides_the_mount(self):
        self.assertIn("if (!r) {\n    mount.hidden = true;", self.src)

    def test_sig_guard_precedes_the_null_hide(self):
        guard = self.src.index("if (sig === _lastSig) return;")
        hide = self.src.index("if (!r) {\n    mount.hidden = true;")
        self.assertLess(
            guard, hide,
            "documents the ordering the fix relies on: the guard runs first "
            "and is passed through because the null sig differs",
        )


if __name__ == "__main__":
    unittest.main()
