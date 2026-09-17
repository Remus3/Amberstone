"""web/legacy_index.html renderLcuPanel after RM-382 moved the sentinels to None.

RM-382 changed both LCU snapshot producers to emit a null phase where they
used to emit the truthy ``"Offline"`` (tools/lcu_agent.capture_state, no
lockfile) and ``"Unknown"`` (lcu/snapshot_shape, failed phase read). The
legacy page - served at ``?ui=legacy`` AND as the fallback when web/index.html
fails to load (dashboard/routes_static.py) - gated on ``!lcu.phase``, so a
closed client flipped from "League client closed" plus the auto-accept /
summoner toggles to the relay-offline text with no toggles.

The contract pinned here, on the snapshot shape both producers share:

  * no snapshot (``{}`` - what dashboard/_liveclient.lcu_summary returns when
    the relay is down or stale) -> relay-offline text, no toggles;
  * ``config`` present, no ``lcu_port``, null phase (agent up, client closed)
    -> "League client closed" plus the toggles;
  * ``config`` + ``lcu_port``, null phase (one failed phase read) -> the
    "Unknown" label plus the toggles, as before RM-382;
  * a real phase renders its label unchanged.

The function is extracted from the page and driven in node through a stub
DOM (the test_b4_client_directive_gate.py idiom), so this pins rendered
output, not the presence of a string. Skips cleanly when node is absent.

All authored content here is 7-bit ASCII.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
LEGACY_HTML = REPO_ROOT / "web" / "legacy_index.html"
NODE = shutil.which("node")

_FN_RE = re.compile(r"^function renderLcuPanel\(lcu\) \{\n.*?^\}\n", re.S | re.M)

_CASES = {
    "relay_down": {},
    "client_closed": {"config": {"auto_accept": True}, "ts": 1.0, "phase": None},
    "failed_phase_read": {"config": {}, "lcu_port": "51234", "ts": 1.0, "phase": None},
    "real_phase": {"config": {}, "lcu_port": "51234", "ts": 1.0, "phase": "Lobby"},
}

_HARNESS = """
globalThis.document = {
  createElement: () => ({ className: "", innerHTML: "" }),
  getElementById: () => null,
};
globalThis.lcuCfgState = () => ({});
globalThis.lcuCfgSave = () => {};
globalThis.lcuCmd = () => {};
globalThis.lobbyState = () => ({});
globalThis.champIconUrl = () => "";
globalThis.champName = () => "";
globalThis.SUMM_SPELLS = [];
%(fn)s
const cases = %(cases)s;
const out = {};
for (const [k, v] of Object.entries(cases)) out[k] = renderLcuPanel(v).innerHTML;
process.stdout.write(JSON.stringify(out));
"""


def extract_render_fn(html: str) -> str:
    m = _FN_RE.search(html)
    if m is None:
        raise AssertionError("renderLcuPanel(lcu) not found in the legacy page")
    return m.group(0)


def render_cases(html: str) -> dict:
    script = _HARNESS % {"fn": extract_render_fn(html), "cases": json.dumps(_CASES)}
    proc = subprocess.run([NODE, "-e", script], capture_output=True, text=True, encoding="utf-8", timeout=30)
    if proc.returncode != 0:
        raise AssertionError(f"node failed: {proc.stderr}")
    return json.loads(proc.stdout)


@unittest.skipIf(NODE is None, "node not available")
class LegacyLcuPanelPhaseTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.out = render_cases(LEGACY_HTML.read_text(encoding="utf-8"))

    def test_extraction_anchor(self):
        """An empty extraction must not pass: every case rendered a heading."""
        self.assertEqual(set(self.out), set(_CASES))
        for k, html in self.out.items():
            with self.subTest(case=k):
                self.assertIn("League Client (LCU)", html)

    def test_relay_down_keeps_relay_offline_text(self):
        html = self.out["relay_down"]
        self.assertIn("Relay offline", html)
        self.assertNotIn("cfg-aa", html)

    def test_client_closed_renders_closed_text_and_toggles(self):
        html = self.out["client_closed"]
        self.assertIn("League client closed", html)
        self.assertNotIn("Relay offline", html)
        self.assertIn('id="cfg-aa"', html)
        self.assertIn('id="cfg-so"', html)

    def test_failed_phase_read_keeps_unknown_label_and_toggles(self):
        html = self.out["failed_phase_read"]
        self.assertIn(">Unknown<", html)
        self.assertNotIn("Relay offline", html)
        self.assertIn('id="cfg-aa"', html)

    def test_real_phase_label_unchanged(self):
        html = self.out["real_phase"]
        self.assertIn("In Lobby", html)
        self.assertIn('id="cfg-aa"', html)


if __name__ == "__main__":
    unittest.main()
