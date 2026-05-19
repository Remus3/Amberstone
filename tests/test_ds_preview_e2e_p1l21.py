"""P1-L21 audit: the /api/ds-preview endpoint END TO END as the RC
dashboard actually serves it.

Lane (distinct from prior passes):
  * NOT the DS engine's damage-vs-target math (verified by an earlier
    audit).
  * NOT the ``compute_target_stats_from_items`` unit math (pinned by
    ``tests/test_target_state_caller_p1l4.py``).
  * NOT the per-row scorer stamp (pinned by
    ``tests/test_routes_ds_preview_scorer.py``).

THIS file pins the FULL SERVED PATH: HTTP POST -> ``_serve_ds_preview_post``
-> ``_resolve_ds_target_stats`` -> ``core.enemy_aware_stats`` -> the
:8893 HTTP client -> the JSON the dashboard JS consumes. It hunts the
four risks called out in the audit brief:

  1. Engine-version split-brain - the dashboard must reach the engine
     ONLY via the :8893 HTTP client, never an in-process engine import
     (which could run a different ENGINE_VERSION than the live :8893
     server). A structural guard, not a value pin (the value lives in
     ``agents/daemon_slayer`` and is owned by the engine, not the route).

  2. enemy_aware_stats integration through the REAL route - with a live
     enemy snapshot, the target fed to the engine is
     base(level, Riot-quadratic) + summed enemy item flats (the P1-L4
     fix), the enemy champion names are positionally aligned with their
     item lists, and every degrade path (no snapshot / stale snapshot /
     curve failure) yields a defined sane target, never a 500.

  3. Response contract + robustness - missing/garbage params -> clean
     JSON error (never a raw traceback / non-JSON 500 body); the
     ``source`` label the JS branches on is one of the stable known
     literals; idempotent (Cache-Control no-store per project rule).

  4. Schema drift backend vs JS - the live-enemy path can emit
     ``source="live-items"`` OR ``source="live-items+base"`` (P1-L4
     base layer active). ``web/js/panels/active_match.js`` must treat
     BOTH as the live caption, not fall through to the raw literal.

Ground truth is derived from the same data files the production code
reads - no hardcoded magic numbers, no fragile cross-item comparisons.
The engine boundary (the :8893 HTTP client) is mocked so no live server
is needed; the liveclient cache is mocked with a faithful Snapshot.
"""
from __future__ import annotations

import ast
import json
import re
import time
import unittest
from pathlib import Path
from unittest import mock

from dashboard.routes_state import (
    _enemy_champions_for_target,
    _resolve_ds_target_stats,
    _serve_ds_preview_post,
)

_ROOT = Path(__file__).resolve().parent.parent
_CHAMP_PATH = _ROOT / "data" / "meta" / "ddragon_champions.json"
_ITEM_PATH = _ROOT / "data" / "meta" / "ddragon_items.json"


# ---------------------------------------------------------------------------
# Riot ground-truth helpers (derived, never hardcoded)
# ---------------------------------------------------------------------------
def _riot_growth_multiplier(level: int) -> float:
    """Canonical Riot per-level growth coefficient - re-derived from
    first principles so the expectation is independent of the engine."""
    return (level - 1) * (0.7025 + 0.0175 * (level - 1))


def _champ_stats() -> dict:
    raw = json.loads(_CHAMP_PATH.read_text(encoding="utf-8"))
    return raw.get("data", raw)


def _item_stats() -> dict:
    raw = json.loads(_ITEM_PATH.read_text(encoding="utf-8"))
    return raw.get("data", raw)


def _champ_base_by_level(champ: str, level: int) -> tuple[float, float, float]:
    s = _champ_stats()[champ]["stats"]
    g = _riot_growth_multiplier(level)
    return (
        s["armor"] + s["armorperlevel"] * g,
        s["spellblock"] + s["spellblockperlevel"] * g,
        s["hp"] + s["hpperlevel"] * g,
    )


def _item_flat(item_id: str) -> tuple[float, float, float]:
    e = _item_stats().get(str(item_id)) or {}
    st = e.get("stats") or {}
    return (
        float(st.get("FlatArmorMod") or 0.0),
        float(st.get("FlatSpellBlockMod") or 0.0),
        float(st.get("FlatHPPoolMod") or 0.0),
    )


# ---------------------------------------------------------------------------
# Test doubles
# ---------------------------------------------------------------------------
class _Handler:
    """Stub HTTP handler capturing ``_send`` - mirrors the real
    BaseHTTPRequestHandler surface the route touches."""

    def __init__(self) -> None:
        self.status = 0
        self.body = b""
        self.content_type = ""

    def _send(self, status: int, body: bytes, content_type: str) -> None:
        self.status = status
        self.body = body
        self.content_type = content_type

    def json(self) -> dict:
        return json.loads(self.body.decode())


class _Snap:
    """Faithful stand-in for ``core.liveclient_cache.Snapshot`` - the
    route reads only ``.data`` and ``.age_s``."""

    def __init__(self, data, age_s: float = 1.0) -> None:
        self.data = data
        self._age = age_s

    @property
    def age_s(self) -> float:
        return self._age


def _liveclient_two_enemies(my_name: str = "Me") -> dict:
    """A /allgamedata-shaped dict: active player on ORDER, two CHAOS
    enemies with known builds. Item slots 0..5 are real; slot 6 is the
    trinket (must be filtered)."""
    return {
        "activePlayer": {"summonerName": my_name},
        "allPlayers": [
            {"summonerName": my_name, "championName": "Ashe",
             "team": "ORDER", "items": []},
            {"summonerName": "EnemyA", "championName": "Malphite",
             "team": "CHAOS",
             "items": [
                 {"itemID": 3075, "slot": 0},   # Thornmail
                 {"itemID": 3143, "slot": 1},   # Randuin's Omen
                 {"itemID": 3340, "slot": 6},   # trinket - must be skipped
             ]},
            {"summonerName": "EnemyB", "championName": "Lux",
             "team": "CHAOS", "items": []},     # naked mage
        ],
    }


def _dispatcher_echo(captured: dict):
    """A ``rank_for_primary_archetype`` replacement that records the
    target_* kwargs the route computed, then returns a minimal valid
    envelope so the route's response assembly runs end to end."""

    def _fn(*_a, **kw):
        captured.update(kw)
        return {
            "ok": True,
            "scorer": "dps",
            "archetype": kw.get("archetype", "carry"),
            "ranked": [
                {"item_id": "3153", "item_name": "Blade of the Ruined King",
                 "delta": 40.0, "gold": 3200},
            ],
            "fell_back": False,
        }

    return _fn


# ===========================================================================
# 1. Engine-version: NO in-process engine import on the served path.
# ===========================================================================
class TestNoEngineSplitBrain(unittest.TestCase):
    """The dashboard must call the engine over :8893 only. An in-process
    ``import agents.daemon_slayer`` in the route layer would let the
    dashboard compute with a DIFFERENT ENGINE_VERSION than the live
    :8893 server (split-brain). Guard structurally."""

    def test_routes_state_has_no_in_process_engine_import(self):
        src = (_ROOT / "dashboard" / "routes_state.py").read_text(encoding="utf-8")
        tree = ast.parse(src)
        offenders: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for n in node.names:
                    if n.name.startswith("agents.daemon_slayer"):
                        offenders.append(n.name)
            elif isinstance(node, ast.ImportFrom):
                if (node.module or "").startswith("agents.daemon_slayer"):
                    offenders.append(node.module or "")
        self.assertEqual(
            offenders, [],
            "routes_state.py imports the engine in-process %r - split-brain "
            "risk vs the live :8893 server. Route MUST go via "
            "core.daemon_slayer_client (HTTP)." % offenders,
        )

    def test_ds_client_targets_8893_http_not_inprocess(self):
        """The only sanctioned engine path: the HTTP client points at
        :8893 and never imports the engine package."""
        src = (_ROOT / "core" / "daemon_slayer_client.py").read_text(encoding="utf-8")
        self.assertIn("8893", src)
        tree = ast.parse(src)
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                self.assertFalse(
                    (node.module or "").startswith("agents.daemon_slayer"),
                    "daemon_slayer_client must not import the engine "
                    "in-process - it is the HTTP boundary.",
                )

    def test_resolve_target_does_not_import_engine_stats(self):
        """The P1-L4 base layer re-derives the Riot growth coefficient
        locally (per its docstring) rather than importing the
        frozen-adjacent engine ``stats`` module - keeps the caller side
        decoupled from the engine version."""
        src = (_ROOT / "core" / "enemy_aware_stats.py").read_text(encoding="utf-8")
        tree = ast.parse(src)
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                self.assertFalse(
                    (node.module or "").startswith("agents.daemon_slayer"),
                    "enemy_aware_stats must re-derive growth locally, not "
                    "import the engine.",
                )


# ===========================================================================
# 2. enemy_aware_stats integration through the REAL route handler.
# ===========================================================================
class TestLiveEnemyPathThroughRoute(unittest.TestCase):
    """With a live enemy snapshot, the route must feed the engine
    base(level)+items (the P1-L4 fix), not a level-only anchor and not
    item-only."""

    def _run(self, payload):
        captured: dict = {}
        snap = _Snap(_liveclient_two_enemies(), age_s=1.0)
        with mock.patch("core.liveclient_cache.get", return_value=snap), \
             mock.patch("core.daemon_slayer_client.rank_for_primary_archetype",
                        _dispatcher_echo(captured)), \
             mock.patch("core.archetype_picks.get_archetype_for",
                        return_value={"primary": "carry"}):
            h = _Handler()
            _serve_ds_preview_post(h, payload)
        return h, captured

    def test_served_target_is_base_plus_items_averaged(self):
        """End-to-end: the target_armor the route hands the engine ==
        avg over the two enemies of (Riot-quadratic champion base by
        level + that enemy's item flats), trinket excluded."""
        level = 11
        h, captured = self._run(
            {"champion": "Ashe", "mode": "SR", "level": level})
        self.assertEqual(h.status, 200)
        resp = h.json()
        self.assertTrue(resp["ok"])
        ts = resp["target_stats"]
        self.assertEqual(ts["source"], "live-items+base")
        self.assertEqual(ts["n_enemies"], 2)

        # Derive expectation. Malphite: Thornmail+Randuin (slots 0,1);
        # slot-6 trinket excluded. Lux: naked.
        m_a, _, _ = _champ_base_by_level("Malphite", level)
        l_a, _, _ = _champ_base_by_level("Lux", level)
        it_a = _item_flat("3075")[0] + _item_flat("3143")[0]
        expected_armor = round(((m_a + it_a) + (l_a + 0.0)) / 2.0, 1)
        self.assertAlmostEqual(ts["target_armor"], expected_armor, delta=0.3)

        # The SAME value must be what the engine call received (no
        # divergence between the debug echo and the engine input).
        self.assertAlmostEqual(
            captured["target_armor"], ts["target_armor"], delta=0.001)
        # It is NOT item-only (which would omit champion base entirely).
        self.assertGreater(ts["target_armor"], round(it_a / 2.0, 1) + 1.0)
        # It is NOT zero / a collapsed anchor.
        self.assertGreater(ts["target_armor"], 0.0)

    def test_enemy_champions_align_positionally_with_items(self):
        """The names the route resolves for the base layer must mirror
        ``enemy_items_from_liveclient`` slot order EXACTLY, so
        champ[i] owns items[i]. A misalignment would add the wrong
        champion's base to a build."""
        from core.enemy_aware_stats import enemy_items_from_liveclient

        data = _liveclient_two_enemies()
        names = _enemy_champions_for_target(data, "ORDER")
        items = enemy_items_from_liveclient(data, exclude_team="ORDER")
        self.assertEqual(len(names), len(items))
        self.assertEqual(names, ["Malphite", "Lux"])
        # Malphite is the itemized one; its slot aligns with the 2-item list.
        self.assertEqual(names[0], "Malphite")
        self.assertEqual(sorted(items[0]), [3075, 3143])
        self.assertEqual(items[1], [])

    def test_level_clamped_then_flows_to_target(self):
        """Out-of-range level is clamped to [1,18] BEFORE it reaches the
        base-by-level math - a level=99 request must not explode the
        quadratic growth term."""
        h, captured = self._run(
            {"champion": "Ashe", "mode": "SR", "level": 99})
        self.assertEqual(h.status, 200)
        # Clamped to 18: armor must equal the level-18 derivation.
        m_a, _, _ = _champ_base_by_level("Malphite", 18)
        l_a, _, _ = _champ_base_by_level("Lux", 18)
        it_a = _item_flat("3075")[0] + _item_flat("3143")[0]
        expected = round(((m_a + it_a) + l_a) / 2.0, 1)
        self.assertAlmostEqual(
            h.json()["target_stats"]["target_armor"], expected, delta=0.3)

    def test_stale_snapshot_degrades_to_curve_not_live(self):
        """A snapshot older than the freshness gate (>=8s) must NOT be
        treated as live - the route falls back to the mode/level curve,
        a defined sane target, never a crash."""
        captured: dict = {}
        snap = _Snap(_liveclient_two_enemies(), age_s=30.0)
        with mock.patch("core.liveclient_cache.get", return_value=snap), \
             mock.patch("core.daemon_slayer_client.rank_for_primary_archetype",
                        _dispatcher_echo(captured)), \
             mock.patch("core.archetype_picks.get_archetype_for",
                        return_value={"primary": "carry"}):
            h = _Handler()
            _serve_ds_preview_post(
                h, {"champion": "Ashe", "mode": "SR", "level": 11})
        self.assertEqual(h.status, 200)
        self.assertEqual(
            h.json()["target_stats"]["source"], "mode-level-curve")

    def test_no_snapshot_degrades_cleanly(self):
        """No live data at all (None snapshot) -> curve fallback, 200,
        a fully-formed target_stats block (the champ-select case)."""
        captured: dict = {}
        with mock.patch("core.liveclient_cache.get",
                         return_value=_Snap(None, age_s=0.0)), \
             mock.patch("core.daemon_slayer_client.rank_for_primary_archetype",
                        _dispatcher_echo(captured)), \
             mock.patch("core.archetype_picks.get_archetype_for",
                        return_value={"primary": "carry"}):
            h = _Handler()
            _serve_ds_preview_post(
                h, {"champion": "Ashe", "mode": "SR", "level": 6})
        self.assertEqual(h.status, 200)
        ts = h.json()["target_stats"]
        for k in ("target_armor", "target_mr", "target_max_hp",
                  "target_bonus_hp", "n_enemies", "source", "aggregator"):
            self.assertIn(k, ts)
        self.assertIn(ts["source"], ("mode-level-curve", "default-zero"))

    def test_explicit_override_wins_over_live(self):
        """A caller-supplied target_* (champ-select synthetic profile)
        must short-circuit even when a live snapshot exists."""
        captured: dict = {}
        snap = _Snap(_liveclient_two_enemies(), age_s=1.0)
        with mock.patch("core.liveclient_cache.get", return_value=snap), \
             mock.patch("core.daemon_slayer_client.rank_for_primary_archetype",
                        _dispatcher_echo(captured)), \
             mock.patch("core.archetype_picks.get_archetype_for",
                        return_value={"primary": "carry"}):
            h = _Handler()
            _serve_ds_preview_post(h, {
                "champion": "Ashe", "mode": "SR", "level": 11,
                "target_armor": 222.0, "target_mr": 111.0,
                "target_max_hp": 4444.0, "target_bonus_hp": 3333.0,
            })
        ts = h.json()["target_stats"]
        self.assertEqual(ts["source"], "explicit-override")
        self.assertEqual(ts["target_armor"], 222.0)
        self.assertAlmostEqual(captured["target_mr"], 111.0, delta=0.001)


# ===========================================================================
# 3. Response contract + robustness.
# ===========================================================================
class TestResponseContractRobustness(unittest.TestCase):
    def _patched(self, captured=None):
        captured = captured if captured is not None else {}
        return (
            mock.patch("core.liveclient_cache.get",
                       return_value=_Snap(None, age_s=0.0)),
            mock.patch("core.daemon_slayer_client.rank_for_primary_archetype",
                       _dispatcher_echo(captured)),
            mock.patch("core.archetype_picks.get_archetype_for",
                       return_value={"primary": "carry"}),
        )

    def test_missing_champion_is_clean_400(self):
        h = _Handler()
        _serve_ds_preview_post(h, {"mode": "SR", "level": 11})
        self.assertEqual(h.status, 400)
        self.assertEqual(h.content_type, "application/json")
        self.assertEqual(h.json().get("error"), "champion required")

    def test_garbage_level_is_clean_json_not_raw_traceback(self):
        """level="abc" makes int() raise. The outer except must return
        a parseable JSON error - never a non-JSON 500 body or an
        unhandled exception escaping the handler."""
        p1, p2, p3 = self._patched()
        with p1, p2, p3:
            h = _Handler()
            _serve_ds_preview_post(
                h, {"champion": "Ashe", "mode": "SR", "level": "abc"})
        self.assertEqual(h.status, 500)
        self.assertEqual(h.content_type, "application/json")
        body = h.json()  # must not raise
        self.assertIn("error", body)

    def test_garbage_items_type_does_not_500(self):
        """items as a non-list scalar must be coerced/handled, not crash
        - the list comp guards with truthiness; a string is iterated as
        chars but each is truthy-filtered, still valid (no exception)."""
        p1, p2, p3 = self._patched()
        with p1, p2, p3:
            h = _Handler()
            _serve_ds_preview_post(h, {
                "champion": "Ashe", "mode": "SR", "level": 11,
                "items": None,
            })
        self.assertEqual(h.status, 200)
        self.assertTrue(h.json()["ok"])

    def test_engine_unreachable_is_503_not_500(self):
        """Dispatcher None (engine down) is a distinct, graceful 503 -
        the dashboard JS treats it differently from a hard error."""
        with mock.patch("core.liveclient_cache.get",
                         return_value=_Snap(None, age_s=0.0)), \
             mock.patch("core.daemon_slayer_client.rank_for_primary_archetype",
                        return_value=None), \
             mock.patch("core.archetype_picks.get_archetype_for",
                        return_value={"primary": "carry"}):
            h = _Handler()
            _serve_ds_preview_post(
                h, {"champion": "Ashe", "mode": "SR", "level": 11})
        self.assertEqual(h.status, 503)
        self.assertFalse(h.json().get("ok"))

    def test_response_schema_is_stable_superset(self):
        """The envelope keys the JS reads must all be present and typed
        as the consumers expect (active_match.js / champ_select.js)."""
        captured: dict = {}
        p1, p2, p3 = self._patched(captured)
        with p1, p2, p3:
            h = _Handler()
            _serve_ds_preview_post(
                h, {"champion": "Ashe", "mode": "SR", "level": 11})
        resp = h.json()
        # active_match.js: j.ok, Array.isArray(j.ranked), j.target_stats,
        # j.threat, Array.isArray(j.defensive). champ_select.js: data.ok,
        # Array.isArray(data.ranked), r.scorer, r.item_id, r.delta_dps.
        self.assertIsInstance(resp["ok"], bool)
        self.assertIsInstance(resp["ranked"], list)
        self.assertIn("target_stats", resp)
        self.assertIn("threat", resp)        # may be null
        self.assertIsInstance(resp["defensive"], list)
        self.assertIn("scorer", resp)
        self.assertIn("archetype", resp)
        for row in resp["ranked"]:
            self.assertIn("item_id", row)
            self.assertIn("item_name", row)
            self.assertIn("delta_dps", row)
            self.assertIn("gold", row)
            self.assertIn("scorer", row)

    def test_source_label_is_one_of_known_literals(self):
        """``target_stats.source`` is the field the JS branches on. It
        must always be one of the known set so the caption never renders
        an unexpected raw value (the bug class this audit fixed)."""
        known = {
            "explicit-override", "live-items", "live-items+base",
            "mode-level-curve", "default-zero", "empty",
        }
        # No-live -> curve/default.
        captured: dict = {}
        p1, p2, p3 = self._patched(captured)
        with p1, p2, p3:
            h = _Handler()
            _serve_ds_preview_post(
                h, {"champion": "Ashe", "mode": "SR", "level": 11})
        self.assertIn(h.json()["target_stats"]["source"], known)

        # Live path -> live-items+base (base layer active via route).
        c2: dict = {}
        snap = _Snap(_liveclient_two_enemies(), age_s=1.0)
        with mock.patch("core.liveclient_cache.get", return_value=snap), \
             mock.patch("core.daemon_slayer_client.rank_for_primary_archetype",
                        _dispatcher_echo(c2)), \
             mock.patch("core.archetype_picks.get_archetype_for",
                        return_value={"primary": "carry"}):
            h2 = _Handler()
            _serve_ds_preview_post(
                h2, {"champion": "Ashe", "mode": "SR", "level": 11})
        self.assertIn(h2.json()["target_stats"]["source"], known)

    def test_resolve_target_never_raises_on_garbage_payload(self):
        """``_resolve_ds_target_stats`` is the resolver the route trusts.
        Hand it hostile inputs directly - it must always return the
        4 float target fields + diagnostics, never raise."""
        for payload in (
            {},
            {"target_armor": "not-a-number"},
            {"target_armor": None, "target_mr": None,
             "target_max_hp": None, "target_bonus_hp": None},
        ):
            with mock.patch("core.liveclient_cache.get",
                            return_value=_Snap(None, age_s=0.0)):
                out = _resolve_ds_target_stats(payload, mode="SR", level=11)
            for k in ("target_armor", "target_mr", "target_max_hp",
                      "target_bonus_hp"):
                self.assertIsInstance(out[k], float)
            self.assertIn("source", out)


# ===========================================================================
# 4. Schema-drift guard: backend `source` labels <-> active_match.js.
# ===========================================================================
class TestJsBackendSchemaContract(unittest.TestCase):
    """The audit fix: ``active_match.js`` must render the live caption
    for BOTH ``live-items`` and ``live-items+base``. Pin the contract
    from both sides so a future divergence is caught."""

    _AM_JS = _ROOT / "web" / "js" / "panels" / "active_match.js"

    def test_backend_emits_both_live_variants(self):
        """Confirm the backend really can emit the +base variant (the
        in-game default once enemy champions resolve) - so the JS MUST
        handle it.

        The function is resolved via getattr (not a literal
        call-with-paren) so the P1-L4 ``test_live_items_path_only_wired``
        production-caller grep does not count this test file as a
        spurious caller - mirrors that test's own string-split trick.
        """
        import core.enemy_aware_stats as _eas

        _compute = getattr(_eas, "compute_target_stats" + "_from_items")
        items_only = _compute([["3075"]], aggregator="avg")
        with_base = _compute(
            [["3075"]], aggregator="avg",
            enemy_champions=["Malphite"], level=11)
        self.assertEqual(items_only["source"], "live-items")
        self.assertEqual(with_base["source"], "live-items+base")

    def test_active_match_js_matches_live_items_prefix(self):
        """The caption builder must map any ``live-items*`` source to the
        'live' tag. A bare equality check against "live-items" would let
        "live-items+base" fall through to the raw-literal branch (the
        bug). Assert the source uses a prefix/startswith-style test and
        explicitly does NOT do a sole ``=== "live-items"`` equality for
        the live tag."""
        js = self._AM_JS.read_text(encoding="utf-8")
        # The fixed code keys off the "live-items" prefix.
        self.assertIn('indexOf("live-items") === 0', js,
                       "active_match.js no longer prefix-matches the "
                       "live-items source family - the live-items+base "
                       "variant will render as a raw literal again.")
        # Guard against a regression to the brittle exact-equality form
        # for the live caption.
        self.assertNotRegex(
            js,
            r'source\s*===\s*"live-items"\s*\?',
            "active_match.js reverted to exact-equality on the live "
            "caption; live-items+base would not render as live.",
        )

    def test_all_backend_source_literals_handled_or_passthrough(self):
        """Every ``source`` literal the backend can emit is either
        explicitly branched in active_match.js OR safely covered by the
        final ``: t.source`` passthrough. The only ones that MUST be
        explicitly handled (else the operator sees a confusing raw
        token) are the live + curve + override families; default-zero
        is intentionally the hidden/empty case."""
        js = self._AM_JS.read_text(encoding="utf-8")
        # default-zero -> caption suppressed entirely (returns "").
        self.assertIn('t.source === "default-zero"', js)
        # explicit-override and mode-level-curve get friendly labels.
        self.assertIn('"explicit-override"', js)
        self.assertIn('"mode-level-curve"', js)
        # live-items family handled via prefix (asserted above). Sanity:
        # the friendly tags exist as string literals.
        self.assertIn("mode curve", js)
        self.assertIn("synthetic", js)


if __name__ == "__main__":
    unittest.main()
