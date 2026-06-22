"""RC2 P3.3 LIVE flip: overlay change-pulse consumes the S0 decision.

Operator-approved 2026-06-22 flip of the overlay emergency-pulse from
shadow-only to AUTHORITATIVE (docs/LIVE_GAME_GATED_SYNC.md). The S0
pulse-rationing decision was ALREADY computed in shadow
(overlay_priority.signalFromState -> selectPrimary -> shouldPulse) and
stamped on #right-now as data-s0-pulse. This flip re-points the two live
pulse sites to CONSUME that decision so motion fires ONLY for the EMERGENCY
tier + a one-shot URGENT cross, and STOPS firing for benign 'good' /
re-emit headline changes (spec section 5 / acceptance A5 motion rationing).

Two layers, matching the repo's overlay test style (tests/test_overlay_
priority_rc2.py runs node against the real helper; tests/test_overlay_route_
smoke.py + test_ui_polish_2026_05_20.py grep the consumer source):

  1. PulseDecisionChainTests - drive the REAL helper chain in node for the
     four acceptance cases the consumers gate on:
       (a) benign 'good' band            -> NO pulse
       (b) emergency / lethal            -> pulse
       (c) one-shot urgent (spike/choices) cross -> pulse once (then silent)
       (d) the lethal_incoming passthrough -> still pulses
     This is the exact boolean BOTH consumers consume (right_now.js via
     _s0Pulse, overlay_pulse.js via the data-s0-pulse stamp), so it pins the
     end-to-end behavior without a DOM emulator (none ships in this tree).

  2. ConsumerFlipWiringTests - grep both consumer sources to prove the flip
     actually landed: the per-band .action pulse is gated on the S0 decision
     (not bare isFreshAction), and overlay_pulse.js gates .ov-pulse on
     data-s0-pulse (not any mutation). These go RED before the flip edit.

Conservative-only contract (CLAUDE.md Data/Engine discipline + the flip
brief): the flip may ONLY ever suppress a pulse that fires today, never add
one. ConservativeSubsetTests pins that every case where the NEW decision
pulses is a case where the OLD bare-isFreshAction path also pulsed.

Skips cleanly when node is unavailable (the helper ships as static JS).
ASCII hygiene: forbidden-glyph dict built via chr() so the file stays clean
against its own scan.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
PRIORITY_JS = REPO / "web" / "js" / "lib" / "overlay_priority.js"
RIGHT_NOW_JS = REPO / "web" / "js" / "panels" / "right_now.js"
OVERLAY_PULSE_JS = REPO / "web" / "js" / "overlay_pulse.js"
NODE = shutil.which("node")


def _run_js(snippet: str) -> str:
    require_path = PRIORITY_JS.as_posix()
    program = (
        "const { selectPrimary, shouldPulse, signalFromState } = "
        f"require({json.dumps(require_path)});\n"
        f"{snippet}\n"
    )
    proc = subprocess.run(
        [NODE, "-e", program],
        capture_output=True,
        text=True,
        timeout=30,
    )
    if proc.returncode != 0:
        raise AssertionError(
            f"node exited {proc.returncode}\n"
            f"STDOUT:{proc.stdout}\nSTDERR:{proc.stderr}"
        )
    return proc.stdout.strip()


def _decide(prev_cue: str, coach_payload: dict, band: str) -> bool:
    """Return the live pulse decision for one render, through the REAL
    helper chain the consumers use: signalFromState -> selectPrimary ->
    shouldPulse. This is exactly right_now.js's _s0Pulse / the value
    written to #right-now[data-s0-pulse]."""
    out = _run_js(
        "const sig = signalFromState("
        + json.dumps(coach_payload) + ", " + json.dumps(band) + ");\n"
        "const sel = selectPrimary(sig);\n"
        "console.log(JSON.stringify("
        "shouldPulse(" + json.dumps(prev_cue) + ", sel)));"
    )
    return json.loads(out)


@unittest.skipUnless(NODE, "node not on PATH - JS helper is static, skip")
class PulseDecisionChainTests(unittest.TestCase):
    """The four acceptance cases (a-d) the flip must honor, evaluated on the
    real helper chain. prev_cue is the cue selected on the previous tick (the
    consumers carry it across renders); 'good' is the calm steady state."""

    # (a) benign 'good' band -> NO pulse (the headline updated to a benign
    #     ambient call; today this pulses rn-pulse-good, the flip silences it).
    def test_benign_good_band_does_not_pulse(self):
        self.assertFalse(_decide("good", {}, "good"))

    def test_benign_good_band_fresh_from_empty_does_not_pulse(self):
        # Even a FRESH good headline (empty -> good) must stay silent: it is
        # ambient, not an emergency or a one-shot urgent cross.
        self.assertFalse(_decide("none", {}, "good"))

    # (b) emergency / lethal -> pulse (entry from a non-emergency cue).
    def test_emergency_lethal_pulses_on_entry(self):
        self.assertTrue(_decide("fight", {"hp_pct": 18}, "fight"))

    def test_emergency_urgent_headline_pulses_on_entry(self):
        # The coach-flagged urgent headline band is the emergency tier too.
        self.assertTrue(_decide("good", {}, "urgent"))

    # (c) one-shot urgent cross -> pulse ONCE, then silent while sustained.
    def test_spike_cross_pulses_once_then_silent(self):
        # Fresh cross (prev=fight) pulses; sustained (prev=spike) does not.
        self.assertTrue(_decide("fight", {"spike_crossed": True}, "fight"))
        self.assertFalse(_decide("spike", {"spike_crossed": True}, "fight"))

    def test_choices_appear_pulses_once_then_silent(self):
        appear = {"choices": [{"key": "A"}, {"key": "B"}]}
        self.assertTrue(_decide("fight", appear, "fight"))
        self.assertFalse(_decide("choices", appear, "fight"))

    # (d) the explicit lethal_incoming passthrough still pulses (and is NOT
    #     silently dropped by the flip). It rides through signalFromState's
    #     lethal_incoming branch into the lethal (emergency) cue.
    def test_lethal_incoming_passthrough_still_pulses(self):
        self.assertTrue(_decide("fight", {"lethal_incoming": True}, "fight"))

    def test_lethal_incoming_passthrough_pulses_even_at_full_hp(self):
        # The explicit producer flag wins regardless of derived low-HP, so the
        # passthrough survives the flip exactly as before (back-compat).
        self.assertTrue(
            _decide("good", {"lethal_incoming": True, "hp_pct": 95}, "fight"))

    # Sustained emergency does not re-pulse (A5 - no alarm fatigue). Still a
    # suppression vs the old per-band path (which re-pulsed on every fresh
    # headline), so it is conservative.
    def test_sustained_emergency_does_not_repulse(self):
        self.assertFalse(_decide("lethal", {"hp_pct": 18}, "fight"))

    # Steady fight band is Urgent-steady, not one-shot: no pulse (today it
    # pulses rn-pulse-warn on every fresh headline; the flip silences it).
    def test_steady_fight_band_does_not_pulse(self):
        self.assertFalse(_decide("good", {}, "fight"))


@unittest.skipUnless(NODE, "node not on PATH - JS helper is static, skip")
class ConservativeSubsetTests(unittest.TestCase):
    """Conservative-only proof: for the bands the OLD per-band path pulsed on
    (urgent/fight/good, on any fresh headline), the NEW decision pulses on a
    strict SUBSET. We never pulse where the old path was silent."""

    def test_new_pulse_implies_old_pulse_across_bands(self):
        # Old per-band path: pulses iff isFreshAction AND band in
        # {urgent, fight, good} (pulseMap keys). Model "fresh headline" as a
        # cue cross by using a contrasting prev_cue, and sweep the bands +
        # the combat predicates. Every True from the new decision must fall in
        # an old-pulsing band.
        old_bands = {"urgent", "fight", "good"}
        cases = [
            # (prev_cue, payload, band)
            ("good", {}, "good"),
            ("none", {}, "good"),
            ("good", {}, "fight"),
            ("good", {}, "urgent"),
            ("fight", {"spike_crossed": True}, "fight"),
            ("fight", {"choices": [{"key": "A"}]}, "fight"),
            ("fight", {"hp_pct": 12}, "fight"),
            ("good", {"lethal_incoming": True}, "fight"),
            ("fight", {}, "empty"),
        ]
        for prev_cue, payload, band in cases:
            with self.subTest(prev=prev_cue, band=band, payload=payload):
                new_pulse = _decide(prev_cue, payload, band)
                if new_pulse:
                    # The empty band never carries a pulseMap entry, so a new
                    # pulse on empty would be a NON-conservative regression.
                    self.assertIn(
                        band, old_bands,
                        f"flip pulses on band={band!r} which the old per-band "
                        f"pulseMap never fired - that ADDS a pulse "
                        f"(non-conservative)",
                    )


class ConsumerFlipWiringTests(unittest.TestCase):
    """Grep-contract that the flip landed in BOTH live consumers. These go
    RED on the pre-flip source (bare isFreshAction / any-mutation) and GREEN
    once each pulse site consumes the S0 decision."""

    def test_right_now_per_band_pulse_gated_on_s0_decision(self):
        js = RIGHT_NOW_JS.read_text(encoding="utf-8")
        # The decision is hoisted to a render-scope flag the per-band site
        # consumes (the one-line swap the shadow design promised).
        self.assertIn("let _s0Pulse", js,
                      "right_now.js must hoist the S0 pulse decision (_s0Pulse) "
                      "so the per-band pulse can consume it")
        self.assertIn("_s0Pulse = shouldPulse(", js,
                      "right_now.js must assign _s0Pulse from shouldPulse(...)")
        # The per-band .action pulse fires only when the decision allows it.
        self.assertIn("if (isFreshAction && _s0Pulse)", js,
                      "right_now.js per-band pulse must be gated on _s0Pulse "
                      "(not bare isFreshAction) - this is the live flip")
        # The data-s0-pulse stamp is still written (overlay_pulse.js needs it).
        self.assertIn("dataset.s0Pulse", js,
                      "right_now.js must still stamp data-s0-pulse for "
                      "overlay_pulse.js to consume")

    def test_overlay_pulse_gated_on_s0_pulse_stamp(self):
        js = OVERLAY_PULSE_JS.read_text(encoding="utf-8")
        # The observer reads the right-now S0 decision stamp before firing.
        self.assertIn('getElementById("right-now")', js,
                      "overlay_pulse.js must read #right-now to consume the "
                      "S0 decision")
        self.assertIn('dataset.s0Pulse === "1"', js,
                      "overlay_pulse.js must gate on data-s0-pulse == '1'")
        # The gate is invoked inside the observer (an early-return before the
        # throttle/fire), so a benign mutation is suppressed.
        self.assertIn("_s0PulseArmed()", js,
                      "overlay_pulse.js must invoke the S0 gate")
        self.assertIn("if (!_s0PulseArmed()) return;", js,
                      "overlay_pulse.js must early-return when the S0 "
                      "decision is not armed (suppress benign mutations)")


class AsciiHygieneTests(unittest.TestCase):
    """CLAUDE.md hard rule: authored source stays 7-bit ASCII.

    overlay_pulse.js is glyph-free, so it is whole-file scanned (matching
    tests/test_overlay_route_smoke.py, which ASCII-scans overlay_pulse.js
    but deliberately NOT right_now.js). right_now.js carries pre-existing
    intentional UI glyphs (box-drawing, the priority chevron/warn glyphs,
    the DEAD-detector regex), so a whole-file scan there is wrong; instead
    this asserts the SPECIFIC lines THIS flip added are ASCII-clean. BAD
    dict via chr() so the test stays clean against its own scan."""

    BAD = {
        chr(0x2013): "EN DASH",
        chr(0x2014): "EM DASH",
        chr(0x2018): "LEFT SINGLE QUOTE",
        chr(0x2019): "RIGHT SINGLE QUOTE",
        chr(0x201C): "LEFT DOUBLE QUOTE",
        chr(0x201D): "RIGHT DOUBLE QUOTE",
    }

    # The exact lines this flip authored into right_now.js (must be ASCII).
    RIGHT_NOW_ADDED_LINES = (
        "let _s0Pulse = false;",
        "_s0Pulse = shouldPulse(_s0PrevCue, _sel);",
        "if (isFreshAction && _s0Pulse) {",
    )

    def _first_non_ascii(self, path: Path):
        data = path.read_bytes()
        return next(((i, b) for i, b in enumerate(data) if b > 0x7F), None)

    def test_overlay_pulse_file_is_pure_ascii(self):
        # Whole-file scan of the glyph-free overlay_pulse.js.
        bad = self._first_non_ascii(OVERLAY_PULSE_JS)
        self.assertIsNone(
            bad,
            f"non-ASCII byte in overlay_pulse.js: "
            f"0x{bad[1]:02X} at offset {bad[0]}" if bad else None,
        )

    def test_test_file_is_pure_ascii(self):
        bad = self._first_non_ascii(Path(__file__))
        self.assertIsNone(
            bad,
            f"non-ASCII byte in test file: "
            f"0x{bad[1]:02X} at offset {bad[0]}" if bad else None,
        )

    def test_right_now_added_lines_are_ascii(self):
        # right_now.js carries legitimate pre-existing glyphs; only assert the
        # lines THIS flip introduced are present and pure ASCII.
        js = RIGHT_NOW_JS.read_text(encoding="utf-8")
        for line in self.RIGHT_NOW_ADDED_LINES:
            with self.subTest(line=line):
                self.assertTrue(line.isascii(), f"added line not ASCII: {line}")
                self.assertIn(line, js,
                              f"expected flip line missing from right_now.js: "
                              f"{line}")

    def test_glyph_scan_clean(self):
        # overlay_pulse.js + the test file carry no smart quotes / dashes.
        for path in (OVERLAY_PULSE_JS, Path(__file__)):
            with self.subTest(file=path.name):
                text = path.read_text(encoding="utf-8")
                hits = [name for ch, name in self.BAD.items() if ch in text]
                self.assertEqual([], hits, f"{path.name} has forbidden glyphs")


if __name__ == "__main__":
    unittest.main()
