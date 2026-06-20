"""Tests for web/js/lib/overlay_priority.js - RC2 Phase 3.2 S0 arbitration.

The helper is vanilla JS consumed by the overlay as an ES module. It decides
which single cue wins the scarce PRIMARY (S0) overlay slot each tick, and
whether the change-pulse may fire. This characterization suite drives node to
require() the CommonJS export and pins the priority ladder + pulse-rationing
contract that right_now.js / callouts.js consume.

Spec: docs/research/RC2_OVERLAY_CONDENSATION_SPEC.md sections 4 (arbitration)
and 5 (motion rationing). Acceptance A2 (exactly one pop-out) + A5 (pulse only
on Emergency / one-shot-Urgent cross).

Skips cleanly when node is unavailable so it never hard-fails CI on a runner
without a JS toolchain (the helper ships as static JS).
"""
from __future__ import annotations

import json
import shutil
import subprocess
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
PRIORITY_JS = REPO_ROOT / "web" / "js" / "lib" / "overlay_priority.js"
NODE = shutil.which("node")


def _run_js(snippet: str) -> str:
    require_path = PRIORITY_JS.as_posix()
    program = (
        f"const {{ selectPrimary, shouldPulse, signalFromState, "
        f"BAND_TIER, PRIORITY }} = "
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
            f"node exited {proc.returncode}\nSTDOUT:{proc.stdout}\nSTDERR:{proc.stderr}"
        )
    return proc.stdout.strip()


def _select(state: dict) -> dict:
    out = _run_js(
        f"console.log(JSON.stringify(selectPrimary({json.dumps(state)})));"
    )
    return json.loads(out)


@unittest.skipUnless(NODE, "node not on PATH - JS helper is static, skip")
class OverlayPriorityTest(unittest.TestCase):
    def test_file_exists(self):
        self.assertTrue(PRIORITY_JS.is_file(), f"missing {PRIORITY_JS}")

    def test_exports_present(self):
        out = _run_js(
            "console.log(JSON.stringify("
            "[typeof selectPrimary, typeof shouldPulse, "
            "typeof BAND_TIER, typeof PRIORITY]));"
        )
        self.assertEqual(json.loads(out), ["function", "function", "object", "object"])

    # ----- band -> tier map (spec section 1) -----
    def test_band_tier_map(self):
        out = _run_js("console.log(JSON.stringify(BAND_TIER));")
        self.assertEqual(
            json.loads(out),
            {"urgent": "emergency", "fight": "urgent", "good": "ambient",
             "empty": "empty"},
        )

    # ----- arbitration: highest-priority eligible cue wins S0 -----
    def test_lethal_wins_over_everything(self):
        sel = _select({"band": "fight", "hasChoices": True, "spikeCrossed": True,
                       "objectiveStealNow": True, "lethal": True})
        self.assertEqual(sel["cue"], "lethal")
        self.assertEqual(sel["tier"], "emergency")
        self.assertEqual(sel["priority"], 100)

    def test_objective_steal_over_choices(self):
        sel = _select({"band": "fight", "hasChoices": True, "spikeCrossed": False,
                       "objectiveStealNow": True, "lethal": False})
        self.assertEqual(sel["cue"], "objective_steal")
        self.assertEqual(sel["priority"], 90)

    def test_urgent_headline_band_is_emergency(self):
        sel = _select({"band": "urgent", "hasChoices": True, "spikeCrossed": False,
                       "objectiveStealNow": False, "lethal": False})
        self.assertEqual(sel["cue"], "urgent_headline")
        self.assertEqual(sel["tier"], "emergency")
        self.assertEqual(sel["priority"], 85)

    def test_choices_over_spike_and_fight(self):
        sel = _select({"band": "fight", "hasChoices": True, "spikeCrossed": True,
                       "objectiveStealNow": False, "lethal": False})
        self.assertEqual(sel["cue"], "choices")
        self.assertEqual(sel["priority"], 80)

    def test_spike_over_fight(self):
        sel = _select({"band": "fight", "hasChoices": False, "spikeCrossed": True,
                       "objectiveStealNow": False, "lethal": False})
        self.assertEqual(sel["cue"], "spike")
        self.assertEqual(sel["priority"], 70)

    def test_fight_band(self):
        sel = _select({"band": "fight", "hasChoices": False, "spikeCrossed": False,
                       "objectiveStealNow": False, "lethal": False})
        self.assertEqual(sel["cue"], "fight")
        self.assertEqual(sel["tier"], "urgent")
        self.assertEqual(sel["priority"], 60)

    def test_good_band_is_ambient(self):
        sel = _select({"band": "good", "hasChoices": False, "spikeCrossed": False,
                       "objectiveStealNow": False, "lethal": False})
        self.assertEqual(sel["cue"], "good")
        self.assertEqual(sel["tier"], "ambient")
        self.assertEqual(sel["priority"], 40)

    def test_empty_is_zero(self):
        sel = _select({"band": "empty", "hasChoices": False, "spikeCrossed": False,
                       "objectiveStealNow": False, "lethal": False})
        self.assertEqual(sel["cue"], "none")
        self.assertEqual(sel["tier"], "empty")
        self.assertEqual(sel["priority"], 0)

    def test_missing_fields_default_to_empty(self):
        # A bare/partial state must not throw; absent signals read as empty.
        sel = _select({})
        self.assertEqual(sel["cue"], "none")
        self.assertEqual(sel["priority"], 0)

    def test_null_state_is_none(self):
        out = _run_js("console.log(JSON.stringify(selectPrimary(null)));")
        sel = json.loads(out)
        self.assertEqual(sel["cue"], "none")
        self.assertEqual(sel["priority"], 0)

    # ----- pulse rationing (A5): Emergency + one-shot-Urgent cross only -----
    def _pulse(self, prev_cue, state) -> bool:
        out = _run_js(
            "const s = selectPrimary(" + json.dumps(state) + ");\n"
            "console.log(JSON.stringify("
            "shouldPulse(" + json.dumps(prev_cue) + ", s)));"
        )
        return json.loads(out)

    def test_pulse_fires_on_emergency_entry(self):
        # prev was a non-emergency cue, now lethal -> pulse.
        self.assertTrue(self._pulse("fight", {"band": "fight", "lethal": True}))

    def test_pulse_silent_on_sustained_emergency(self):
        # Same emergency cue two ticks running -> no re-pulse (alarm fatigue).
        self.assertFalse(self._pulse("lethal", {"band": "fight", "lethal": True}))

    def test_pulse_fires_on_emergency_cue_change(self):
        # objective_steal -> lethal is an escalation within emergency: pulse.
        self.assertTrue(self._pulse(
            "objective_steal", {"band": "fight", "lethal": True}))

    def test_pulse_fires_on_spike_cross(self):
        self.assertTrue(self._pulse(
            "fight", {"band": "fight", "spikeCrossed": True}))

    def test_pulse_fires_on_choices_appear(self):
        self.assertTrue(self._pulse(
            "fight", {"band": "fight", "hasChoices": True}))

    def test_pulse_silent_on_steady_fight(self):
        # fight is steady-Urgent: NO pulse even on a fresh headline.
        self.assertFalse(self._pulse(
            "good", {"band": "fight"}))

    def test_pulse_silent_on_good(self):
        self.assertFalse(self._pulse("empty", {"band": "good"}))

    def test_pulse_silent_on_sustained_spike(self):
        self.assertFalse(self._pulse(
            "spike", {"band": "fight", "spikeCrossed": True}))

    # ----- signalFromState: coach payload -> normalized S0 signal (3.3) -----
    # The shadow consumer (right_now.js) maps the live coach envelope into the
    # selectPrimary() signal through this one pure function, so the eventual
    # operator-gated live flip is a one-line swap (consume sel/pulse instead of
    # stamping). Pins band passthrough, choices detection, and the Phase-4
    # crossing-edge predicates (default false, honored when a producer sets
    # the named optional booleans - spec section 9 Q1/Q2).
    def _signal(self, p, band) -> dict:
        out = _run_js(
            "console.log(JSON.stringify(signalFromState("
            + json.dumps(p) + ", " + json.dumps(band) + ")));"
        )
        return json.loads(out)

    def test_signal_band_passthrough(self):
        self.assertEqual(self._signal({}, "fight")["band"], "fight")

    def test_signal_band_defaults_empty_on_non_string(self):
        self.assertEqual(self._signal({}, None)["band"], "empty")

    def test_signal_has_choices_true(self):
        sig = self._signal({"choices": [{"key": "A"}, {"key": "B"}]}, "good")
        self.assertTrue(sig["hasChoices"])

    def test_signal_has_choices_false_when_empty_or_absent(self):
        self.assertFalse(self._signal({"choices": []}, "good")["hasChoices"])
        self.assertFalse(self._signal({}, "good")["hasChoices"])

    def test_signal_combat_predicates_default_false(self):
        sig = self._signal({"choices": []}, "fight")
        self.assertFalse(sig["spikeCrossed"])
        self.assertFalse(sig["objectiveStealNow"])
        self.assertFalse(sig["lethal"])

    def test_signal_combat_predicates_honored_when_present(self):
        sig = self._signal(
            {"spike_crossed": True, "objective_steal_now": True,
             "lethal_incoming": True}, "fight")
        self.assertTrue(sig["spikeCrossed"])
        self.assertTrue(sig["objectiveStealNow"])
        self.assertTrue(sig["lethal"])

    def test_signal_feeds_select_primary_choices(self):
        out = _run_js(
            "const sig = signalFromState("
            "{choices:[{key:'A'},{key:'B'}]}, 'fight');\n"
            "console.log(JSON.stringify(selectPrimary(sig).cue));"
        )
        self.assertEqual(json.loads(out), "choices")

    def test_signal_null_payload_safe(self):
        sig = self._signal(None, "empty")
        self.assertEqual(sig["band"], "empty")
        self.assertFalse(sig["hasChoices"])


if __name__ == "__main__":
    unittest.main()
