"""tests/test_death_recap_rm608.py - RM-608 / X-08 estimated death recap, Tier A.

All fixtures are synthetic and name-scrubbed: the player names below are
invented placeholders, never real Riot IDs.
"""
from __future__ import annotations

import json
import pathlib
import shutil
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core import death_recap as dr  # noqa: E402
from core import liveclient_cache  # noqa: E402
from core.liveclient_cache import Snapshot  # noqa: E402


def _player(name, champ, team, level=11, items=()):
    return {
        "summonerName": name,
        "riotIdGameName": name,
        "riotId": name + "#TST1",
        "championName": champ,
        "team": team,
        "level": level,
        "items": [{"itemID": i} for i in items],
    }


def _game(events=(), game_time=900.0, mode="CLASSIC"):
    return {
        "activePlayer": {
            "summonerName": "SelfPlayer",
            "riotIdGameName": "SelfPlayer",
            "riotId": "SelfPlayer#TST1",
            "level": 10,
            "championStats": {"armor": 60.0, "magicResist": 40.0, "maxHealth": 1800.0},
        },
        "allPlayers": [
            _player("SelfPlayer", "Ashe", "ORDER", 10, (3031,)),
            _player("AllyOne", "Leona", "ORDER"),
            _player("FoeOne", "Zed", "CHAOS", 12, (3142, 6692)),
            _player("FoeTwo", "Lux", "CHAOS", 11, (6655,)),
            _player("FoeThree", "Darius", "CHAOS", 13, (6631,)),
        ],
        "events": {"Events": list(events)},
        "gameData": {"gameTime": game_time, "gameMode": mode},
    }


def _kill(eid, victim, killer, assisters=(), t=600.0):
    return {"EventID": eid, "EventName": "ChampionKill", "EventTime": t,
            "VictimName": victim, "KillerName": killer, "Assisters": list(assisters)}


def _burst(rows):
    return {"per_cast": [{"damage_type": dt, "final_damage": dmg} for dt, dmg in rows],
            "total_burst_damage": sum(d for _, d in rows)}


class BuildRecapTests(unittest.TestCase):
    def test_synthetic_kill_shares_sum_to_one_and_estimated(self):
        ev = _kill(7, "SelfPlayer", "FoeOne", ["FoeTwo"])
        data = _game([ev])
        profiles = {
            "Zed": _burst([("PHYSICAL", 600.0), ("TRUE", 100.0)]),
            "Lux": _burst([("MAGIC", 300.0)]),
        }
        row = dr.build_recap(ev, data, profiles, dr.our_resists_from(data))
        self.assertIsNotNone(row)
        self.assertEqual(row["provenance"], "estimated")
        s = row["shares"]
        self.assertAlmostEqual(s["physical"] + s["magic"] + s["true"], 1.0, places=9)
        self.assertAlmostEqual(s["physical"], 0.6, places=3)
        self.assertAlmostEqual(s["magic"], 0.3, places=3)
        self.assertAlmostEqual(s["true"], 0.1, places=3)
        self.assertEqual(row["basis"], "ds")
        champs = [c["champion"] for c in row["contributors"]]
        self.assertEqual(champs, ["Zed", "Lux"])
        killer = row["contributors"][0]
        self.assertEqual(killer["role"], "killer")
        self.assertEqual(killer["level"], 12)
        self.assertEqual(killer["items"], ["3142", "6692"])
        # public-repo hygiene: no player names are persisted in the row
        self.assertNotIn("FoeOne", json.dumps(row))
        self.assertNotIn("SelfPlayer", json.dumps(row))

    def test_killer_name_as_champion_name_rm673(self):
        ev = _kill(3, "SelfPlayer", "Darius", [])
        data = _game([ev])
        row = dr.build_recap(ev, data, {}, dr.our_resists_from(data))
        self.assertIsNotNone(row)
        self.assertEqual(row["contributors"][0]["champion"], "Darius")
        self.assertEqual(row["contributors"][0]["level"], 13)

    def test_full_riot_id_victim_is_self(self):
        ev = _kill(3, "SelfPlayer#TST1", "FoeOne#TST1", [])
        data = _game([ev])
        row = dr.build_recap(ev, data, {}, dr.our_resists_from(data))
        self.assertIsNotNone(row)
        self.assertEqual(row["contributors"][0]["champion"], "Zed")

    def test_non_self_kill_ignored(self):
        ev = _kill(4, "AllyOne", "FoeOne", ["FoeTwo"])
        data = _game([ev])
        self.assertIsNone(dr.build_recap(ev, data, {}, dr.our_resists_from(data)))

    def test_non_kill_event_ignored(self):
        ev = {"EventID": 1, "EventName": "DragonKill", "KillerName": "FoeOne"}
        self.assertIsNone(dr.build_recap(ev, _game([ev]), {}, {}))

    def test_local_fallback_when_no_ds_profile(self):
        ev = _kill(5, "SelfPlayer", "FoeOne", ["FoeTwo"])
        data = _game([ev])
        row = dr.build_recap(ev, data, {}, dr.our_resists_from(data))
        self.assertEqual(row["basis"], "local")
        s = row["shares"]
        self.assertAlmostEqual(s["physical"] + s["magic"] + s["true"], 1.0, places=9)
        self.assertEqual(row["provenance"], "estimated")
        for c in row["contributors"]:
            self.assertEqual(c["source"], "local_ddragon")
        split = {c["champion"]: c["split"] for c in row["contributors"]}
        # documented local fallback = DDragon info.attack / info.magic
        self.assertGreater(split["Zed"]["physical"], split["Zed"]["magic"])
        self.assertGreater(split["Lux"]["magic"], split["Lux"]["physical"])
        # killer weighted above assister (our own fixed weights)
        self.assertGreater(row["contributors"][0]["weight"], row["contributors"][1]["weight"])

    def test_unusable_ds_profile_falls_back_per_contributor(self):
        ev = _kill(5, "SelfPlayer", "FoeOne", ["FoeTwo"])
        data = _game([ev])
        profiles = {"Zed": _burst([("PHYSICAL", 500.0)]), "Lux": {"per_cast": []}}
        row = dr.build_recap(ev, data, profiles, dr.our_resists_from(data))
        self.assertEqual(row["basis"], "mixed")
        srcs = {c["champion"]: c["source"] for c in row["contributors"]}
        self.assertEqual(srcs, {"Zed": "ds_burst", "Lux": "local_ddragon"})
        s = row["shares"]
        self.assertAlmostEqual(s["physical"] + s["magic"] + s["true"], 1.0, places=9)

    def test_structure_kill_has_no_shares(self):
        ev = _kill(6, "SelfPlayer", "Turret_T2_C_05_A", [])
        data = _game([ev])
        row = dr.build_recap(ev, data, {}, dr.our_resists_from(data))
        self.assertIsNotNone(row)
        self.assertIsNone(row["shares"])
        self.assertEqual(row["basis"], "none")
        self.assertEqual(row["provenance"], "estimated")

    def test_ds_split_parses_typed_rows_only(self):
        split = dr.split_from_ds_profile(
            _burst([("PHYSICAL", 50.0), ("magical", 50.0), (None, 999.0)]))
        self.assertIsNotNone(split)
        self.assertAlmostEqual(split[0], 0.5)
        self.assertAlmostEqual(split[1], 0.5)
        self.assertIsNone(dr.split_from_ds_profile({"per_cast": [{"damage_type": None,
                                                                   "final_damage": 10}]}))
        self.assertIsNone(dr.split_from_ds_profile(None))


class DsFetchFailSoftTests(unittest.TestCase):
    def _contribs(self):
        ev = _kill(5, "SelfPlayer", "FoeOne", ["FoeTwo"])
        data = _game([ev])
        return dr.resolve_contributors(ev, data), dr.our_resists_from(data)

    def test_ds_raising_returns_empty_without_raising(self):
        contribs, res = self._contribs()

        def boom(*a, **k):
            raise RuntimeError("engine exploded")
        out = dr.fetch_ds_profiles(contribs, res, "SR", burst_fn=boom, up_fn=lambda: True)
        self.assertEqual(out, {})

    def test_ds_down_skips_calls(self):
        contribs, res = self._contribs()
        calls = []
        out = dr.fetch_ds_profiles(contribs, res, "SR",
                                   burst_fn=lambda *a, **k: calls.append(1),
                                   up_fn=lambda: False)
        self.assertEqual(out, {})
        self.assertEqual(calls, [])

    def test_ds_call_uses_our_resists_and_short_timeout(self):
        contribs, res = self._contribs()
        seen = []

        def fake(champ, **kw):
            seen.append((champ, kw))
            return _burst([("PHYSICAL", 10.0)])
        out = dr.fetch_ds_profiles(contribs, res, "ARAM", burst_fn=fake, up_fn=lambda: True)
        self.assertEqual(set(out), {"Zed", "Lux"})
        champ, kw = seen[0]
        self.assertEqual(kw["target_armor"], 60.0)
        self.assertEqual(kw["target_mr"], 40.0)
        self.assertEqual(kw["mode"], "ARAM")
        self.assertLessEqual(kw["timeout"], 0.5)

    def test_ds_none_result_degrades_to_local(self):
        ev = _kill(5, "SelfPlayer", "FoeOne", [])
        data = _game([ev])
        res = dr.our_resists_from(data)
        profiles = dr.fetch_ds_profiles(dr.resolve_contributors(ev, data), res, "SR",
                                        burst_fn=lambda *a, **k: None, up_fn=lambda: True)
        row = dr.build_recap(ev, data, profiles, res)
        self.assertEqual(row["basis"], "local")

    def test_process_job_never_raises(self):
        ev = _kill(5, "SelfPlayer", "FoeOne", [])

        def boom(*a, **k):
            raise RuntimeError("x")
        tmp = pathlib.Path(tempfile.mkdtemp(prefix="recap_"))
        try:
            row = dr.process_kill(ev, _game([ev]), path=tmp / "r.jsonl",
                                  burst_fn=boom, up_fn=lambda: True)
            self.assertIsNotNone(row)
            self.assertEqual(len(dr.read_rows(tmp / "r.jsonl")), 1)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


class TapTests(unittest.TestCase):
    def setUp(self):
        self.jobs = []
        self.tap = dr.DeathRecapTap(dispatch=lambda ev, data: self.jobs.append(ev["EventID"]))

    def test_first_snapshot_does_not_backfill(self):
        self.tap.on_snapshot(Snapshot(data=_game([_kill(1, "SelfPlayer", "FoeOne")])))
        self.assertEqual(self.jobs, [])

    def test_new_self_death_dispatched_once(self):
        e0 = {"EventID": 0, "EventName": "GameStart"}
        self.tap.on_snapshot(Snapshot(data=_game([e0])))
        snap = Snapshot(data=_game([e0, _kill(1, "AllyOne", "FoeOne"),
                                    _kill(2, "SelfPlayer", "FoeOne")]))
        self.tap.on_snapshot(snap)
        self.tap.on_snapshot(snap)
        self.assertEqual(self.jobs, [2])

    def test_new_game_resets_high_water(self):
        self.tap.on_snapshot(Snapshot(data=_game([_kill(40, "AllyOne", "FoeOne")], 1500.0)))
        self.tap.on_snapshot(Snapshot(data=_game([{"EventID": 0, "EventName": "GameStart"},
                                                  _kill(1, "SelfPlayer", "FoeOne")], 60.0)))
        self.assertEqual(self.jobs, [1])

    def test_empty_snapshot_is_inert(self):
        self.tap.on_snapshot(Snapshot(data=None))
        self.tap.on_snapshot(None)
        self.assertEqual(self.jobs, [])


class FlagTests(unittest.TestCase):
    def setUp(self):
        liveclient_cache.clear_listeners()
        dr._reset_for_tests()

    def tearDown(self):
        liveclient_cache.clear_listeners()
        dr._reset_for_tests()

    def test_flag_default_off(self):
        self.assertFalse(dr.is_enabled({}))
        self.assertFalse(dr.is_enabled({"RC_DEATH_RECAP": "0"}))
        self.assertTrue(dr.is_enabled({"RC_DEATH_RECAP": "1"}))

    def test_flag_off_installs_nothing(self):
        self.assertFalse(dr.install_if_enabled({}))
        self.assertEqual(liveclient_cache._listeners, [])

    def test_optional_taps_inert_when_flag_off(self):
        import os
        old = os.environ.pop("RC_DEATH_RECAP", None)
        try:
            liveclient_cache._install_optional_taps()
            self.assertNotIn(dr.on_liveclient_snapshot, liveclient_cache._listeners)
        finally:
            if old is not None:
                os.environ["RC_DEATH_RECAP"] = old

    def test_flag_on_installs_listener_once(self):
        self.assertTrue(dr.install_if_enabled({"RC_DEATH_RECAP": "1"}))
        self.assertFalse(dr.install_if_enabled({"RC_DEATH_RECAP": "1"}))
        self.assertEqual(liveclient_cache._listeners.count(dr.on_liveclient_snapshot), 1)

    def test_optional_taps_installs_when_flag_on(self):
        import os
        old = os.environ.get("RC_DEATH_RECAP")
        os.environ["RC_DEATH_RECAP"] = "1"
        try:
            liveclient_cache._install_optional_taps()
            self.assertIn(dr.on_liveclient_snapshot, liveclient_cache._listeners)
        finally:
            if old is None:
                os.environ.pop("RC_DEATH_RECAP", None)
            else:
                os.environ["RC_DEATH_RECAP"] = old


class PersistAndAggregateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp(prefix="recap_"))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _rows(self):
        ev = _kill(7, "SelfPlayer", "FoeOne", ["FoeTwo"])
        data = _game([ev])
        r1 = dr.build_recap(ev, data, {"Zed": _burst([("PHYSICAL", 900.0)]),
                                       "Lux": _burst([("MAGIC", 100.0)])},
                            dr.our_resists_from(data))
        ev2 = _kill(9, "SelfPlayer", "Lux", [])
        r2 = dr.build_recap(ev2, data, {"Lux": _burst([("MAGIC", 400.0)])},
                            dr.our_resists_from(data))
        return r1, r2

    def test_append_and_read_roundtrip_skips_torn_line(self):
        p = self.tmp / "recaps.jsonl"
        r1, r2 = self._rows()
        dr.append_row(r1, p)
        dr.append_row(r2, p)
        with open(p, "a", encoding="utf-8", newline="\n") as f:
            f.write('{"torn": ')
        self.assertEqual(len(dr.read_rows(p)), 2)
        self.assertEqual(dr.read_rows(self.tmp / "missing.jsonl"), [])

    def test_postmortem_aggregation_picks_rows_up(self):
        from scripts.postmortem_analyze import aggregate_death_recaps
        r1, r2 = self._rows()
        agg = aggregate_death_recaps([r1, r2])
        self.assertEqual(agg["provenance"], "estimated")
        self.assertEqual(agg["total_recaps"], 2)
        ms = agg["mean_shares"]
        self.assertAlmostEqual(ms["physical"] + ms["magic"] + ms["true"], 1.0, places=3)
        self.assertEqual(agg["dominant_type_counts"]["magic"], 1)
        self.assertEqual(agg["dominant_type_counts"]["physical"], 1)
        self.assertEqual(agg["top_killer_champions"][0]["count"], 1)

    def test_aggregation_counts_only_estimated_rows(self):
        from scripts.postmortem_analyze import aggregate_death_recaps
        r1, r2 = self._rows()
        bogus = dict(r2, provenance="measured")
        agg = aggregate_death_recaps([r1, bogus])
        self.assertEqual(agg["total_recaps"], 1)

    def test_loader_rejects_unlabelled_section(self):
        from core.death_patterns_loader import damage_recap_summary
        p = self.tmp / "dp.json"
        p.write_text(json.dumps({"damage_recap": {"total_recaps": 3}}), encoding="utf-8")
        self.assertEqual(damage_recap_summary(p), {})
        p.write_text(json.dumps({"damage_recap": {"provenance": "estimated",
                                                  "total_recaps": 3}}), encoding="utf-8")
        self.assertEqual(damage_recap_summary(p)["total_recaps"], 3)

    def test_postmortem_main_writes_section_and_loader_reads_it(self):
        from tests.test_postmortem_analyze import _build_fixture_db
        from scripts.postmortem_analyze import main
        from core.death_patterns_loader import damage_recap_summary, top_patterns
        db = self.tmp / "rewind.db"
        fixture = _build_fixture_db(db)
        recaps = self.tmp / "recaps.jsonl"
        for r in self._rows():
            dr.append_row(r, recaps)
        out = self.tmp / "out.json"
        rc = main(["--db", str(db), "--puuid", fixture["self_puuid"],
                   "--output", str(out), "--recaps", str(recaps)])
        self.assertEqual(rc, 0)
        data = json.loads(out.read_text(encoding="utf-8"))
        self.assertEqual(data["schema_version"], 2)
        self.assertEqual(data["damage_recap"]["total_recaps"], 2)
        summ = damage_recap_summary(out)
        self.assertEqual(summ["provenance"], "estimated")
        self.assertEqual(summ["total_recaps"], 2)
        # loader contract unchanged
        self.assertIsInstance(top_patterns(out), list)

    def test_postmortem_main_without_recaps_has_no_section(self):
        from tests.test_postmortem_analyze import _build_fixture_db
        from scripts.postmortem_analyze import main
        from core.death_patterns_loader import damage_recap_summary
        db = self.tmp / "rewind.db"
        fixture = _build_fixture_db(db)
        out = self.tmp / "out.json"
        rc = main(["--db", str(db), "--puuid", fixture["self_puuid"],
                   "--output", str(out), "--recaps", str(self.tmp / "none.jsonl")])
        self.assertEqual(rc, 0)
        data = json.loads(out.read_text(encoding="utf-8"))
        self.assertNotIn("damage_recap", data)
        self.assertEqual(damage_recap_summary(out), {})


class LabelTests(unittest.TestCase):
    def test_panel_line_says_estimated(self):
        ev = _kill(7, "SelfPlayer", "FoeOne", ["FoeTwo"])
        data = _game([ev])
        row = dr.build_recap(ev, data, {"Zed": _burst([("PHYSICAL", 700.0)]),
                                        "Lux": _burst([("MAGIC", 300.0)])},
                             dr.our_resists_from(data))
        line = dr.format_line(row)
        self.assertIn("estimated", line)
        self.assertIn("Zed", line)
        self.assertTrue(line.isascii())
        self.assertEqual(dr.format_line(None), "")


if __name__ == "__main__":
    unittest.main()
