"""B4-b (RM-189): client-side directive gate - web/js/lib/live_directive_gate.js.

The AUTHORITATIVE B4 gate is server-side (dashboard/_state_builder.py -
suppress_live_directives / suppress_live_envelope, guarded by
tests/test_b4_live_directive_suppression.py). This module is defence in depth:
the envelope is cached client-side as state.latest and replayed on re-render,
so a payload captured a tick before the game started could otherwise repaint a
directive after it.

Two layers are pinned here:

  1. the predicate itself, node-required through the CommonJS export (mirrors
     tests/test_overlay_priority_rc2.py);
  2. the three renderers ACTUALLY going quiet - driven through a stub DOM in
     node, exercising the real pre-game -> live transition rather than
     grepping for the call. A source grep would pass against wiring that is
     imported and never reached.

The transition is the case that matters: the renderers all early-return when
their dedup signature is unchanged, so "first render while live" leaves an
already-empty mount untouched and proves nothing. Painting first, then going
live, is what exercises the teardown.

Skips cleanly when node is unavailable so a runner without a JS toolchain
never hard-fails (the helpers ship as static JS).
"""
from __future__ import annotations

import json
import shutil
import subprocess
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
GATE_JS = REPO_ROOT / "web" / "js" / "lib" / "live_directive_gate.js"
CHOICES_JS = REPO_ROOT / "web" / "js" / "panels" / "coach_choices.js"
CALLOUTS_JS = REPO_ROOT / "web" / "js" / "panels" / "callouts.js"
NODE = shutil.which("node")

# A live envelope: a game-shaped mode_key AND a non-empty liveclient.
LIVE = {"mode_key": "aram", "liveclient": {"champion": "Kai'Sa",
                                           "game_time": "14:54"}}
# Champ select: the LCU pre-flip has mirrored aram_mode onto health, but no
# game is running yet, so liveclient is still {}.
CHAMP_SELECT = {"mode_key": "aram", "liveclient": {},
                "health": {"aram_mode": True}}
IDLE = {"mode_key": "client", "liveclient": {}}

CHOICES = [{"key": "A", "label": "Force a short trade", "confidence": "high"},
           {"key": "B", "label": "Back off", "confidence": "low"}]
CALLOUTS = [{"tag": "item2", "line": "2-item spike - force fights now",
             "eta_s": 0.0, "kind": "spike"}]
LEAD = {"state": "ahead", "magnitude": "large",
        "line": "Big lead: dive or roam, snowball it now."}


def _run_node(program: str) -> str:
    proc = subprocess.run([NODE, "-e", program], capture_output=True,
                          text=True, timeout=60)
    if proc.returncode != 0:
        raise AssertionError(
            f"node exited {proc.returncode}\nSTDOUT:{proc.stdout}"
            f"\nSTDERR:{proc.stderr}")
    return proc.stdout.strip()


@unittest.skipIf(NODE is None, "node not available")
class GatePredicateTests(unittest.TestCase):
    def _gate(self, fn: str, state) -> bool:
        out = _run_node(
            f"const g = require({json.dumps(GATE_JS.as_posix())});\n"
            f"console.log(JSON.stringify(g.{fn}({json.dumps(state)})));")
        return json.loads(out)

    def test_live_game_is_live(self):
        self.assertTrue(self._gate("isLiveGame", LIVE))

    def test_champ_select_is_not_live(self):
        """The whole reason the client predicate keys off liveclient and not
        the health flags: apply_preflip_mirror stamps aram_mode onto health
        during champ select, which is pre-game and stays coached."""
        self.assertFalse(self._gate("isLiveGame", CHAMP_SELECT))
        self.assertTrue(self._gate("directivesAllowed", CHAMP_SELECT))

    def test_idle_is_not_live(self):
        self.assertFalse(self._gate("isLiveGame", IDLE))

    def test_game_mode_key_without_liveclient_is_not_live(self):
        self.assertFalse(self._gate("isLiveGame",
                                    {"mode_key": "sr", "liveclient": {}}))

    def test_liveclient_without_game_mode_key_is_not_live(self):
        self.assertFalse(self._gate(
            "isLiveGame", {"mode_key": "client", "liveclient": {"a": 1}}))

    def test_every_game_mode_counts(self):
        for mk in ("sr", "aram", "arena", "tft", "brawl"):
            with self.subTest(mode_key=mk):
                self.assertTrue(self._gate(
                    "isLiveGame", {"mode_key": mk, "liveclient": {"a": 1}}))

    def test_garbage_fails_open_not_closed(self):
        """Fail-SAFE, deliberately. A fail-closed default would blank the
        legitimate pre-game / post-game coaching every time a tick arrived
        malformed; the compliance guarantee rests on the server blanking the
        fields, not on this."""
        for bad in (None, "nope", 7, []):
            with self.subTest(bad=bad):
                self.assertFalse(self._gate("isLiveGame", bad))
                self.assertTrue(self._gate("directivesAllowed", bad))


# A stub DOM sufficient for the three renderers. Records innerHTML + hidden per
# mount so the assertions read the real render result.
_DOM_STUB = """
const mounts = {};
function makeMount(id) {
  return {
    id, innerHTML: "", hidden: true,
    classList: { add() {}, remove() {} },
    querySelectorAll() { return { forEach() {} }; },
  };
}
for (const id of ["rn-choices", "rn-callouts", "rn-lead"]) {
  mounts[id] = makeMount(id);
}
globalThis.document = { getElementById: (id) => mounts[id] || null };
"""


@unittest.skipIf(NODE is None, "node not available")
class RendererGoesQuietTests(unittest.TestCase):
    """Drive the real ES modules and assert the mounts empty out when the
    game goes live."""

    def _render_transition(self, module_path: Path, fn: str, mount_id: str,
                           pre_state: dict, live_state: dict) -> dict:
        program = (
            _DOM_STUB
            + "(async () => {\n"
            + f"  const m = await import({json.dumps(module_path.as_uri())});\n"
            + f"  m.{fn}({json.dumps(pre_state)});\n"
            + f"  const painted = mounts[{json.dumps(mount_id)}].innerHTML;\n"
            + f"  const paintedHidden = mounts[{json.dumps(mount_id)}].hidden;\n"
            + f"  m.{fn}({json.dumps(live_state)});\n"
            + f"  const after = mounts[{json.dumps(mount_id)}].innerHTML;\n"
            + f"  const afterHidden = mounts[{json.dumps(mount_id)}].hidden;\n"
            + "  console.log(JSON.stringify({painted, paintedHidden,"
              " after, afterHidden}));\n"
            + "})();\n"
        )
        return json.loads(_run_node(program))

    def test_choices_chips_clear_when_the_game_starts(self):
        r = self._render_transition(
            CHOICES_JS, "renderCoachChoices", "rn-choices",
            {**CHAMP_SELECT, "coach": {"choices": CHOICES}},
            {**LIVE, "coach": {"choices": CHOICES}},
        )
        self.assertIn("rc-chip", r["painted"],
                      "pre-game chips must still paint, else this is vacuous")
        self.assertFalse(r["paintedHidden"])
        self.assertEqual(r["after"], "")
        self.assertTrue(r["afterHidden"])

    def test_callouts_clear_when_the_game_starts(self):
        r = self._render_transition(
            CALLOUTS_JS, "renderCallouts", "rn-callouts",
            {**CHAMP_SELECT, "callouts": CALLOUTS},
            {**LIVE, "callouts": CALLOUTS},
        )
        self.assertIn("force fights now", r["painted"])
        self.assertFalse(r["paintedHidden"])
        self.assertEqual(r["after"], "")
        self.assertTrue(r["afterHidden"])

    def test_lead_clears_when_the_game_starts(self):
        r = self._render_transition(
            CALLOUTS_JS, "renderLead", "rn-lead",
            {**CHAMP_SELECT, "lead_projection": LEAD},
            {**LIVE, "lead_projection": LEAD},
        )
        self.assertIn("snowball it now", r["painted"])
        self.assertFalse(r["paintedHidden"])
        self.assertEqual(r["after"], "")
        self.assertTrue(r["afterHidden"])


if __name__ == "__main__":
    unittest.main()
