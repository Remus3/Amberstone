"""Item-1 Phase 5: relocate the champ-select auto-push toggles to Settings +
flip the default to ON.

The item-240 in-panel header control ([PUSH] button + 3 inline checkboxes on
the build-chooser title, opt-in all-OFF via the rc-cs-push-flags blob) is
SUPERSEDED here. The Runes/Spells/Build push toggles now live in the CHAMP
SELECT settings card (web/index.html), wired by an INVERTED dev.js binder
(checked unless the stored value is "0"), and champ_select._csvGetPushFlags
now DEFAULTS ON, reading three flat localStorage keys
rc-cs-push-{runes,spells,build}. The per-category push plumbing
(_csvPushCategory / _csvPushCheckedCategories) is left intact for Phase 6.

House pattern (mirrors tests/test_csv_build_chooser_part3_item240.py): grep the
source for the load-bearing ids / wiring / keys a refactor must not rip out,
plus a node round-trip of the default-ON _csvGetPushFlags contract.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
CHAMP_SELECT_JS = REPO_ROOT / "web" / "js" / "panels" / "champ_select.js"
DEV_JS = REPO_ROOT / "web" / "js" / "panels" / "dev.js"
INDEX_HTML = REPO_ROOT / "web" / "index.html"
_NODE = shutil.which("node")

_PUSH_KEYS = ("rc-cs-push-runes", "rc-cs-push-spells", "rc-cs-push-build")
_TOGGLE_IDS = ("set-push-runes", "set-push-spells", "set-push-build")


def _fn_body(text: str, sig: str) -> str:
    """Brace-balanced body of a top-level `function <sig> {`."""
    start = text.index(sig)
    open_brace = text.index("{", start)
    depth = 0
    for i in range(open_brace, len(text)):
        c = text[i]
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return text[open_brace:i + 1]
    raise AssertionError(f"unbalanced braces after {sig!r}")


class SettingsCardTogglesTests(unittest.TestCase):
    """The 3 push toggles live in the CHAMP SELECT settings card, wired by the
    inverted dev.js binder against the 3 flat keys."""

    @classmethod
    def setUpClass(cls):
        cls.html = INDEX_HTML.read_text(encoding="utf-8")
        cls.dev = DEV_JS.read_text(encoding="utf-8")

    def test_three_toggle_inputs_present(self):
        for tid in _TOGGLE_IDS:
            self.assertIn(f'id="{tid}"', self.html,
                f"missing the {tid} push toggle in the settings card (Phase 5).")

    def test_toggles_live_under_champ_select_card(self):
        # Land in today's CHAMP SELECT card (item-4's Client Settings rename is
        # separate/later). Bound by the next settings-card-head.
        i = self.html.index("CHAMP SELECT")
        nxt = self.html.index("settings-card-head", i + 1)
        card = self.html[i:nxt]
        for tid in _TOGGLE_IDS:
            self.assertIn(f'id="{tid}"', card,
                f"{tid} must sit inside the CHAMP SELECT settings card (Phase 5).")

    def test_dev_binder_wires_each_toggle_to_its_flat_key(self):
        for tid, key in zip(_TOGGLE_IDS, _PUSH_KEYS):
            self.assertRegex(
                self.dev, rf'"{tid}"\s*,\s*"{key}"',
                f"dev.js must bind {tid} -> {key} (Phase 5).")

    def test_dev_binder_is_inverted_default_on(self):
        # Checked unless the stored value is "0" (opt-OUT), not checked only on
        # "1" (the item-240 opt-in).
        self.assertIn('!== "0"', self.dev,
            "the push toggles need an INVERTED binder (checked unless '0') so "
            "they default ON (Phase 5).")


class GetPushFlagsDefaultOnTests(unittest.TestCase):
    """_csvGetPushFlags reads the 3 flat keys and defaults ON."""

    @classmethod
    def setUpClass(cls):
        cls.js = CHAMP_SELECT_JS.read_text(encoding="utf-8")

    def test_reads_three_flat_keys(self):
        body = _fn_body(self.js, "function _csvGetPushFlags(")
        for key in _PUSH_KEYS:
            self.assertIn(key, body,
                f"_csvGetPushFlags must read the flat key {key} (Phase 5).")

    def test_default_on_inverted(self):
        body = _fn_body(self.js, "function _csvGetPushFlags(")
        self.assertIn('!== "0"', body,
            "_csvGetPushFlags must DEFAULT ON (a key is ON unless set to '0') "
            "- Phase 5 flips the item-240 opt-in.")
        self.assertNotRegex(
            body, r"runes:\s*false,\s*spells:\s*false,\s*build:\s*false",
            "the item-240 all-false default must be gone (Phase 5 default-ON).")

    def test_still_returns_the_three_category_shape(self):
        body = _fn_body(self.js, "function _csvGetPushFlags(")
        for cat in ("runes", "spells", "build"):
            self.assertIn(f"{cat}:", body,
                f"_csvGetPushFlags must still return the {cat} flag (Phase 5).")


class InPanelControlRemovedTests(unittest.TestCase):
    """The item-240 in-panel header control is fully removed (regression pin);
    the Phase-6 push plumbing survives."""

    @classmethod
    def setUpClass(cls):
        cls.js = CHAMP_SELECT_JS.read_text(encoding="utf-8")

    def test_push_button_and_render_gone(self):
        self.assertNotIn("csv-builds-push-btn", self.js,
            "the in-panel [PUSH] button must be gone (Phase 5 -> Settings).")
        self.assertNotIn("csv-builds-push-cb", self.js)
        self.assertNotIn("_pushCtrlHtml", self.js,
            "the in-panel push-control render must be gone (Phase 5).")

    def test_old_blob_key_and_setter_gone(self):
        self.assertNotIn("rc-cs-push-flags", self.js,
            "the old blob key is replaced by 3 flat keys (Phase 5).")
        self.assertNotIn("function _csvSetPushFlag(", self.js,
            "_csvSetPushFlag (the in-panel checkbox writer) is gone; the "
            "settings binder writes the flat keys directly (Phase 5).")

    def test_phase6_push_plumbing_intact(self):
        self.assertIn("function _csvPushCategory(", self.js)
        self.assertIn("function _csvPushCheckedCategories(", self.js)


@unittest.skipUnless(_NODE, "node not on PATH")
class GetPushFlagsBehaviorTests(unittest.TestCase):
    """Run the extracted _csvGetPushFlags in node against a fake localStorage to
    prove default-ON + explicit-'0'-off."""

    @classmethod
    def setUpClass(cls):
        fn = _fn_body(CHAMP_SELECT_JS.read_text(encoding="utf-8"),
                      "function _csvGetPushFlags(")
        harness = (
            "const _store = {};\n"
            "const localStorage = {\n"
            "  getItem(k){ return Object.prototype.hasOwnProperty.call(_store,k)?_store[k]:null; },\n"
            "  setItem(k,v){ _store[k]=String(v); },\n"
            "};\n"
            "function _csvGetPushFlags() " + fn + "\n"
            "const empty = _csvGetPushFlags();\n"
            "_store['rc-cs-push-runes']='0';\n"
            "const runesOff = _csvGetPushFlags();\n"
            "_store['rc-cs-push-spells']='1';\n"
            "const spellsOn = _csvGetPushFlags();\n"
            "process.stdout.write(JSON.stringify({empty, runesOff, spellsOn}));\n"
        )
        cls._td = tempfile.mkdtemp()
        h = Path(cls._td) / "pushflags.mjs"
        h.write_text(harness, encoding="utf-8")
        proc = subprocess.run([_NODE, str(h)], capture_output=True,
                              text=True, timeout=30)
        if proc.returncode != 0:
            raise AssertionError(f"node harness failed: {proc.stderr}")
        cls.res = json.loads(proc.stdout)

    def test_empty_store_all_on(self):
        self.assertEqual(self.res["empty"],
                         {"runes": True, "spells": True, "build": True},
            "default-ON: an untouched store pushes all 3 categories (Phase 5).")

    def test_explicit_zero_turns_off_only_that_category(self):
        self.assertFalse(self.res["runesOff"]["runes"])
        self.assertTrue(self.res["runesOff"]["spells"])
        self.assertTrue(self.res["runesOff"]["build"])

    def test_explicit_one_stays_on(self):
        self.assertTrue(self.res["spellsOn"]["spells"])


class AsciiHygieneTests(unittest.TestCase):
    def test_this_file_ascii(self):
        raw = Path(__file__).read_bytes()
        self.assertEqual([b for b in raw if b > 0x7F], [])


if __name__ == "__main__":
    unittest.main()
