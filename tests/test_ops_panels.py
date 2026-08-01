"""Guard the three ops panels' data layer (ADDENDUM A concepts 3, 4, 5).

These are the panels whose whole value is telling the truth about drift, so a
test that merely asserted "returns a dict" would defeat them. Each test below
pins the payload against a LIVE source of truth rather than a literal:

- seam map   -> re-derived from the DS server source, then cross-checked
                against the STRANDED_TODAY ledger the DS suite already
                maintains, so the two cannot silently disagree.
- drift strip-> compared to the files that define each fact (current.txt,
                ENGINE_VERSION), never to a hardcoded patch string, which
                would go stale on the next patch bump and pass anyway.
- gated queue-> parsed from docs/LIVE_GAME_GATED_SYNC.md, asserted on
                structure that survives editing rather than on today's counts.
"""
from __future__ import annotations

import unittest
from pathlib import Path

from core import ops_panels

ROOT = Path(__file__).resolve().parent.parent


class SeamMapTests(unittest.TestCase):

    def test_every_seam_reports_all_three_gates(self):
        """A seam missing a gate is the bug this panel exists to show."""
        payload = ops_panels.compute_seam_map()
        self.assertTrue(payload["seams"], "seam map came back empty")
        for row in payload["seams"]:
            for gate in ("flag", "transport", "route"):
                self.assertIn(gate, row, f"{row.get('seam')} missing gate {gate}")
                self.assertIn(
                    row[gate], ("yes", "no", "unmeasured"),
                    f"{row['seam']}.{gate} = {row[gate]!r} is not a known gate state",
                )

    def test_seam_names_agree_with_the_ds_stranded_ledger(self):
        """Cross-check against the ledger the DS suite maintains.

        This is the non-vacuous half: `core/ops_panels.py` re-derives the
        stranded set from source, and the DS suite pins the same set in
        STRANDED_TODAY. If either drifts, this fails - which is the point,
        because a panel that quietly disagrees with the engine's own guard is
        worse than no panel.
        """
        ledger_src = (ROOT / "agents" / "daemon_slayer" / "tests"
                      / "test_stranded_hsp_seam_r197.py").read_text(encoding="utf-8")
        ledger = set(ops_panels._parse_stranded_ledger(ledger_src))
        self.assertTrue(ledger, "could not parse STRANDED_TODAY - the ledger moved")

        reported = {r["seam"] for r in ops_panels.compute_seam_map()["seams"]}
        missing = ledger - reported
        self.assertEqual(
            missing, set(),
            f"seams in the DS ledger but absent from the panel: {sorted(missing)}",
        )

    def test_an_inert_seam_is_visibly_inert(self):
        """Two greens and a red must be representable, not collapsed to one flag."""
        payload = ops_panels.compute_seam_map()
        for row in payload["seams"]:
            if row["flag"] == "yes" and row["route"] == "no":
                self.assertTrue(row["inert"], f"{row['seam']} is inert but not flagged")
        self.assertIn("inert_count", payload)


class DriftStripTests(unittest.TestCase):

    def test_patch_pill_matches_the_file_that_defines_it(self):
        pills = {p["key"]: p for p in ops_panels.compute_drift_strip()["pills"]}
        live = (ROOT / "data" / "daemon_slayer" / "current.txt").read_text(
            encoding="utf-8").strip()
        self.assertEqual(pills["ds_patch"]["value"], live)

    def test_engine_pill_matches_engine_version(self):
        pills = {p["key"]: p for p in ops_panels.compute_drift_strip()["pills"]}
        src = (ROOT / "agents" / "daemon_slayer" / "__init__.py").read_text(
            encoding="utf-8")
        self.assertIn(f'"{pills["engine"]["value"]}"', src)

    def test_every_pill_carries_a_state_and_a_reason(self):
        for pill in ops_panels.compute_drift_strip()["pills"]:
            self.assertIn(pill["state"], ("ok", "amber", "red", "unknown"))
            self.assertTrue(pill["key"] and pill["label"])
            if pill["state"] != "ok":
                self.assertTrue(
                    pill.get("reason"),
                    f"{pill['key']} is {pill['state']} with no reason - an amber "
                    f"pill with no explanation is unactionable",
                )

    def test_disagreement_drives_the_state_not_the_other_way_round(self):
        """Feed two mismatched patch values and require an amber."""
        state = ops_panels._agreement_state(["16.15.1", "16.14.1"])
        self.assertEqual(state, "amber")
        self.assertEqual(ops_panels._agreement_state(["16.15.1", "16.15.1"]), "ok")
        self.assertEqual(ops_panels._agreement_state([]), "unknown")


class GatedQueueTests(unittest.TestCase):

    def test_rows_are_actually_parsed(self):
        """Non-vacuity guard, added after the first version shipped a regex
        that matched NOTHING and still passed every other test in this class.

        The doc uses `- **G2-01**` bullets, not markdown checkboxes, so a
        checkbox regex reconciles at 0 open / 0 done - which reads as "no work
        left" rather than "the parser is broken". Assert real rows exist.
        """
        payload = ops_panels.compute_gated_queue()
        total_rows = payload["total_open"] + payload["total_done"]
        self.assertGreater(
            total_rows, 50,
            f"only {total_rows} gated rows parsed - the row marker moved and "
            f"the counts are silently meaningless",
        )
        self.assertTrue(
            any(b["open"] + b["done"] > 0 for b in payload["buckets"]),
            "every bucket is empty - rows are not being attributed to gates",
        )

    def test_row_count_matches_an_independent_scan_of_the_document(self):
        """Cross-check the parser against a dumb grep of the same file."""
        raw = (ROOT / "docs" / "LIVE_GAME_GATED_SYNC.md").read_text(
            encoding="utf-8", errors="replace")
        independent = len([
            ln for ln in raw.splitlines()
            if ln.lstrip().startswith("- **G") and "**" in ln[4:]
        ])
        payload = ops_panels.compute_gated_queue()
        parsed = payload["total_open"] + payload["total_done"]
        # Rows above GATE 1 (the drain-session preamble) are legitimately not
        # in any bucket, so the parser may see fewer - never more.
        self.assertLessEqual(parsed, independent)
        self.assertGreaterEqual(
            parsed, independent * 0.5,
            f"parser attributed {parsed} of {independent} rows to gates - "
            f"most rows are falling outside every bucket",
        )

    def test_buckets_come_from_the_gate_headings(self):
        payload = ops_panels.compute_gated_queue()
        modes = {b["mode"] for b in payload["buckets"]}
        self.assertTrue(
            modes, "no gate buckets parsed - the doc's ## GATE headings moved")
        for bucket in payload["buckets"]:
            self.assertIsInstance(bucket["open"], int)
            self.assertGreaterEqual(bucket["open"], 0)
            self.assertTrue(bucket["label"])

    def test_total_equals_the_sum_of_buckets(self):
        """A total that does not reconcile is exactly the defect this program
        has now hit twice (119-vs-146, then the LIFT-six mismatch)."""
        payload = ops_panels.compute_gated_queue()
        self.assertEqual(
            payload["total_open"],
            sum(b["open"] for b in payload["buckets"]),
            "gated-queue total does not reconcile against its own buckets",
        )

    def test_missing_document_fails_soft(self):
        payload = ops_panels.compute_gated_queue(path=ROOT / "does_not_exist.md")
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["buckets"], [])
        self.assertEqual(payload["total_open"], 0)


if __name__ == "__main__":
    unittest.main()
