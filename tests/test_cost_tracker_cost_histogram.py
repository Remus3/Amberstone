"""Tests for the per-call cost histogram wired into cost_tracker.record_call.

BACKLOG: "Per-call cost histogram: track median/p95 cost per lane in
Prometheus." The histogram must be observed exactly once per record_call,
labelled by model + purpose, with the call's USD cost as the value, at the
same chokepoint as the existing counters, and it must render at /metrics
(declared at source-module scope + eager-imported by routes_metrics).
"""
import tempfile
import unittest
from pathlib import Path

from core import cost_tracker
from core.prom_metrics import render_all


def _hist_entry(model, purpose):
    """Internal [cumulative_bucket_counts, sum, count] for one label set,
    or None if nothing observed yet."""
    h = cost_tracker._M_COACH_COST_PER_CALL
    return h._values.get((str(model), str(purpose)))


class CostHistogramTests(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.mkdtemp()
        self.tracker = cost_tracker.CostTracker(
            config_provider=lambda: {}, spend_dir=Path(self._td))

    def test_observed_once_per_record_call_with_labels_and_value(self):
        before = _hist_entry("claude-haiku-4-5-20251001", "aram_coach")
        before_count = before[2] if before else 0
        before_sum = before[1] if before else 0.0

        out = self.tracker.record_call(
            model="claude-haiku-4-5-20251001",
            input_tokens=1000, output_tokens=500,
            purpose="aram_coach",
        )

        after = _hist_entry("claude-haiku-4-5-20251001", "aram_coach")
        self.assertIsNotNone(after)
        # exactly one new observation on this lane
        self.assertEqual(after[2], before_count + 1)
        # the observed value is the call's USD cost (sum delta == cost)
        self.assertAlmostEqual(after[1] - before_sum, out["usd"], places=9)
        # haiku 1000 in @0.80/1M + 500 out @4.00/1M = 0.0008 + 0.002 = 0.0028
        self.assertAlmostEqual(out["usd"], 0.0028, places=9)

    def test_zero_cost_call_still_observed(self):
        # A 0-token call costs $0 but must still land in the histogram so
        # p50/p95 are over the full call population.
        before = _hist_entry("claude-sonnet-4-6", "vision_relay")
        before_count = before[2] if before else 0
        self.tracker.record_call(model="claude-sonnet-4-6",
                                 purpose="vision_relay")
        after = _hist_entry("claude-sonnet-4-6", "vision_relay")
        self.assertIsNotNone(after)
        self.assertEqual(after[2], before_count + 1)

    def test_unspecified_purpose_uses_same_label_as_counter(self):
        self.tracker.record_call(model="claude-sonnet-4-6",
                                 input_tokens=10, purpose="")
        # counter uses "_unspecified" for an empty purpose; the histogram
        # must use the SAME label so the two line up per lane.
        self.assertIsNotNone(_hist_entry("claude-sonnet-4-6", "_unspecified"))

    def test_renders_at_metrics_with_buckets_sum_count(self):
        self.tracker.record_call(model="claude-haiku-4-5-20251001",
                                 input_tokens=2000, output_tokens=2000,
                                 purpose="sr_coach")
        body = render_all()
        self.assertIn("# TYPE rc_coach_cost_usd_per_call histogram", body)
        self.assertIn('rc_coach_cost_usd_per_call_bucket{', body)
        self.assertIn('purpose="sr_coach"', body)
        self.assertIn("rc_coach_cost_usd_per_call_sum{", body)
        self.assertIn("rc_coach_cost_usd_per_call_count{", body)
        self.assertIn('le="+Inf"', body)

    def test_buckets_are_the_usd_scale(self):
        self.assertEqual(
            cost_tracker._M_COACH_COST_PER_CALL.buckets,
            (0.0005, 0.001, 0.005, 0.01, 0.05, 0.1, 0.5, 1.0),
        )

    def test_routes_metrics_eager_imports_cost_tracker(self):
        # The histogram only renders if routes_metrics eager-imports the
        # source module (prom metrics declared at module scope).
        src = (Path(__file__).parent.parent
               / "dashboard" / "routes_metrics.py").read_text(
            encoding="utf-8")
        self.assertIn("import core.cost_tracker", src)


if __name__ == "__main__":
    unittest.main()
