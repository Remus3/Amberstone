"""Item 189 Slice A drift guard: bridge_watcher_install.ps1 -EnableLanes prep.

Pins the THREE moving pieces that have to stay coherent until the operator
grants the frozen-file edit on tools/bridge_watcher_install.ps1:

  1. The canonical 5-LOC diff lives in
     tools/BRIDGE_WATCHER_INSTALL_PS1_LANES_DIFF.md with stable markers
     so a future "Edit 1 of 2" / "Edit 2 of 2" search lands on the right
     hunks.

  2. tools/bridge_watcher.py still exposes the --enable-auto-action-lanes
     argparse flag at L1083 (the consumer the diff is wiring up to). If
     bridge_watcher.py gets refactored and the flag goes away, the diff
     doc is stale and so is the AUTO_ACTION_LANES_GATE_PROBE.md recipe.

  3. tools/bridge_watcher_install.ps1 (FROZEN) still hardcodes the
     original Arguments string at L200 WITHOUT --enable-auto-action-lanes.
     If the operator lands the diff before flipping this guard, the
     "current state" assertion below will fail loudly + we know we can
     drop the guard.

Background per CLAUDE.md item 188 paragraph (j):

    NEW carry: tools/bridge_watcher_install.ps1 -EnableLanes param
    (~5 LOC) prep work owed before Slice G recipe invocation.

Per CLAUDE.md "Frozen files" hard rule, tools/bridge_watcher_install.ps1
must not be edited without explicit user approval. This file stages the
diff content + the regression invariants so the eventual frozen-file edit
is a 1-shot operator-grant + apply step.
"""
from __future__ import annotations

import re
import unittest
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent

_INSTALL_PS1 = _REPO_ROOT / "tools" / "bridge_watcher_install.ps1"
_WATCHER_PY = _REPO_ROOT / "tools" / "bridge_watcher.py"
_DIFF_DOC = _REPO_ROOT / "tools" / "BRIDGE_WATCHER_INSTALL_PS1_LANES_DIFF.md"


class DiffDocPresentTests(unittest.TestCase):
    """The staged diff doc must exist + carry both edit hunks."""

    def test_diff_doc_exists(self) -> None:
        self.assertTrue(
            _DIFF_DOC.is_file(),
            f"expected staged diff doc at {_DIFF_DOC}; it captures the "
            "~5 LOC change to tools/bridge_watcher_install.ps1 (which is "
            "frozen) so operator can apply with one grant.",
        )

    def test_diff_doc_has_both_edit_hunks(self) -> None:
        body = _DIFF_DOC.read_text(encoding="utf-8")
        # Two stable section markers in the doc so future edits land on
        # the right hunks. These strings are the literal H3 headers.
        self.assertIn("### Edit 1 of 2 - param block", body)
        self.assertIn("### Edit 2 of 2 - task XML Arguments string", body)

    def test_diff_doc_proposes_enablelanes_param(self) -> None:
        body = _DIFF_DOC.read_text(encoding="utf-8")
        # Param block must propose `[string]$EnableLanes = ""` shape.
        self.assertRegex(
            body,
            r'\[string\]\$EnableLanes\s*=\s*""',
            "diff doc must propose the canonical "
            '`[string]$EnableLanes = ""` parameter declaration',
        )

    def test_diff_doc_proposes_validate_pattern(self) -> None:
        body = _DIFF_DOC.read_text(encoding="utf-8")
        # Should restrict input to: empty / read / ops / read,ops / ops,read.
        # This prevents silent passthrough of typos to the daemon argparse.
        self.assertIn("ValidatePattern", body)
        self.assertIn("read,ops", body)
        self.assertIn("ops,read", body)

    def test_diff_doc_proposes_enable_auto_action_lanes_flag(self) -> None:
        body = _DIFF_DOC.read_text(encoding="utf-8")
        # The XML edit must wire the new param through to the canonical
        # argparse flag name on the daemon side.
        self.assertIn("--enable-auto-action-lanes", body)

    def test_diff_doc_carries_phase3_gate_reminder(self) -> None:
        body = _DIFF_DOC.read_text(encoding="utf-8")
        # Per docs/AUTO_ACTION_LANES_GATE_PROBE.md the diff is PREP only;
        # operator still has to wait on the N>=50 / >=95% gate before
        # actually flipping a peer.
        self.assertIn("DEFERRED", body)
        self.assertIn("N>=50", body)

    def test_diff_doc_is_ascii_only(self) -> None:
        # CLAUDE.md hard rule: 7-bit ASCII authored content.
        raw = _DIFF_DOC.read_bytes()
        non_ascii = [b for b in raw if b > 0x7F]
        self.assertEqual(
            len(non_ascii),
            0,
            f"diff doc contains {len(non_ascii)} non-ASCII bytes; remove "
            "em-dashes / smart quotes / box-drawing chars per CLAUDE.md "
            '"No em-dashes or en-dashes" hard rule',
        )


class WatcherPyArgparseStableTests(unittest.TestCase):
    """tools/bridge_watcher.py must still expose --enable-auto-action-lanes."""

    def test_argparse_flag_still_defined(self) -> None:
        body = _WATCHER_PY.read_text(encoding="utf-8")
        # Pin both the argparse add + the consumer that splits the
        # comma-separated value into the enabled_lanes set.
        self.assertIn('"--enable-auto-action-lanes"', body)
        self.assertIn("enabled_lanes", body)

    def test_legion_xml_already_uses_the_flag(self) -> None:
        # Sanity cross-check per AUTO_ACTION_LANES_GATE_PROBE.md note:
        # ops/RC-BridgeWatcher.xml (Legion side) already bakes in
        # `--enable-auto-action-lanes read,ops`. If this disappears,
        # something upstream has regressed.
        legion_xml = _REPO_ROOT / "ops" / "RC-BridgeWatcher.xml"
        if not legion_xml.is_file():
            self.skipTest(
                "ops/RC-BridgeWatcher.xml not present in this worktree; "
                "this is informational not load-bearing"
            )
        # Windows scheduled task XMLs are UTF-16 LE w/ BOM per the install
        # script's own comment block. read_text("utf-16") auto-detects from
        # the BOM. Fall back to utf-8 for any future re-encode.
        try:
            body = legion_xml.read_text(encoding="utf-16")
        except (UnicodeError, ValueError):
            body = legion_xml.read_text(encoding="utf-8", errors="replace")
        self.assertIn("--enable-auto-action-lanes", body)


class InstallPs1FrozenStateTests(unittest.TestCase):
    """tools/bridge_watcher_install.ps1 must still be in pre-diff state.

    These assertions flip once the operator grants + lands the diff. At
    that point delete this test class (or relax it) and bump the carry
    in CLAUDE.md from "owed" to "DONE".
    """

    def test_install_ps1_exists(self) -> None:
        self.assertTrue(_INSTALL_PS1.is_file())

    def test_install_ps1_still_lacks_enablelanes_param(self) -> None:
        body = _INSTALL_PS1.read_text(encoding="utf-8")
        # Pre-diff: no $EnableLanes param. Post-diff: this assertion
        # will fail loudly, signaling the carry can be closed.
        self.assertNotRegex(
            body,
            r'\[string\]\$EnableLanes\s*=\s*""',
            "tools/bridge_watcher_install.ps1 now declares $EnableLanes; "
            "item 188 carry (j) is DONE - close this test class and "
            "flip the carry in CLAUDE.md.",
        )

    def test_install_ps1_still_lacks_lanes_flag_in_args(self) -> None:
        body = _INSTALL_PS1.read_text(encoding="utf-8")
        # Pre-diff: hardcoded Arguments string at L200 does NOT mention
        # --enable-auto-action-lanes. Post-diff: this flips.
        self.assertNotIn(
            "--enable-auto-action-lanes",
            body,
            "tools/bridge_watcher_install.ps1 now wires the lanes flag "
            "through; item 188 carry (j) is DONE - close this test "
            "class + flip the carry in CLAUDE.md.",
        )

    def test_install_ps1_param_block_present(self) -> None:
        # The diff lands on a specific anchor: the existing param() block.
        # Make sure the anchor still looks the way the diff doc assumes.
        body = _INSTALL_PS1.read_text(encoding="utf-8")
        self.assertIn('[ValidateSet("gamepc", "peer")]', body)
        self.assertIn('[string]$Node = ""', body)

    def test_install_ps1_arguments_line_present(self) -> None:
        # The second diff hunk lands on the existing <Arguments> line in
        # the embedded task XML. Confirm the anchor.
        body = _INSTALL_PS1.read_text(encoding="utf-8")
        self.assertIn("--node $Node --bridge-url $BridgeUrl", body)
        self.assertIn("--poll 15", body)


class CrossCheckGateProbeDocTests(unittest.TestCase):
    """The recipe doc that motivates this prep work must still be present.

    If docs/AUTO_ACTION_LANES_GATE_PROBE.md gets renamed or deleted, the
    diff staged here is orphaned. Catch that drift.
    """

    def test_gate_probe_doc_present(self) -> None:
        # Item 188 Slice G shipped under this name in this worktree;
        # the brief uses the alternate name AUTO_ACTION_LANES_ENABLE_RECIPE.md.
        # Accept either to be future-proof.
        candidate_a = _REPO_ROOT / "docs" / "AUTO_ACTION_LANES_GATE_PROBE.md"
        candidate_b = _REPO_ROOT / "docs" / "AUTO_ACTION_LANES_ENABLE_RECIPE.md"
        self.assertTrue(
            candidate_a.is_file() or candidate_b.is_file(),
            "expected docs/AUTO_ACTION_LANES_{GATE_PROBE,ENABLE_RECIPE}.md "
            "from item 188 Slice G; if both are gone the prep diff staged "
            "in tools/BRIDGE_WATCHER_INSTALL_PS1_LANES_DIFF.md is orphaned.",
        )


if __name__ == "__main__":
    unittest.main()
