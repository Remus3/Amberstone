"""Deep-audit cycle 8 P2-W1 dashboard slice C regression tests.

Covers fixes in the champ-select / lobby route surface:
  dashboard/routes_pickban.py        - cleanse advisory dead-import +
                                       canonical-name bridge + conditional
                                       durations_s field; bounded TTL cache;
                                       generic 500 bodies (both handlers)
  dashboard/routes_team_context.py   - non-int queue_id / team_id coercion
  dashboard/routes_personal_vs.py    - stable operator-puuid tiebreak;
                                       generic 500 body
  dashboard/routes_lobby_aux.py      - stable operator-puuid tiebreak;
                                       dead _ddragon_version removal;
                                       mains GET 500 wrapper; top8 POST
                                       generic 500 body
  dashboard/routes_draft_elo.py      - bounded cache; generic 500 body
  dashboard/routes_ban_suggest.py    - bounded cache; generic 500 body
  dashboard/routes_duo_synergy.py    - bounded cache; generic 500 body
  dashboard/routes_ban_suggestions.py - generic 500 body
  dashboard/routes_adaptive_summoners.py - generic 500 body
  dashboard/routes_personal_context.py   - generic 500 body
  dashboard/routes_sr_draft.py           - generic 500 body
  dashboard/routes_sr_user_builds.py     - generic 500 body

Every seam used below was grep-verified against the live module surface
(file:line cited in the audit report). Hermetic: no network, no real
rewind_history.db, registry lookups monkey-patched.
"""
from __future__ import annotations

import json
import sqlite3
import sys
import tempfile
import time
import types
import unittest
from pathlib import Path
from unittest import mock

from dashboard import routes_adaptive_summoners as ras
from dashboard import routes_ban_suggest as rbsg
from dashboard import routes_ban_suggestions as rbsu
from dashboard import routes_draft_elo as rde
from dashboard import routes_duo_synergy as rds
from dashboard import routes_lobby_aux as rla
from dashboard import routes_personal_context as rpc
from dashboard import routes_personal_vs as rpv
from dashboard import routes_pickban as rp
from dashboard import routes_sr_user_builds as rsub
from dashboard import routes_team_context as rtc

SECRET = "SECRET_DETAIL_xyzzy"


class _StubHandler:
    """Captures _send calls; mirrors tests/test_routes_personal_vs.py."""

    def __init__(self, path: str = "/", headers: dict | None = None):
        self.path = path
        self.headers = headers or {}
        self.client_address = ("127.0.0.1", 0)
        self.responses: list[tuple[int, bytes, str]] = []

    def _send(self, code, body, ctype="application/json"):
        self.responses.append((code, body, ctype))

    @property
    def code(self) -> int:
        return self.responses[-1][0]

    @property
    def body(self) -> bytes:
        return self.responses[-1][1]


# ---------------------------------------------------------------------
# routes_pickban: cleanse advisory (item 168) was silently dead
# ---------------------------------------------------------------------

class TestCleanseAdvisory(unittest.TestCase):
    """_compose_cleanse_advisory: routes_pickban.py:693. The per-spell
    registry truly lives at agents.daemon_slayer._per_spell_cc:778, NOT
    the package root; ConditionalCcEntry carries durations_s (tuple),
    not duration_seconds (cc_conditional.py:458)."""

    def setUp(self):
        from agents.daemon_slayer import _per_spell_cc as psc
        from agents.daemon_slayer import cc_conditional as ccc
        self._psc = psc
        self._ccc = ccc
        # Hermetic id->name map (display names, as DDragon "name").
        self._names = mock.patch.object(rp, "_CHAMP_ID_TO_NAME", {
            25: "Morgana", 22: "Ashe", 412: "Thresh",
            4: "Twisted Fate", 62: "Wukong", 59: "Jarvan IV",
            103: "Ahri",
        })
        self._names.start()
        self.addCleanup(self._names.stop)

    def _patch_registry(self, reg: dict):
        p = mock.patch.object(self._psc, "_PER_SPELL_CC_DURATIONS", reg)
        p.start()
        self.addCleanup(p.stop)

    def _patch_conditional(self, fn):
        p = mock.patch.object(self._ccc, "get_conditional_entries", fn)
        p.start()
        self.addCleanup(p.stop)

    def test_fires_on_three_heavy_cc_enemies_without_cleanse(self):
        self._patch_registry({
            "Morgana": {"Q": (2.0, 2.25, 2.5, 2.75, 3.0)},
            "Ashe":    {"R": (1.0,)},
            "Thresh":  {"Q": (1.5,)},
        })
        self._patch_conditional(lambda name: ())
        adv = rp._compose_cleanse_advisory((25, 22, 412), (4, 7))
        self.assertIsNotNone(
            adv, "advisory must fire for 3 heavy-CC enemies w/o Cleanse")
        self.assertIn("Cleanse", adv)

    def test_silent_when_cleanse_already_equipped(self):
        self._patch_registry({
            "Morgana": {"Q": (3.0,)},
            "Ashe":    {"R": (1.0,)},
            "Thresh":  {"Q": (1.5,)},
        })
        self._patch_conditional(lambda name: ())
        adv = rp._compose_cleanse_advisory((25, 22, 412), (4, 1))
        self.assertIsNone(adv)

    def test_display_names_bridge_to_canonical_registry_keys(self):
        # Registry keys are canonical DDragon ids; the LCU/ddragon side
        # hands the advisory display names. TwistedFate / MonkeyKing /
        # JarvanIV must still count.
        self._patch_registry({
            "TwistedFate": {"W": (1.5,)},
            "MonkeyKing":  {"R": (1.2,)},
            "JarvanIV":    {"R": (1.0,)},
        })
        self._patch_conditional(lambda name: ())
        adv = rp._compose_cleanse_advisory((4, 62, 59), (4, 7))
        self.assertIsNotNone(
            adv, "display-name enemies must bridge to canonical ids")

    def test_conditional_entries_use_durations_s(self):
        self._patch_registry({})
        entry = types.SimpleNamespace(durations_s=(1.2, 1.3, 1.4))
        self._patch_conditional(
            lambda name: (entry,) if name in
            ("Morgana", "Ashe", "Thresh") else ())
        adv = rp._compose_cleanse_advisory((25, 22, 412), (4, 7))
        self.assertIsNotNone(
            adv, "conditional CC entries (durations_s) must count")

    def test_below_threshold_stays_silent(self):
        self._patch_registry({"Morgana": {"Q": (3.0,)}})
        self._patch_conditional(lambda name: ())
        adv = rp._compose_cleanse_advisory((25, 103), (4, 7))
        self.assertIsNone(adv)


# ---------------------------------------------------------------------
# routes_team_context: malformed numeric fields must not blow the route
# ---------------------------------------------------------------------

class TestTeamContextCoercion(unittest.TestCase):
    """_serve_refresh_post (routes_team_context.py:350) crashed with
    ValueError on non-int queue_id / team_id; the dispatcher has no
    catch-all (dashboard/_handler.py:280) so the client saw a reset."""

    def setUp(self):
        rtc._clear()
        self.addCleanup(rtc._clear)
        # Route is local-only + unauthenticated post-ADR-012; only the
        # fan-out dispatcher needs stubbing to avoid a real Riot worker.
        p3 = mock.patch.object(rtc, "_FANOUT_DISPATCHER",
                               lambda a, e, q: None)
        p3.start()
        self.addCleanup(p3.stop)

    def _post(self, body):
        h = _StubHandler("/api/team-context/refresh", headers={})
        rtc._serve_refresh_post(h, body)
        return h

    def test_non_int_queue_id_coerces_to_zero(self):
        h = self._post({"queue_id": "garbage", "roster": [
            {"puuid": "p1", "summoner_name": "X", "team_id": 100,
             "locked_champion": "Ahri"},
        ]})
        self.assertEqual(h.code, 200)
        cache = rtc.get_team_context()
        self.assertIsNotNone(cache)
        self.assertEqual(cache["queue_id"], 0)

    def test_non_int_team_id_coerces_to_zero_allies(self):
        h = self._post({"queue_id": 420, "roster": [
            {"puuid": "p1", "summoner_name": "X", "team_id": "abc",
             "locked_champion": ""},
        ]})
        self.assertEqual(h.code, 200)
        cache = rtc.get_team_context()
        self.assertEqual(len(cache["allies"]), 1)
        self.assertEqual(cache["allies"][0]["team_id"], 0)

    def test_valid_ints_unchanged(self):
        h = self._post({"queue_id": 440, "roster": [
            {"puuid": "p1", "summoner_name": "X", "team_id": 200,
             "locked_champion": "Jax"},
        ]})
        self.assertEqual(h.code, 200)
        cache = rtc.get_team_context()
        self.assertEqual(cache["queue_id"], 440)
        self.assertEqual(len(cache["enemies"]), 1)


# ---------------------------------------------------------------------
# operator-puuid resolver: stable tiebreak (mirrors routes_pickban.py:261)
# ---------------------------------------------------------------------

def _tied_db(path: Path) -> None:
    conn = sqlite3.connect(str(path))
    conn.executescript("""
        CREATE TABLE matches (
            match_id TEXT PRIMARY KEY,
            queue_id INTEGER,
            game_creation_ts INTEGER
        );
        CREATE TABLE participants (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            match_id TEXT, puuid TEXT, team_id INTEGER,
            champion_id INTEGER, champion_name TEXT, win INTEGER
        );
    """)
    # Two puuids, identical match counts. Insert the lexicographically
    # LARGER one first so insertion order disagrees with the contract.
    for i in range(5):
        mid = f"M{i}"
        conn.execute("INSERT INTO matches VALUES (?,?,?)", (mid, 420, i))
        conn.execute(
            "INSERT INTO participants(match_id,puuid,team_id,champion_id,"
            "champion_name,win) VALUES (?,?,?,?,?,?)",
            (mid, "zzz-puuid", 100, 1, "Annie", 1))
        conn.execute(
            "INSERT INTO participants(match_id,puuid,team_id,champion_id,"
            "champion_name,win) VALUES (?,?,?,?,?,?)",
            (mid, "aaa-puuid", 200, 2, "Ahri", 0))
    conn.commit()
    conn.close()


class TestOperatorPuuidTiebreak(unittest.TestCase):
    def test_personal_vs_resolver_deterministic_on_tie(self):
        with tempfile.TemporaryDirectory() as td:
            db = Path(td) / "rh.db"
            _tied_db(db)
            conn = sqlite3.connect(str(db))
            try:
                self.assertEqual(
                    rpv._resolve_operator_puuid(conn), "aaa-puuid")
            finally:
                conn.close()

    def test_lobby_aux_resolver_deterministic_on_tie(self):
        with tempfile.TemporaryDirectory() as td:
            db = Path(td) / "rh.db"
            _tied_db(db)
            conn = sqlite3.connect(str(db))
            try:
                self.assertEqual(
                    rla._resolve_operator_puuid(conn), "aaa-puuid")
            finally:
                conn.close()


# ---------------------------------------------------------------------
# bounded TTL caches (retention-less growth)
# ---------------------------------------------------------------------

class TestBoundedCaches(unittest.TestCase):
    def test_pickban_cache_bounded(self):
        rp._reset_caches()
        self.addCleanup(rp._reset_caches)
        for i in range(rp._PB_CACHE_MAX + 50):
            rp._cache_put(("pickban", float(i), "TOP", (420,), "comfort",
                           (), (), (), (), 1, i), time.time(), {"ok": True})
        self.assertLessEqual(len(rp._PB_CACHE), rp._PB_CACHE_MAX)

    def test_draft_elo_cache_bounded(self):
        rde._reset_caches()
        self.addCleanup(rde._reset_caches)
        for i in range(rde._CACHE_MAX + 50):
            rde._cache_put((i,), time.time(), {"ok": True})
        self.assertLessEqual(len(rde._CACHE), rde._CACHE_MAX)

    def test_ban_suggest_cache_bounded(self):
        rbsg._reset_caches()
        self.addCleanup(rbsg._reset_caches)
        for i in range(rbsg._CACHE_MAX + 50):
            rbsg._cache_put((i,), time.time(), {"ok": True})
        self.assertLessEqual(len(rbsg._CACHE), rbsg._CACHE_MAX)

    def test_duo_synergy_cache_bounded(self):
        rds._reset_caches()
        self.addCleanup(rds._reset_caches)
        for i in range(rds._CACHE_MAX + 50):
            rds._cache_put((f"k{i}",), time.time(), {"ok": True})
        self.assertLessEqual(len(rds._CACHE), rds._CACHE_MAX)


# ---------------------------------------------------------------------
# 500 envelopes must not leak raw exception text (CLAUDE.md error rule;
# same standard dashboard/_handler.py:252 articulates for do_POST)
# ---------------------------------------------------------------------

class TestGeneric500Bodies(unittest.TestCase):
    def _assert_clean_500(self, h):
        self.assertEqual(h.code, 500)
        self.assertNotIn(SECRET.encode(), h.body,
                         "raw exception text leaked into the 500 body")
        doc = json.loads(h.body.decode("utf-8"))
        err = doc.get("error", "")
        self.assertTrue(err, "500 body should carry a friendly error field")

    def test_pickban_recs_500(self):
        with mock.patch.object(rp, "_parse_queue_ids",
                               side_effect=RuntimeError(SECRET)):
            h = _StubHandler("/api/champ-select/pickban-recs?role=TOP")
            rp._serve_pickban_recs(h)
        self._assert_clean_500(h)

    def test_personal_record_500(self):
        with mock.patch.object(rp, "_parse_queue_ids",
                               side_effect=RuntimeError(SECRET)):
            h = _StubHandler("/api/champ-select/personal-record?champ=22")
            rp._serve_personal_record(h)
        self._assert_clean_500(h)

    def test_draft_elo_500(self):
        with mock.patch.object(rde, "_parse_int_list",
                               side_effect=RuntimeError(SECRET)):
            h = _StubHandler("/api/draft-elo?ally=1,2,3,4,5&enemy=6,7,8,9,10")
            rde._serve_draft_elo(h)
        self._assert_clean_500(h)

    def test_ban_suggest_500(self):
        with mock.patch.object(rbsg, "_parse_int_list",
                               side_effect=RuntimeError(SECRET)):
            h = _StubHandler("/api/ban-suggest?ally=1&candidates=2")
            rbsg._serve_ban_suggest(h)
        self._assert_clean_500(h)

    def test_ban_suggestions_500(self):
        with mock.patch.object(rbsu, "_load_bans_file",
                               side_effect=RuntimeError(SECRET)):
            h = _StubHandler("/api/champ-select/ban-suggestions")
            rbsu._serve_ban_suggestions(h)
        self._assert_clean_500(h)

    def test_adaptive_summoners_500(self):
        with mock.patch.object(ras, "_resolve_enemy_names",
                               side_effect=RuntimeError(SECRET)):
            h = _StubHandler(
                "/api/champ-select/adaptive-summoners?champion=Ahri")
            ras._serve_adaptive_summoners(h)
        self._assert_clean_500(h)

    def test_personal_vs_500(self):
        with mock.patch.object(rpv, "_parse_queue_filter",
                               side_effect=RuntimeError(SECRET)):
            h = _StubHandler("/api/personal-vs?champ_id=10")
            rpv._serve_personal_vs(h)
        self._assert_clean_500(h)

    def test_personal_context_500(self):
        rpc._CACHE["payload"] = None
        rpc._CACHE["expires_at"] = 0.0
        with mock.patch.object(rpc, "_build_payload",
                               side_effect=RuntimeError(SECRET)):
            h = _StubHandler("/api/personal-context")
            rpc._serve_personal_context(h)
        self._assert_clean_500(h)

    def test_duo_synergy_500(self):
        rds._reset_caches()
        self.addCleanup(rds._reset_caches)
        with mock.patch.object(rds, "_build_payload",
                               side_effect=RuntimeError(SECRET)):
            h = _StubHandler("/api/duo-synergy?my_role=bot")
            rds._serve_duo_synergy(h)
        self._assert_clean_500(h)

    def test_sr_draft_apply_500(self):
        # Stub web_dashboard so the in-handler import is hermetic
        # (pattern: tests/phase8_smoke/test_sr_draft_apply.py:40).
        if "web_dashboard" not in sys.modules:
            stub = types.ModuleType("web_dashboard")
            stub._VISION_TOKEN = "test-token"
            sys.modules["web_dashboard"] = stub
            self.addCleanup(sys.modules.pop, "web_dashboard", None)
        else:
            sys.modules["web_dashboard"]._VISION_TOKEN = "test-token"
        from dashboard import routes_sr_draft as rsd
        with mock.patch.object(rsd, "_build_rune_cmd",
                               side_effect=RuntimeError(SECRET)):
            h = _StubHandler("/api/sr-draft/apply")
            rsd._serve_sr_draft_apply_post(h, {
                "champion": "Tristana", "key": "primary",
                "runes": {"keystone": "k", "primary": "p",
                          "secondary": "s"},
            })
        self._assert_clean_500(h)

    def test_sr_user_builds_get_500(self):
        import coaches.sr_user_builds as sub
        with mock.patch.object(sub, "list_for",
                               side_effect=RuntimeError(SECRET)):
            h = _StubHandler("/api/sr-draft/user-builds?champion=Ahri")
            rsub._serve_user_builds_get(h)
        self._assert_clean_500(h)

    def test_sr_user_builds_post_500(self):
        import coaches.sr_user_builds as sub
        with mock.patch.object(sub, "list_for",
                               side_effect=RuntimeError(SECRET)):
            h = _StubHandler("/api/sr-draft/user-builds")
            rsub._serve_user_builds_post(
                h, {"action": "list", "champion": "Ahri"})
        self._assert_clean_500(h)

    def test_top8_post_save_500(self):
        with mock.patch.object(rla, "_save_top8",
                               side_effect=RuntimeError(SECRET)):
            h = _StubHandler("/api/top8")
            rla._serve_top8_post(h, {"entries": [
                {"riot_id": "A#B", "summoner_name": "A"}]})
        self._assert_clean_500(h)

    def test_mains_get_wraps_internal_error(self):
        # Pre-fix: the exception escaped the handler entirely
        # (connection reset); post-fix: friendly 500 envelope.
        with mock.patch.object(rla, "_operator_mains",
                               side_effect=RuntimeError(SECRET)):
            h = _StubHandler("/api/mains")
            rla._serve_mains_get(h)
        self._assert_clean_500(h)


# ---------------------------------------------------------------------
# routes_lobby_aux: dead self-HTTP helper removed (stale 16.9.1 pin)
# ---------------------------------------------------------------------

class TestLobbyAuxDeadCode(unittest.TestCase):
    def test_ddragon_version_helper_removed(self):
        self.assertFalse(hasattr(rla, "_ddragon_version"))
        self.assertFalse(hasattr(rla, "_DDRAGON_VERSION_DEFAULT"))


if __name__ == "__main__":
    unittest.main()
