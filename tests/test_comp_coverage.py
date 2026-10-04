"""Property pack for core.comp_coverage (Y-09 / RM-533, external reference S).

Every property runs over the REAL current-patch roster: the names come from
core.aram_comp_verdict._load_index(), which reads
data/daemon_slayer/<current.txt>/champions.json (tracked in git). The
corpus is asserted NON-EMPTY first so an empty enumeration can never pass the
pack vacuously.

Comp FACTS only - nothing here (or in the module) predicts a game outcome.
"""
from __future__ import annotations

import copy
import random
import unittest
from unittest import mock

from core import aram_comp_verdict as cv
from core import comp_coverage as cc

_SEED = 533  # RM-533; fixed so the sampled teams are reproducible.
_N_TEAMS = 200


def _roster() -> list[str]:
    return sorted(c["name"] for c in cv._load_index().values())


def _pct(res: dict) -> float:
    return 0.0 if res["coverage_pct"] is None else res["coverage_pct"]


class CorpusTests(unittest.TestCase):

    def test_corpus_non_empty_and_resolves(self):
        names = _roster()
        # 16.18.1 carries 173 champions; anything under 150 means the data
        # path broke, not that the roster shrank.
        self.assertGreaterEqual(len(names), 150)
        res = cc.compute_team_coverage(names, mode_key="sr")
        self.assertEqual(res["n"], len(names))
        self.assertEqual(res["unresolved"], [])

    def test_every_axis_is_live_on_the_roster(self):
        """Positive control for the derivation: each COVER axis is held by at
        least one champion and by NOT every champion, same for each VULN
        axis. A broken DS import or a dead threshold turns this red."""
        names = _roster()
        holders = {a: 0 for a in cc.COVER_AXES}
        weak = {a: 0 for a in cc.VULN_AXES}
        for name in names:
            prof = cc.champion_profile(name)
            self.assertIsNotNone(prof, name)
            for a in prof["cover"]:
                holders[a] += 1
            for a in prof["vuln"]:
                weak[a] += 1
        for a, n in holders.items():
            self.assertGreater(n, 0, f"cover axis {a} held by nobody")
            self.assertLess(n, len(names), f"cover axis {a} held by everyone")
        for a, n in weak.items():
            self.assertGreater(n, 0, f"vuln axis {a} hits nobody")
            self.assertLess(n, len(names), f"vuln axis {a} hits everyone")


class PropertyTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        names = _roster()
        rng = random.Random(_SEED)
        cls.teams = [rng.sample(names, 5) for _ in range(_N_TEAMS)]

    def test_sampled_corpus_non_empty(self):
        self.assertEqual(len(self.teams), _N_TEAMS)
        self.assertTrue(all(len(t) == 5 for t in self.teams))

    def test_superset_coverage_ge_subset(self):
        checked = 0
        for team in self.teams:
            prev = cc.compute_team_coverage([], mode_key="sr")
            for k in range(1, len(team) + 1):
                cur = cc.compute_team_coverage(team[:k], mode_key="sr")
                self.assertGreaterEqual(_pct(cur), _pct(prev), team[:k])
                self.assertTrue(set(prev["covered"]) <= set(cur["covered"]))
                prev_shared = {v["axis"] for v in prev["shared_vulns"]}
                cur_shared = {v["axis"] for v in cur["shared_vulns"]}
                self.assertTrue(prev_shared <= cur_shared)
                prev = cur
                checked += 1
        self.assertEqual(checked, _N_TEAMS * 5)

    def test_shared_vulns_bounded(self):
        for team in self.teams:
            for mode in ("sr", "aram", "arena"):
                res = cc.compute_team_coverage(team, mode_key=mode)
                sv = res["shared_vulns"]
                self.assertGreaterEqual(len(sv), 0)
                self.assertLessEqual(len(sv), len(cc.VULN_AXES))
                for row in sv:
                    self.assertIn(row["axis"], cc.VULN_AXES)
                    self.assertGreaterEqual(len(row["members"]), 2)
                    self.assertTrue(set(row["members"]) <= set(team))

    def test_partition_and_denominator(self):
        for team in self.teams[:50]:
            for mode in ("sr", "aram", "arena", "jade"):
                res = cc.compute_team_coverage(team, mode_key=mode)
                axes = cc.cover_axes_for_mode(mode)
                self.assertEqual(sorted(res["covered"] + res["missing"]), sorted(axes))
                self.assertFalse(set(res["covered"]) & set(res["missing"]))
                self.assertAlmostEqual(
                    res["coverage_pct"],
                    round(100.0 * len(res["covered"]) / len(axes), 1),
                )

    def test_deterministic_and_order_free(self):
        for team in self.teams[:50]:
            a = cc.compute_team_coverage(team, mode_key="aram")
            b = cc.compute_team_coverage(list(team), mode_key="aram")
            self.assertEqual(a, b)
            c = cc.compute_team_coverage(list(reversed(team)), mode_key="aram")
            self.assertEqual(a, c)

    def test_no_lookup_mutation(self):
        before = copy.deepcopy(cv._load_index())
        for team in self.teams:
            cc.compute_team_coverage(team, mode_key="sr")
            cc.compute_enemy_coverage(team, mode_key="sr")
        self.assertEqual(cv._load_index(), before)


class FailSoftTests(unittest.TestCase):

    def test_junk_names_skipped_not_crashed(self):
        team = ["Malphite", "Lux", "Jinx"]
        base = cc.compute_team_coverage(team, mode_key="sr")
        junk = ["", "__class__", None, 123, "NotAChampion", "__init__"]
        res = cc.compute_team_coverage(junk + team, mode_key="sr")
        self.assertEqual(res["n"], 3)
        for k in ("coverage_pct", "covered", "missing", "shared_vulns"):
            self.assertEqual(res[k], base[k])
        self.assertIsNone(cc.champion_profile(""))
        self.assertIsNone(cc.champion_profile("__class__"))

    def test_non_list_inputs(self):
        for bad in (None, "Malphite", 5, {"a": 1}):
            res = cc.compute_team_coverage(bad, mode_key="sr")
            self.assertEqual(res["n"], 0)
            self.assertIsNone(res["coverage_pct"])

    def test_empty_team_is_unknown_not_zero(self):
        res = cc.compute_team_coverage([], mode_key="sr")
        self.assertIsNone(res["coverage_pct"])
        self.assertEqual(res["covered"], [])
        self.assertEqual(res["shared_vulns"], [])


class ModeTests(unittest.TestCase):

    def test_arena_has_no_waveclear_axis(self):
        self.assertNotIn("waveclear", cc.cover_axes_for_mode("arena"))
        self.assertEqual(len(cc.cover_axes_for_mode("arena")), len(cc.COVER_AXES) - 1)

    def test_tft_is_not_applicable(self):
        self.assertEqual(cc.cover_axes_for_mode("tft"), ())
        self.assertIsNone(cc.compute_coverage(["Lux"], ["Jinx"], mode_key="tft"))

    def test_unknown_mode_falls_back_to_full_list(self):
        self.assertEqual(cc.cover_axes_for_mode(None), cc.COVER_AXES)
        self.assertEqual(cc.cover_axes_for_mode("whatever"), cc.COVER_AXES)


class FactTests(unittest.TestCase):
    """Spot facts read from the 16.18.1 data + DS registries (not outcomes)."""

    def test_known_kits(self):
        mal = cc.champion_profile("Malphite")
        self.assertIn("frontline", mal["cover"])
        self.assertIn("hard_cc", mal["cover"])
        self.assertIn("anti_heal", cc.champion_profile("Katarina")["cover"])
        vay = cc.champion_profile("Vayne")
        self.assertIn("true", vay["cover"])
        self.assertIn("tank_shred", vay["cover"])
        self.assertIn("poke", cc.champion_profile("Xerath")["cover"])
        self.assertIn("weak_to_dive", cc.champion_profile("Xerath")["vuln"])
        self.assertIn("weak_to_grievous", cc.champion_profile("Soraka")["vuln"])


class EnemyAndContextTests(unittest.TestCase):

    def test_enemy_carries_damage_profile(self):
        res = cc.compute_enemy_coverage(["Malphite", "Lux", "Jinx"], mode_key="sr")
        self.assertIn("damage_profile", res)
        self.assertIn("coverage_pct", res)

    def test_both_teams(self):
        res = cc.compute_coverage(["Malphite", "Lux"], ["Jinx", "Zed"], mode_key="aram")
        self.assertEqual(res["mode_key"], "aram")
        self.assertIn("ours", res)
        self.assertIn("enemy", res)
        self.assertIn("damage_profile", res["enemy"])

    def test_from_team_context(self):
        tc = {
            "allies": [{"locked_champion": "Malphite"}, {"locked_champion": ""}],
            "enemies": [{"locked_champion": "Lux"}, "junk"],
            "queue_id": 450,
        }
        res = cc.coverage_from_team_context(tc)
        self.assertEqual(res["mode_key"], "aram")
        self.assertEqual(res["ours"]["n"], 1)
        self.assertEqual(res["enemy"]["n"], 1)

    def test_from_team_context_fail_soft(self):
        for bad in (None, [], "x", {"allies": "nope"}, {"queue_id": "zz"}):
            cc.coverage_from_team_context(bad)  # must not raise
        with mock.patch.object(cc, "compute_coverage", side_effect=RuntimeError("boom")):
            self.assertIsNone(cc.coverage_from_team_context({"allies": [], "queue_id": 450}))


class StateBuilderSpliceTests(unittest.TestCase):

    def _build(self, tc):
        from dashboard import _state_builder as sb
        with mock.patch.object(sb, "read_json", return_value={"alive": True, "pid": 1, "mode": "client"}), \
                mock.patch.object(sb, "lcu_summary", return_value={}), \
                mock.patch.object(sb, "liveclient_summary", return_value={}), \
                mock.patch.object(sb, "get_team_context", return_value=tc), \
                mock.patch.object(sb, "validate_coaching_payload", lambda *_a, **_k: None):
            return sb.build_state()

    def test_coverage_spliced_and_cache_untouched(self):
        tc = {
            "allies": [{"locked_champion": "Malphite"}, {"locked_champion": "Lux"}],
            "enemies": [{"locked_champion": "Jinx"}],
            "queue_id": 450,
        }
        snap = copy.deepcopy(tc)
        st = self._build(tc)
        out = st["coach"]["team_context"]
        self.assertIn("coverage", out)
        self.assertEqual(out["coverage"]["mode_key"], "aram")
        self.assertEqual(out["allies"], snap["allies"])
        self.assertEqual(tc, snap)  # route cache dict not mutated

    def test_cold_cache_stays_none(self):
        self.assertIsNone(self._build(None)["coach"]["team_context"])

    def test_scorer_failure_never_raises_into_state(self):
        tc = {"allies": [{"locked_champion": "Lux"}], "enemies": [], "queue_id": 450}
        with mock.patch("core.comp_coverage.compute_coverage", side_effect=RuntimeError("x")):
            st = self._build(tc)
        out = st["coach"]["team_context"]
        self.assertIsNone(out["coverage"])
        self.assertEqual(out["queue_id"], 450)


if __name__ == "__main__":
    unittest.main()
