"""RM-143 P3 - runner semantics, especially SKEW vs FAIL.

The single most important property here is that a stale deploy reports SKEW and
NEVER FAIL. A DS bounce is routine (CLAUDE.md warns that a mid-suite bounce
already fakes anchor-mismatch failures), and a gate that goes red during a
normal restart is a gate that gets switched off within a week - the same
reasoning ``tools/stop_claim_gate.py`` used to ship REPORT-ONLY first.

The FAIL path is proven separately and destructively: mutate one line of
``_route_dps`` so the in-process leg diverges from the long-lived :8860 process
and run the tool. Measured 2026-08-01 at ENGINE 1.268.0 with
``level = (... ) + 1``: 3 FAIL / 5 PARITY and ``--arm`` exited 2. That mutation
is not committed; this file covers everything that can be asserted without one.
"""
from __future__ import annotations

import unittest

from tools import ds_parity_run as R


class _StubServer:
    """Stands in for the daemon_slayer server module."""

    def __init__(self, results: dict | None = None) -> None:
        self._POST_ROUTES = {
            "/dps": lambda body: dict(results or {"x": 1.0})
        }


class DiffTests(unittest.TestCase):
    def test_identical_payloads_have_no_diff(self) -> None:
        a = {"dps": 143.7, "items": ["3031"], "nested": {"ok": True}}
        self.assertEqual(R._diff(a, dict(a)), [])

    def test_float_repr_noise_is_tolerated(self) -> None:
        self.assertEqual(R._diff({"v": 0.1 + 0.2}, {"v": 0.3}), [])

    def test_real_divergence_is_reported(self) -> None:
        diffs = R._diff({"v": 143.70493923611113}, {"v": 145.9188732638889})
        self.assertEqual(len(diffs), 1)
        self.assertIn("143.70", diffs[0])

    def test_missing_key_is_reported_on_both_sides(self) -> None:
        self.assertEqual(R._diff({"a": 1}, {}), [".a: missing live"])
        self.assertEqual(R._diff({}, {"a": 1}), [".a: missing in-process"])

    def test_bool_is_not_compared_as_a_number(self) -> None:
        # True == 1 numerically; a seam flipping True -> 1 would be a real
        # payload change and must not be swallowed by the numeric branch.
        self.assertNotEqual(R._diff({"f": True}, {"f": 1}), [])


class SkewTests(unittest.TestCase):
    FIXTURES = [{"id": "f1", "route": "/dps", "body": {"champion": "Ashe"}}]

    def setUp(self) -> None:
        self._orig_setup = R._in_process_setup
        self._orig_live = R._live_engine_version
        R._in_process_setup = lambda: (_StubServer(), "1.268.0")

    def tearDown(self) -> None:
        R._in_process_setup = self._orig_setup
        R._live_engine_version = self._orig_live

    def test_version_mismatch_is_skew_never_fail(self) -> None:
        R._live_engine_version = lambda *a, **k: "1.267.0"
        report = R.run(self.FIXTURES, settle_retry=False)
        self.assertEqual(report["counts"], {"SKEW": 1})
        self.assertNotIn("FAIL", report["counts"])
        self.assertIn("1.267.0", report["results"][0]["detail"])

    def test_unreachable_server_is_skew_never_fail(self) -> None:
        R._live_engine_version = lambda *a, **k: None
        report = R.run(self.FIXTURES, settle_retry=False)
        self.assertEqual(report["counts"], {"SKEW": 1})
        self.assertIn("unreachable", report["results"][0]["detail"])

    def test_matching_versions_do_not_short_circuit_to_skew(self) -> None:
        """Guard against the gate passing itself by always reporting SKEW."""
        R._live_engine_version = lambda *a, **k: "1.268.0"
        orig_post = R._post
        R._post = lambda route, body, timeout=60.0: {"x": 1.0}
        try:
            report = R.run(self.FIXTURES, settle_retry=False)
        finally:
            R._post = orig_post  # restore, never `del` a real module function
        self.assertEqual(report["counts"], {"PARITY": 1})


class FixtureLintTests(unittest.TestCase):
    def test_shipped_fixtures_are_clean(self) -> None:
        self.assertEqual(R.lint_fixtures(R.load_fixtures()), [])

    def test_lint_catches_a_key_the_route_never_reads(self) -> None:
        """The /rank trap: enemy_ad_share is parsed by /ehp, ignored by /rank.

        POSTing it to /rank today returns a plausible carry-scored answer with
        the key silently discarded (reference_ds_probe_rank_vs_archetype_route).
        """
        bad = [{"id": "trap", "route": "/rank",
                "body": {"champion": "Jinx", "enemy_ad_share": 0.7}}]
        problems = R.lint_fixtures(bad)
        self.assertEqual(len(problems), 1)
        self.assertIn("enemy_ad_share", problems[0])
        self.assertIn("/ehp", problems[0])

    def test_every_fixture_carries_a_reason(self) -> None:
        for fx in R.load_fixtures():
            self.assertTrue(fx.get("why", "").strip(),
                            f"fixture {fx['id']} has no why")

    def test_no_ranking_fixture_probes_an_empty_build(self) -> None:
        """reference_ds_probe_empty_build_artifact.

        Probing a ranking route at ``items: []`` under-ranks amp and
        complementary items; that artifact manufactured both headline RM-92
        instances. Allowed only when the fixture says the empty build IS the
        subject.
        """
        for fx in R.load_fixtures():
            if not fx["route"].startswith("/rank"):
                continue
            if fx["body"].get("items") == [] and "empty build" not in fx["why"]:
                self.fail(f"{fx['id']} ranks at items:[] without saying why")


if __name__ == "__main__":
    unittest.main()
