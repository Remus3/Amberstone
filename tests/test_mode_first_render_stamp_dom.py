"""Regression guard: setMode must stamp the DOM on the FIRST render.

Bug (observed 2026-08-02 on a freshly relaunched rc-shell companion):
``state.mode`` is SEEDED to "client" in ``web/js/lib/state.js``, and
``setMode(tag)`` early-returned on ``tag === state.mode``. So a fresh page
whose first resolved mode is "client" - the ordinary out-of-game case -
never stamped anything: ``document.title`` stayed on index.html's static
"Amberstone - Phase 3", and the mode pill + ``body[data-mode]`` kept
their markup defaults. A long-lived page looked fine only because some
earlier REAL mode flip had eventually stamped it, which is why this
survived: the failure is invisible on any page that has been open a while.

The fix adds a `_modeStamped` latch so the first call always stamps while a
later unchanged tag stays a no-op (the health and state envelopes both call
setMode on their own cadence and must not repaint every tick). The s158
transition log stays gated on an ACTUAL change - a first-render stamp is not
a transition, and a client->client entry would be noise in the ring buffer
that exists to make flicker visible.

Same idiom as test_mode_flap_deferral_dom / test_archetype_nudge_chip_dom:
these are source-shape smoke checks that trip if a refactor drops the
wiring. They do NOT execute the module - the behavioral proof for this fix
was a live render check, recorded in LEDGER 1167.
"""
from __future__ import annotations

import re
import unittest
from pathlib import Path

WEB = Path(__file__).resolve().parent.parent / "web"
MAIN_JS = WEB / "js" / "main.js"
STATE_JS = WEB / "js" / "lib" / "state.js"


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


class SetModeFirstRenderTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.main = _read(MAIN_JS)
        cls.state = _read(STATE_JS)
        start = cls.main.find("function setMode(tag)")
        assert start != -1, "setMode(tag) not found in main.js"
        # Wide enough to cover all three stamp targets below (the last one,
        # body[data-mode], sits ~1900 chars in).
        cls.body = cls.main[start:start + 2400]

    def test_state_mode_is_still_seeded_to_client(self):
        """The precondition that makes the latch necessary. If this seed ever
        becomes empty the latch is harmless, but the comment explaining WHY it
        exists would be wrong - so pin it."""
        self.assertRegex(self.state, r'mode:\s*"client"')

    def test_setmode_no_longer_early_returns_on_the_seed_alone(self):
        """The exact defect: `if (!tag || tag === state.mode) return;`."""
        self.assertNotRegex(
            self.body,
            r"if\s*\(\s*!tag\s*\|\|\s*tag\s*===\s*state\.mode\s*\)\s*return",
            "setMode must not early-return on tag===state.mode without "
            "checking whether the DOM has ever been stamped",
        )

    def test_the_latch_exists_and_gates_the_early_return(self):
        self.assertIn("_modeStamped", self.main)
        self.assertRegex(self.main, r"let\s+_modeStamped\s*=\s*false")
        # An unchanged tag is only a no-op once something has been stamped.
        self.assertRegex(self.body, r"if\s*\(\s*!changed\s*&&\s*_modeStamped\s*\)\s*return")
        self.assertRegex(self.body, r"_modeStamped\s*=\s*true")

    def test_repeat_calls_are_still_suppressed(self):
        """The latch must not turn every envelope into a repaint - the guard
        still short-circuits an unchanged tag after the first stamp."""
        self.assertIn("!changed && _modeStamped", self.body)

    def test_transition_log_stays_gated_on_a_real_change(self):
        """A first-render stamp is not a transition; logging client->client
        would pollute the flicker-debug ring buffer."""
        self.assertRegex(
            self.body,
            r"if\s*\(\s*changed\s*\)\s*_rcLogTransition\(\"mode\"",
        )

    def test_the_stamp_targets_are_all_still_inside_setmode(self):
        """Title, pill and body[data-mode] are the three surfaces the early
        return was skipping; if one moves out, this guard stops covering it."""
        for needle in ("document.title", "modePill.textContent",
                       "document.body.dataset.mode"):
            self.assertIn(needle, self.body, f"{needle} left setMode")


class AsciiTests(unittest.TestCase):
    """Repo hard rule: no em/en dashes, no smart quotes in authored source."""

    def test_no_banned_glyphs_in_the_edited_region(self):
        start = MAIN_JS.read_text(encoding="utf-8").find("let _modeStamped")
        region = MAIN_JS.read_text(encoding="utf-8")[start - 900:start + 1600]
        # chr() rather than literals: tools/precommit_gate.py scans STAGED
        # LINES for these glyphs, so spelling them out would block this file.
        for bad in (chr(0x2013), chr(0x2014), chr(0x201c), chr(0x201d), chr(0x2018), chr(0x2019)):
            self.assertNotIn(bad, region, f"banned glyph {bad!r} in setMode region")


if __name__ == "__main__":
    unittest.main()
