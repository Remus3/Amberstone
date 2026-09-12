"""Pin the rune-push wire on champ-select variant-selection change.

When the operator clicks a different SR build path inside the collapsed
sr-collapsed variant (item 178), or a different ARAM/Arena variant row,
the dashboard MUST push the path's runes to the LCU rune page (in
addition to the items + summoners). This was already working end-to-end
before item 189 - but had ZERO test coverage of the variant->rune flow.
This file is the drift guard so a future refactor cannot rip it out.

Coverage:
 - _csvWireBuildVariants in web/js/panels/champ_select.js calls
   _csvApplyLoadout for both legacy single-variant rows AND the new
   item-178 collapsed-path rows.
 - _csvApplyLoadout POSTs /api/loadout/apply with push_runes:true by
   default.
 - The dashboard apply handler invokes the resolver, which surfaces
   rune_cmd, then forwards rune_cmd to the LCU agent via /lcu-cmd.
 - The LCU agent's apply_runes command is whitelisted in
   _LCU_ALLOWED_CMDS at dashboard/routes_loadout.py.
 - The LCU agent has an apply_runes handler in
   tools/lcu_agent.py that PATCHes /lol-perks/v1/currentpage.
 - The resolver returns rune_cmd that overlays per-path runes when the
   colon-form "<variant>:<path-key>" is passed, so different build paths
   produce different keystones (e.g. Jinx Crit -> Lethal Tempo vs Jinx
   Bruiser -> Conqueror).

Mirror of item 186 tests/test_loadout_list_dedup.py drift-guard pattern.
"""

from __future__ import annotations

import re
import sys
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

CHAMP_SELECT_JS = REPO_ROOT / "web" / "js" / "panels" / "champ_select.js"
ROUTES_LOADOUT  = REPO_ROOT / "dashboard" / "routes_loadout.py"
LCU_AGENT    = REPO_ROOT / "tools" / "lcu_agent.py"


class JsVariantClickFiresApplyLoadoutTests(unittest.TestCase):
    """The variant + path-row click handlers must call _csvApplyLoadout."""

    @classmethod
    def setUpClass(cls):
        cls.text = CHAMP_SELECT_JS.read_text(encoding="utf-8")

    def test_wire_build_variants_function_exists(self):
        self.assertIn(
            "function _csvWireBuildVariants(scope)", self.text,
            "missing _csvWireBuildVariants - the variant + path-row "
            "click wiring is the only entry that fires the per-row "
            "rune push.",
        )

    def test_apply_loadout_function_exists(self):
        self.assertIn(
            "function _csvApplyLoadout(", self.text,
            "missing _csvApplyLoadout - the POST /api/loadout/apply "
            "caller that backs the rune push.",
        )

    def test_apply_loadout_defaults_push_runes_true(self):
        # A click that does NOT pass an explicit pushFlags arg must still
        # push runes. Item 240 part-3 generalized _csvApplyLoadout with an
        # optional pushFlags param; the body now reads
        # push_runes: wantRunes, where wantRunes defaults to true when the
        # caller omits pushFlags. Assert BOTH halves so the default-true
        # contract is pinned (regression: silent items-only if the default
        # flips to false or the wantRunes default is dropped).
        body_block_re = re.compile(
            r"const body = \{[^}]*push_runes:\s*wantRunes[^}]*\}",
            re.DOTALL,
        )
        self.assertRegex(
            self.text, body_block_re,
            "_csvApplyLoadout body must set push_runes: wantRunes.",
        )
        self.assertIn(
            "const wantRunes = (pf.push_runes !== undefined) ? !!pf.push_runes : true;",
            self.text,
            "wantRunes must default to true when pushFlags is omitted so a "
            "default click still pushes runes (item 240 part-3).",
        )

    def test_apply_loadout_targets_correct_endpoint(self):
        self.assertIn(
            'fetch("/api/loadout/apply"', self.text,
            "_csvApplyLoadout must POST /api/loadout/apply - the only "
            "endpoint that hits the resolver's rune_cmd path.",
        )

    def test_collapsed_path_click_calls_apply_loadout(self):
        # Item 178 path-row click MUST fire _csvApplyLoadout with the
        # composed "<variant>:<path-key>" form so the resolver picks
        # the right build path's runes. Verify the 3 anchors all exist
        # inside the same _csvWireBuildVariants function body (i.e.
        # between its opening brace and its closing brace).
        wire = self.text
        body_re = re.compile(
            r"function _csvWireBuildVariants\(scope\) \{([\s\S]*?)^\}",
            re.MULTILINE,
        )
        m = body_re.search(wire)
        self.assertIsNotNone(
            m, "_csvWireBuildVariants function body not found")
        body = m.group(1)
        self.assertIn(".csv-build-path-row", body,
            "item-178 collapsed-path row selector missing inside "
            "_csvWireBuildVariants - path clicks won't wire.")
        self.assertIn("const composed = `${variantKey}:${pathKey}`", body,
            "item-178 collapsed-path click MUST compose "
            "`<variant>:<path-key>` so the resolver overlays per-path "
            "runes.")
        self.assertIn("_csvApplyLoadout(champion, composed, mode", body,
            "item-178 collapsed-path click MUST invoke _csvApplyLoadout "
            "with the composed key so the rune-push fires.")

    def test_legacy_row_click_calls_apply_loadout(self):
        # The non-collapsed (ARAM / Arena / experimental) row click also
        # MUST fire _csvApplyLoadout so variant-change pushes runes there
        # too.
        wire = self.text
        body_re = re.compile(
            r"function _csvWireBuildVariants\(scope\) \{([\s\S]*?)^\}",
            re.MULTILINE,
        )
        m = body_re.search(wire)
        self.assertIsNotNone(
            m, "_csvWireBuildVariants function body not found")
        body = m.group(1)
        self.assertIn(".csv-build-row", body,
            "legacy single-variant row selector missing inside "
            "_csvWireBuildVariants.")
        self.assertIn(
            "_csvApplyLoadout(champion, variantKey, mode", body,
            "legacy single-variant row click MUST invoke "
            "_csvApplyLoadout so ARAM/Arena/experimental variant "
            "changes push runes.")


class DashboardAllowlistRuneCmdTests(unittest.TestCase):
    """apply_runes MUST be in the LCU command allowlist."""

    @classmethod
    def setUpClass(cls):
        cls.text = ROUTES_LOADOUT.read_text(encoding="utf-8")

    def test_apply_runes_is_allowed_lcu_cmd(self):
        # Must be inside the _LCU_ALLOWED_CMDS set literal. The set
        # spans multiple lines; just verify the constant exists and
        # contains the apply_runes string literal.
        self.assertIn("_LCU_ALLOWED_CMDS", self.text)
        self.assertIn('"apply_runes"', self.text,
            'apply_runes must be in _LCU_ALLOWED_CMDS at '
            'dashboard/routes_loadout.py - else the vision-server LCU '
            'relay rejects the rune push.')

    def test_apply_handler_threads_push_runes_default_true(self):
        # RM-296d converted this from a SOURCE-TEXT assertion to a BEHAVIOURAL
        # one. It used to assert the literal spelling
        # `push_runes = payload.get("push_runes",   True)`, including that
        # line's incidental double space, so it broke the moment the bare
        # `.get(..., True)` became a coercion that rejects a truthy string
        # "false" - a change that PRESERVED the very default this test names.
        # The old form graded the implementation's characters, not its
        # contract, so it could only ever fail for the wrong reason: green
        # while the defect shipped, red when the defect was fixed.
        from dashboard.routes_loadout import _coerce_push_flag

        for key in ("push_runes", "push_items", "push_summoners"):
            with self.subTest(key=key):
                self.assertIs(
                    _coerce_push_flag({}, key),
                    True,
                    f"_serve_loadout_apply_post must default {key}=True "
                    "when the JS body omits the flag.",
                )
        # Anchor: an omitted key must not be contaminated by a SIBLING key
        # that was supplied, which a naive "any flag present" reading passes.
        self.assertIs(
            _coerce_push_flag({"push_items": False}, "push_runes"),
            True,
            "An omitted push_runes must stay True when a sibling flag is set.",
        )

    def test_apply_handler_enqueues_rune_cmd(self):
        self.assertIn(
            'if push_runes: _enqueue(resolved.get("rune_cmd"))',
            self.text,
            "_serve_loadout_apply_post must forward rune_cmd from the "
            "resolver to the LCU command queue when push_runes is true.",
        )


class LcuAgentRuneHandlerTests(unittest.TestCase):
    """The LCU agent has the apply_runes handler that PATCHes the
    rune page. Live network deploy is a separate operator step."""

    @classmethod
    def setUpClass(cls):
        cls.text = LCU_AGENT.read_text(encoding="utf-8")

    def test_handler_branch_exists(self):
        # The agent dispatches by cmd name. The apply_runes branch is
        # the rune page POST/PATCH chain.
        self.assertIn(
            'if name == "apply_runes":', self.text,
            "tools/lcu_agent.py must carry the apply_runes "
            "dispatch branch.",
        )

    def test_handler_targets_lol_perks_pages(self):
        self.assertIn(
            "/lol-perks/v1/pages", self.text,
            "apply_runes handler must hit /lol-perks/v1/pages (the "
            "canonical rune-page LCU endpoint).",
        )

    def test_handler_sets_current_page(self):
        self.assertIn(
            "/lol-perks/v1/currentpage", self.text,
            "apply_runes handler must PUT /lol-perks/v1/currentpage so "
            "the freshly-created RC page becomes active in-game.",
        )


class ResolverRuneCmdSmokeTests(unittest.TestCase):
    """End-to-end smoke: resolve() returns a distinct rune_cmd per
    build path when the caller passes the colon-form variant key.

    This is the actual proof that selecting a different variant changes
    the rune payload (not just the items)."""

    def test_jinx_sr_collapsed_default_rune_cmd_present(self):
        from coaches.loadout_resolver import resolve
        out = resolve("Jinx", "sr-collapsed", "sr")
        self.assertTrue(out.get("ok"),
            f"resolve(Jinx, sr-collapsed, sr) failed: {out.get('err')}")
        rc = out.get("rune_cmd")
        self.assertIsNotNone(rc,
            "Jinx sr-collapsed default path MUST produce a rune_cmd "
            "(else clicking the default row pushes 0 runes).")
        self.assertEqual(rc.get("cmd"), "apply_runes")
        self.assertTrue(rc.get("perk_ids"),
            "rune_cmd must carry perk_ids - LCU body is empty without it.")

    def test_jinx_sr_collapsed_path_keystones_differ(self):
        """The whole point of item 189: different paths -> different
        runes. If two paths end up with the same keystone, the per-path
        overlay in resolver is broken.

        2026-05-28: item 208 (commit a814020) dropped Jinx's duplicate
        Bruiser/Conqueror path. The live sr-collapsed paths are now
        adc-crit + adc-on-hit (both Lethal Tempo) + auto-sr-primary-carry
        (Press the Attack). Compare Crit vs Carry - they carry genuinely
        distinct keystones (Lethal Tempo 8008 vs Press the Attack 8005),
        which is the case this invariant must protect."""
        from coaches.loadout_resolver import resolve

        # Loadout file has Jinx with >=2 distinct-keystone paths (Crit
        # uses Lethal Tempo, Carry uses Press the Attack per the live
        # data). Pick those two so the keystone genuinely differs.
        crit  = resolve("Jinx", "sr-collapsed:adc-crit",              "sr")
        carry = resolve("Jinx", "sr-collapsed:auto-sr-primary-carry", "sr")
        self.assertTrue(crit.get("ok"),
            f"resolve crit path failed: {crit.get('err')}")
        self.assertTrue(carry.get("ok"),
            f"resolve carry path failed: {carry.get('err')}")
        self.assertIsNotNone(crit.get("rune_cmd"),
            "Crit path missing rune_cmd")
        self.assertIsNotNone(carry.get("rune_cmd"),
            "Carry path missing rune_cmd")
        # The page_name carries the variant+path identity so distinct
        # paths produce distinct LCU page names. This is the durable
        # invariant tested here.
        crit_name  = crit["rune_cmd"].get("page_name", "")
        carry_name = carry["rune_cmd"].get("page_name", "")
        self.assertNotEqual(crit_name, carry_name,
            f"per-path rune_cmd page_name collision: "
            f"crit={crit_name!r} carry={carry_name!r} - "
            "different build paths must produce distinct LCU pages.")
        # primary_id is the tree id (e.g. Precision=8000 vs
        # Domination=8100 vs Resolve=8400). At least one of
        # primary_id / sub_id / perk_ids[0] should differ between
        # distinct archetype paths - else the overlay is a no-op.
        crit_sig = (
            crit["rune_cmd"].get("primary_id"),
            crit["rune_cmd"].get("sub_id"),
            tuple(crit["rune_cmd"].get("perk_ids") or [])[:1],
        )
        carry_sig = (
            carry["rune_cmd"].get("primary_id"),
            carry["rune_cmd"].get("sub_id"),
            tuple(carry["rune_cmd"].get("perk_ids") or [])[:1],
        )
        self.assertNotEqual(crit_sig, carry_sig,
            f"per-path rune_cmd contents identical: crit={crit_sig} "
            f"carry={carry_sig} - the per-path overlay in "
            "coaches/loadout_resolver.py::resolve is not picking up "
            "build_paths[].runes.")


class AsciiHygieneTests(unittest.TestCase):
    def test_this_file_is_ascii_clean(self):
        text = Path(__file__).read_bytes()
        for i, b in enumerate(text):
            self.assertLess(b, 128,
                f"non-ASCII byte 0x{b:02x} at offset {i}")


if __name__ == "__main__":
    unittest.main()
