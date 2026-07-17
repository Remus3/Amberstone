"""Champ-select swap-wipe regression: a swap to a BUILD-LESS champion must
still wipe the prior champion's RC-<champ>-<mode>-* item sets.

Bug (2026-07-17): in _csvMaybePushBuildsToLCU the pre-push stale-set wipe
(lcuCmd delete_stale_rc_item_sets, item 188 Slice B) sat AFTER the
`if (!pushUnits.length) return;` guard - and after the even earlier
`!variants.length` guard (a hovered champ with no curated/user variants gets
bare [] from _csvBuildVariantsFor, champ_select.js userRows return). Swapping
to a champ with no builds returned early, so the OLD champ's RC- sets were
never wiped and lingered in the in-game item-shop dropdown.

Latch hazard pinned here too: the push-dedup latch _CSV_LAST_PUSH_KEY keys on
`champ|mode|itemSig` and assumes pushed sets persist. A naive hoist of the
wipe wipes RC-A-* on hover-B, then a hover BACK to A skips the re-push
(unchanged latch key) leaving A's sets deleted. The fix pairs the hoisted
wipe with (1) its own champion|mode wipe latch _CSV_LAST_WIPE_KEY (at most
one wipe per champ change, no per-tick churn) and (2) a push-latch reset so
hover-back re-pushes.

House pattern (mirrors tests/test_csv_push_toggles_phase5.py): structural
pins on the load-bearing wiring + a node round-trip of the extracted
function against a recording lcuCmd stub.
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
_NODE = shutil.which("node")

_WIPE_CMD = "delete_stale_rc_item_sets"
_BATCH_CMD = "apply_item_sets_batch"


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


class SwapWipeStructureTests(unittest.TestCase):
    """Static pins: wipe latch declared, wipe hoisted above the empty-guards,
    push-latch reset present, exactly ONE wipe call site (old post-guard site
    removed), CS-exit clears the wipe latch."""

    @classmethod
    def setUpClass(cls):
        cls.js = CHAMP_SELECT_JS.read_text(encoding="utf-8")
        cls.body = _fn_body(cls.js, "function _csvMaybePushBuildsToLCU(")

    def test_wipe_latch_declared_module_level(self):
        self.assertIn('const _CSV_LAST_WIPE_KEY = { value: "" };', self.js,
            "need a module-level _CSV_LAST_WIPE_KEY beside _CSV_LAST_PUSH_KEY "
            "so hover-scrubbing fires at most one wipe per champ change.")

    def test_wipe_fires_before_the_empty_guards(self):
        wipe_at = self.body.index(_WIPE_CMD)
        push_guard_at = self.body.index("if (!pushUnits.length) return;")
        self.assertLess(wipe_at, push_guard_at,
            "the delete_stale_rc_item_sets wipe must run BEFORE the "
            "pushUnits empty-guard - a build-less swap must still wipe.")
        variants_guard_at = self.body.index("!variants.length) return;")
        self.assertLess(wipe_at, variants_guard_at,
            "the wipe must also run BEFORE the !variants.length guard - "
            "_csvBuildVariantsFor returns bare [] for a hovered champ with "
            "no curated/user variants (userRows), the common build-less shape.")

    def test_push_latch_reset_inside_wipe_branch(self):
        self.assertIn('_CSV_LAST_PUSH_KEY.value = "";', self.body,
            "the wipe must RESET the push latch: it deletes other champs' "
            "RC- sets, so a hover-back to a previously-pushed champ has to "
            "re-push even though its champ|mode|itemSig key is unchanged.")

    def test_exactly_one_wipe_call_site(self):
        # Count the call-shaped literal (not comment mentions): the hoisted
        # wipe replaces the old post-guard call - a leftover duplicate would
        # double-wipe on a normal build-carrying swap.
        self.assertEqual(self.js.count(f'cmd: "{_WIPE_CMD}"'), 1,
            "exactly ONE delete_stale_rc_item_sets lcuCmd call site.")

    def test_cs_exit_clears_wipe_latch(self):
        render = _fn_body(self.js, "export function renderChampSelectView(")
        self.assertIn("_CSV_LAST_WIPE_KEY.value", render,
            "leaving champ select must clear _CSV_LAST_WIPE_KEY (alongside "
            "the _CSV_LAST_RUNE_PUSH clear) so a fresh enter re-asserts.")


@unittest.skipUnless(_NODE, "node not on PATH")
class SwapWipeBehaviorTests(unittest.TestCase):
    """Run the extracted _csvMaybePushBuildsToLCU in node against a recording
    lcuCmd stub and drive the swap scenarios."""

    @classmethod
    def setUpClass(cls):
        fn = _fn_body(CHAMP_SELECT_JS.read_text(encoding="utf-8"),
                      "function _csvMaybePushBuildsToLCU(")
        harness = (
            'const _CSV_LAST_PUSH_KEY = { value: "" };\n'
            'const _CSV_LAST_WIPE_KEY = { value: "" };\n'
            "const _calls = [];\n"
            "function lcuCmd(o) { _calls.push({ cmd: o.cmd,"
            " champ: o.active_champion || null,"
            " nsets: Array.isArray(o.sets) ? o.sets.length : null }); }\n"
            "function _csvMaybePushBuildsToLCU(champion, mode, variants) "
            + fn + "\n"
            "function drain() { const c = _calls.slice();"
            " _calls.length = 0; return c; }\n"
            "const buildsA = [{ key: 'dps', label: 'DPS', build_paths: ["
            "{ key: 'p1', label: 'Crit', item_ids: [3031, 3006, 3094] }] }];\n"
            "const buildsC = [{ key: 'burst', label: 'Burst', build_paths: ["
            "{ key: 'p1', label: 'AP', item_ids: [3089] }] }];\n"
            "const out = {};\n"
            "// 1: normal first push for Ashe.\n"
            "_csvMaybePushBuildsToLCU('Ashe', 'sr', buildsA);\n"
            "out.push_a = drain();\n"
            "// 2: swap to a BUILD-LESS champ - _csvBuildVariantsFor returns\n"
            "// bare [] (userRows) when no curated/user variants exist.\n"
            "_csvMaybePushBuildsToLCU('Yuumi', 'sr', []);\n"
            "out.swap_buildless = drain();\n"
            "// 2b: same build-less champ re-render (hover-scrub tick).\n"
            "_csvMaybePushBuildsToLCU('Yuumi', 'sr', []);\n"
            "out.rerender_buildless = drain();\n"
            "// 3: hover BACK to Ashe with byte-identical variants.\n"
            "_csvMaybePushBuildsToLCU('Ashe', 'sr',"
            " JSON.parse(JSON.stringify(buildsA)));\n"
            "out.hover_back = drain();\n"
            "// 4: normal build-carrying swap to Cassiopeia.\n"
            "_csvMaybePushBuildsToLCU('Cassiopeia', 'sr', buildsC);\n"
            "out.swap_with_builds = drain();\n"
            "// 5: same champ + same items re-render.\n"
            "_csvMaybePushBuildsToLCU('Cassiopeia', 'sr',"
            " JSON.parse(JSON.stringify(buildsC)));\n"
            "out.rerender_same = drain();\n"
            "// 6: pre-hover placeholder (no champion yet) must not wipe.\n"
            "_csvMaybePushBuildsToLCU('-', 'sr', [{ key: 'empty',"
            " label: 'no champion yet', item_ids: [] }]);\n"
            "out.no_champ_placeholder = drain();\n"
            "process.stdout.write(JSON.stringify(out));\n"
        )
        cls._td = tempfile.mkdtemp()
        h = Path(cls._td) / "swapwipe.mjs"
        h.write_text(harness, encoding="utf-8")
        proc = subprocess.run([_NODE, str(h)], capture_output=True,
                              text=True, timeout=30)
        if proc.returncode != 0:
            raise AssertionError(f"node harness failed: {proc.stderr}")
        cls.res = json.loads(proc.stdout)

    @staticmethod
    def _cmds(calls):
        return [c["cmd"] for c in calls]

    def test_first_push_wipes_then_pushes(self):
        cmds = self._cmds(self.res["push_a"])
        self.assertEqual(cmds.count(_WIPE_CMD), 1)
        self.assertEqual(cmds.count(_BATCH_CMD), 1)
        self.assertLess(cmds.index(_WIPE_CMD), cmds.index(_BATCH_CMD),
            "wipe stays PRE-push (item 188 Slice B ordering).")

    def test_swap_to_buildless_champ_fires_scoped_wipe(self):
        calls = self.res["swap_buildless"]
        wipes = [c for c in calls if c["cmd"] == _WIPE_CMD]
        self.assertEqual(len(wipes), 1,
            "swapping to a champ with NO builds must still fire "
            "delete_stale_rc_item_sets - the old champ's RC- sets "
            "otherwise linger in the in-game dropdown.")
        self.assertEqual(wipes[0]["champ"], "Yuumi",
            "the wipe must be scoped to the NEW champion.")
        self.assertEqual(self._cmds(calls).count(_BATCH_CMD), 0,
            "nothing to push for a build-less champ.")

    def test_buildless_rerender_does_not_rewipe(self):
        self.assertEqual(self.res["rerender_buildless"], [],
            "wipe-key dedup: a same-champ re-render (hover-scrub tick) "
            "must not fire a second wipe.")

    def test_hover_back_after_wipe_repushes(self):
        cmds = self._cmds(self.res["hover_back"])
        self.assertEqual(cmds.count(_BATCH_CMD), 1,
            "hover-back after a wipe must RE-PUSH: the swap-wipe deleted "
            "RC-Ashe-* so the champ|mode|itemSig push latch has to have "
            "been reset (naive hoist regression).")

    def test_build_carrying_swap_single_wipe_then_push(self):
        calls = self.res["swap_with_builds"]
        cmds = self._cmds(calls)
        self.assertEqual(cmds.count(_WIPE_CMD), 1,
            "exactly one wipe on a normal build-carrying swap - no "
            "double-wipe from a leftover old call site.")
        self.assertEqual(cmds.count(_BATCH_CMD), 1)
        self.assertLess(cmds.index(_WIPE_CMD), cmds.index(_BATCH_CMD))
        wipe = next(c for c in calls if c["cmd"] == _WIPE_CMD)
        self.assertEqual(wipe["champ"], "Cassiopeia")

    def test_same_champ_same_items_rerender_is_silent(self):
        self.assertEqual(self.res["rerender_same"], [],
            "same champ + same itemSig re-render fires neither wipe nor "
            "push (both latches hold).")

    def test_no_champ_placeholder_does_not_wipe(self):
        self.assertEqual(self.res["no_champ_placeholder"], [],
            "the pre-hover 'empty' placeholder (champion sentinel '-') "
            "must NOT wipe - it would delete every real champ's RC- sets "
            "on each pre-hover champ-select tick.")


class AsciiHygieneTests(unittest.TestCase):
    def test_this_file_ascii(self):
        raw = Path(__file__).read_bytes()
        self.assertEqual([b for b in raw if b > 0x7F], [])


if __name__ == "__main__":
    unittest.main()
