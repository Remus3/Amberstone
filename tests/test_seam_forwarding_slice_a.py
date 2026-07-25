"""Seam-flag forwarding: /api/ds-preview + with_build_order (SLICE A).

Two confirmed defects, both "the plumbing exists and nothing uses it":

DEFECT 1 - ``dashboard/routes_state.py`` ``_serve_ds_preview_post`` called
``core.daemon_slayer_client.rank_for_primary_archetype`` with a FIXED kwarg
list (champion / archetype / level / item_ids / mode / top / sort_by /
timeout / the four target_*). The dispatcher accepts nine-plus seam flags
plus ``enemy_ad_share`` / ``enemy_ap_share``, so /api/ds-preview could not
reach ANY seam - the champ-select + in-game BUILD preview ranked with every
seam at its client default no matter what the caller asked for.

DEFECT 2 - ``coach_integration/archetype_dispatch.dispatch_for_coach``
forwards seam flags to the flat ranking (lines 279-299) but the
``with_build_order=True`` branch called ``core.build_order.plan_build_order``
with NO ``rank_kwargs`` at all. ``plan_build_order`` has had a
``rank_kwargs`` param since 2026-05-17 that it splats into EVERY ranker
call, so the fix is pure plumbing. Because ``prefer_kit_axis_by_win``
DEFAULTS TO TRUE in ``dispatch_for_coach`` (C4 flip, 2026-07-04), a
``with_build_order=True`` dispatch RANKED with the kit-axis seam ON and
PLANNED the ordered build with it OFF - a silent divergence between the
flat DS row list and the ordered build the operator actually follows.
``enemy_ad_share`` / ``enemy_ap_share`` were dropped on the planner side
too (the planner only received the four target_* stats), which also
neutered the AD/AP-aware boots pick at ``core/build_order.py:574``.

Assumptions (verified against source before writing):
  - Body key names for /api/ds-preview seams are EXACTLY the
    ``rank_for_primary_archetype`` parameter names
    (core/daemon_slayer_client.py:1399-1411).
  - ``score_by`` has two legal values: "blended" (default) and
    "team_blended" (core/daemon_slayer_client.py:329-330).
  - A flagless request must stay byte-identical, so a seam is forwarded
    only when non-default - the same ``if flag: kwargs[...] = True`` idiom
    already used at coach_integration/archetype_dispatch.py:282-299.
  - ``enemy_ad_share`` / ``enemy_ap_share`` at 0.5 / 0.5 IS the planner's
    own default (core/build_order.py:574-575), so the neutral split is not
    forwarded into ``rank_kwargs`` - that keeps the no-seam dispatch
    byte-identical while a real comp split gets through.
  - No new import of the in-process engine in routes_state.py (guard
    tests/test_ds_preview_e2e_p1l21.py:191).
"""
from __future__ import annotations

import json
import unittest
from unittest import mock

from dashboard.routes_state import _serve_ds_preview_post


# --- fixtures -------------------------------------------------------------
# Handler stub mirrors tests/test_routes_ds_preview_scorer.py:21.

class _Handler:
    """Stub HTTP handler capturing the single ``_send`` the route makes."""

    def __init__(self) -> None:
        self.status: int = 0
        self.body: bytes = b""
        self.content_type: str = ""

    def _send(self, status: int, body: bytes, content_type: str) -> None:
        self.status = status
        self.body = body
        self.content_type = content_type

    def json(self) -> dict:
        return json.loads(self.body.decode())


def _dispatcher_response() -> dict:
    return {
        "ok": True, "scorer": "dps", "archetype": "carry",
        "ranked": [
            {"item_id": "3078", "item_name": "Trinity Force", "delta": 60.0,
             "gold": 3333, "shares_dead_unique": False, "dead_unique_key": ""},
            {"item_id": "3074", "item_name": "Ravenous Hydra", "delta": 50.0,
             "gold": 3300, "shares_dead_unique": False, "dead_unique_key": ""},
        ],
        "fell_back": False,
    }


class _Stats:
    """Duck-typed EnemyStats stub - mirrors tests/test_build_order.py:419
    and adds the two damage-share fields the real dataclass carries."""

    def __init__(self, armor=80.0, mr=30.0, max_hp=2000.0, bonus_hp=500.0,
                 ad_share=None, ap_share=None):
        self.armor = armor
        self.mr = mr
        self.max_hp = max_hp
        self.bonus_hp = bonus_hp
        if ad_share is not None:
            self.ad_share = ad_share
        if ap_share is not None:
            self.ap_share = ap_share


# Every seam name the dispatcher exposes. Used by the no-op pins to prove
# nothing new leaked into a default call.
_SEAM_KEYS = (
    "exempt_offclass_by_win", "prefer_kit_axis_by_win", "cost_ceiling",
    "prefer_survivability_by_win", "score_by", "assume_magic_burst",
    "assume_passive_as_stacks", "apply_target_vuln",
    "assume_missing_hp_heal_amp", "widen_carry_pool",
    "enemy_ad_share", "enemy_ap_share",
    # TRI-STATE seam (see the tri-state block below). Listed here so every
    # existing no-op pin also proves it stays ABSENT on a seam-free call -
    # "absent" is the only value that means "inherit the engine default".
    "apply_squishy_burst_target",
)


# ===========================================================================
# DEFECT 1 - /api/ds-preview seam reachability
# ===========================================================================
class DsPreviewSeamForwardingTests(unittest.TestCase):

    @mock.patch("core.daemon_slayer_client.rank_for_primary_archetype")
    @mock.patch("core.archetype_picks.get_archetype_for")
    def test_body_seam_flag_reaches_the_ranker(self, m_arch, m_rk):
        """A boolean seam in the POST body arrives as a ranker kwarg."""
        m_arch.return_value = {"primary": "carry"}
        m_rk.return_value = _dispatcher_response()
        h = _Handler()
        _serve_ds_preview_post(h, {
            "champion": "Ezreal", "mode": "SR", "level": 11,
            "prefer_kit_axis_by_win": True,
        })
        self.assertEqual(h.status, 200)
        kwargs = m_rk.call_args.kwargs
        self.assertIs(kwargs.get("prefer_kit_axis_by_win"), True)

    @mock.patch("core.daemon_slayer_client.rank_for_primary_archetype")
    @mock.patch("core.archetype_picks.get_archetype_for")
    def test_body_widen_carry_pool_and_cost_ceiling_reach_the_ranker(
            self, m_arch, m_rk):
        """Non-boolean coercion: cost_ceiling arrives as an int."""
        m_arch.return_value = {"primary": "carry"}
        m_rk.return_value = _dispatcher_response()
        h = _Handler()
        _serve_ds_preview_post(h, {
            "champion": "Ezreal", "mode": "SR", "level": 11,
            "widen_carry_pool": True, "cost_ceiling": "2800",
        })
        self.assertEqual(h.status, 200)
        kwargs = m_rk.call_args.kwargs
        self.assertIs(kwargs.get("widen_carry_pool"), True)
        self.assertEqual(kwargs.get("cost_ceiling"), 2800)
        self.assertIsInstance(kwargs.get("cost_ceiling"), int)

    @mock.patch("core.daemon_slayer_client.rank_for_primary_archetype")
    @mock.patch("core.archetype_picks.get_archetype_for")
    def test_body_score_by_whitelisted_value_forwarded(self, m_arch, m_rk):
        m_arch.return_value = {"primary": "tank"}
        m_rk.return_value = _dispatcher_response()
        h = _Handler()
        _serve_ds_preview_post(h, {
            "champion": "Malphite", "mode": "SR", "level": 11,
            "score_by": "team_blended",
        })
        self.assertEqual(h.status, 200)
        self.assertEqual(m_rk.call_args.kwargs.get("score_by"), "team_blended")

    @mock.patch("core.daemon_slayer_client.rank_for_primary_archetype")
    @mock.patch("core.archetype_picks.get_archetype_for")
    def test_body_score_by_garbage_is_dropped_not_forwarded(self, m_arch, m_rk):
        """An unknown score_by must not reach the engine (whitelist)."""
        m_arch.return_value = {"primary": "tank"}
        m_rk.return_value = _dispatcher_response()
        h = _Handler()
        _serve_ds_preview_post(h, {
            "champion": "Malphite", "mode": "SR", "level": 11,
            "score_by": "drop table items",
        })
        self.assertEqual(h.status, 200)
        self.assertNotIn("score_by", m_rk.call_args.kwargs)

    @mock.patch("core.daemon_slayer_client.rank_for_primary_archetype")
    @mock.patch("core.archetype_picks.get_archetype_for")
    def test_body_enemy_shares_reach_the_ranker(self, m_arch, m_rk):
        """The probe trap: POST /rank ignores the shares, the archetype
        route consumes them - so the dashboard must be able to send them."""
        m_arch.return_value = {"primary": "tank"}
        m_rk.return_value = _dispatcher_response()
        h = _Handler()
        _serve_ds_preview_post(h, {
            "champion": "Malphite", "mode": "SR", "level": 11,
            "enemy_ad_share": 0.8, "enemy_ap_share": 0.2,
        })
        self.assertEqual(h.status, 200)
        kwargs = m_rk.call_args.kwargs
        self.assertAlmostEqual(kwargs.get("enemy_ad_share"), 0.8)
        self.assertAlmostEqual(kwargs.get("enemy_ap_share"), 0.2)

    @mock.patch("core.daemon_slayer_client.rank_for_primary_archetype")
    @mock.patch("core.archetype_picks.get_archetype_for")
    def test_flagless_request_kwargs_are_byte_identical(self, m_arch, m_rk):
        """REGRESSION PIN: a body with no seam keys must produce exactly
        the pre-fix kwarg set - no additions, no removals, no defaults
        leaking through as explicit values."""
        m_arch.return_value = {"primary": "carry"}
        m_rk.return_value = _dispatcher_response()
        h = _Handler()
        _serve_ds_preview_post(h, {
            "champion": "Ezreal", "mode": "SR", "level": 11,
            "target_armor": 80.0, "target_mr": 30.0,
            "target_max_hp": 2000.0, "target_bonus_hp": 500.0,
        })
        self.assertEqual(h.status, 200)
        self.assertEqual(m_rk.call_args.args, ())
        self.assertEqual(m_rk.call_args.kwargs, {
            "champion": "Ezreal",
            "archetype": "carry",
            "level": 11,
            "item_ids": [],
            "mode": "SR",
            "top": 8,
            "sort_by": "delta",
            "timeout": 2.0,
            "target_armor": 80.0,
            "target_mr": 30.0,
            "target_max_hp": 2000.0,
            "target_bonus_hp": 500.0,
        })

    @mock.patch("core.daemon_slayer_client.rank_for_primary_archetype")
    @mock.patch("core.archetype_picks.get_archetype_for")
    def test_falsy_seam_values_in_body_are_not_forwarded(self, m_arch, m_rk):
        """Explicit False / null must stay OFF *and* stay absent, so a
        client that echoes its whole state back does not change the call."""
        m_arch.return_value = {"primary": "carry"}
        m_rk.return_value = _dispatcher_response()
        h = _Handler()
        _serve_ds_preview_post(h, {
            "champion": "Ezreal", "mode": "SR", "level": 11,
            "prefer_kit_axis_by_win": False,
            "widen_carry_pool": False,
            "cost_ceiling": None,
            "score_by": "blended",
        })
        self.assertEqual(h.status, 200)
        for key in _SEAM_KEYS:
            self.assertNotIn(key, m_rk.call_args.kwargs)


# ===========================================================================
# TRI-STATE seam - apply_squishy_burst_target
#
# Every other seam on the route is a default-FALSE boolean, so the universal
# "forward only non-default values" idiom (`if flag: kwargs[key] = True`) can
# express its whole range. apply_squishy_burst_target defaults TRUE in the
# engine (core/daemon_slayer_client.py:1410), so that idiom physically cannot
# express turning it OFF - which is exactly why the seam was left off
# /api/ds-preview. The route therefore treats it as tri-state:
#   absent / null -> kwarg OMITTED  (inherit the engine's True default)
#   true          -> kwarg True     (force ON)
#   false         -> kwarg False    (force OFF - the previously unreachable state)
# Malformed values are dropped, same contract as every other seam.
# ===========================================================================
class DsPreviewSquishyBurstTristateTests(unittest.TestCase):

    _PIN_BODY = {
        "champion": "Ezreal", "mode": "SR", "level": 11,
        "target_armor": 80.0, "target_mr": 30.0,
        "target_max_hp": 2000.0, "target_bonus_hp": 500.0,
    }
    _PIN_KWARGS = {
        "champion": "Ezreal",
        "archetype": "carry",
        "level": 11,
        "item_ids": [],
        "mode": "SR",
        "top": 8,
        "sort_by": "delta",
        "timeout": 2.0,
        "target_armor": 80.0,
        "target_mr": 30.0,
        "target_max_hp": 2000.0,
        "target_bonus_hp": 500.0,
    }

    @mock.patch("core.daemon_slayer_client.rank_for_primary_archetype")
    @mock.patch("core.archetype_picks.get_archetype_for")
    def test_absent_key_keeps_kwargs_byte_identical(self, m_arch, m_rk):
        """PIN EXTENSION: the tri-state seam must not weaken
        test_flagless_request_kwargs_are_byte_identical. Omitting the key
        means INHERIT, so the kwarg set stays exactly the pre-fix one."""
        m_arch.return_value = {"primary": "carry"}
        m_rk.return_value = _dispatcher_response()
        h = _Handler()
        _serve_ds_preview_post(h, dict(self._PIN_BODY))
        self.assertEqual(h.status, 200)
        self.assertEqual(m_rk.call_args.args, ())
        self.assertEqual(m_rk.call_args.kwargs, self._PIN_KWARGS)
        self.assertNotIn("apply_squishy_burst_target", m_rk.call_args.kwargs)

    @mock.patch("core.daemon_slayer_client.rank_for_primary_archetype")
    @mock.patch("core.archetype_picks.get_archetype_for")
    def test_json_null_keeps_kwargs_byte_identical(self, m_arch, m_rk):
        """Explicit JSON null is the wire spelling of "inherit" - a client
        echoing its whole state back with the knob unset changes nothing."""
        m_arch.return_value = {"primary": "carry"}
        m_rk.return_value = _dispatcher_response()
        h = _Handler()
        body = dict(self._PIN_BODY)
        body["apply_squishy_burst_target"] = None
        _serve_ds_preview_post(h, body)
        self.assertEqual(h.status, 200)
        self.assertEqual(m_rk.call_args.kwargs, self._PIN_KWARGS)

    @mock.patch("core.daemon_slayer_client.rank_for_primary_archetype")
    @mock.patch("core.archetype_picks.get_archetype_for")
    def test_true_forces_the_seam_on(self, m_arch, m_rk):
        m_arch.return_value = {"primary": "carry"}
        m_rk.return_value = _dispatcher_response()
        h = _Handler()
        body = dict(self._PIN_BODY)
        body["apply_squishy_burst_target"] = True
        _serve_ds_preview_post(h, body)
        self.assertEqual(h.status, 200)
        self.assertIs(
            m_rk.call_args.kwargs.get("apply_squishy_burst_target"), True)

    @mock.patch("core.daemon_slayer_client.rank_for_primary_archetype")
    @mock.patch("core.archetype_picks.get_archetype_for")
    def test_false_forces_the_seam_off(self, m_arch, m_rk):
        """THE DEFECT: before the tri-state, no /api/ds-preview body could
        produce this kwarg at all - the truthiness idiom drops False."""
        m_arch.return_value = {"primary": "carry"}
        m_rk.return_value = _dispatcher_response()
        h = _Handler()
        body = dict(self._PIN_BODY)
        body["apply_squishy_burst_target"] = False
        _serve_ds_preview_post(h, body)
        self.assertEqual(h.status, 200)
        kwargs = m_rk.call_args.kwargs
        self.assertIn("apply_squishy_burst_target", kwargs)
        self.assertIs(kwargs["apply_squishy_burst_target"], False)

    @mock.patch("core.daemon_slayer_client.rank_for_primary_archetype")
    @mock.patch("core.archetype_picks.get_archetype_for")
    def test_malformed_values_are_dropped_not_coerced(self, m_arch, m_rk):
        """A malformed seam must never 500 the preview and must never
        silently resolve to ON or OFF - it is dropped, i.e. inherited.
        Ints are deliberately NOT accepted: 0/1 is too easy to send by
        accident from a client that means "unset"."""
        m_arch.return_value = {"primary": "carry"}
        m_rk.return_value = _dispatcher_response()
        for bad in ("maybe", "", 0, 1, [], {}, 2.5):
            with self.subTest(bad=bad):
                m_rk.reset_mock()
                m_rk.return_value = _dispatcher_response()
                h = _Handler()
                body = dict(self._PIN_BODY)
                body["apply_squishy_burst_target"] = bad
                _serve_ds_preview_post(h, body)
                self.assertEqual(h.status, 200)
                self.assertNotIn(
                    "apply_squishy_burst_target", m_rk.call_args.kwargs)

    @mock.patch("core.daemon_slayer_client.rank_for_primary_archetype")
    @mock.patch("core.archetype_picks.get_archetype_for")
    def test_string_booleans_are_accepted(self, m_arch, m_rk):
        """Query-string / form-shaped clients send "true" / "false" as
        strings; those are unambiguous, so they parse."""
        m_arch.return_value = {"primary": "carry"}
        m_rk.return_value = _dispatcher_response()
        for raw, expected in (("true", True), ("False", False)):
            with self.subTest(raw=raw):
                m_rk.reset_mock()
                m_rk.return_value = _dispatcher_response()
                h = _Handler()
                body = dict(self._PIN_BODY)
                body["apply_squishy_burst_target"] = raw
                _serve_ds_preview_post(h, body)
                self.assertEqual(h.status, 200)
                self.assertIs(
                    m_rk.call_args.kwargs.get("apply_squishy_burst_target"),
                    expected)


# ===========================================================================
# DEFECT 2 - with_build_order seam divergence
# ===========================================================================
class BuildOrderSeamThreadingTests(unittest.TestCase):
    """The headline: RANK and PLAN must agree on every seam."""

    @staticmethod
    def _planner_calls(m_rk):
        """Ranker calls made by plan_build_order (all but the flat one)."""
        return [c.kwargs for c in m_rk.call_args_list[1:]]

    @mock.patch("core.daemon_slayer_client.rank_for_primary_archetype")
    @mock.patch("core.archetype_picks.get_archetype_for")
    def test_prefer_kit_axis_reaches_rank_and_plan(self, m_arch, m_rk):
        """prefer_kit_axis_by_win DEFAULTS ON in dispatch_for_coach. The
        flat ranking got it; the planner did not. Both must now."""
        from coach_integration.archetype_dispatch import dispatch_for_coach
        m_arch.return_value = {"primary": "carry"}
        m_rk.return_value = _dispatcher_response()
        res = dispatch_for_coach(
            "Ezreal", mode_engine="SR", level=11, item_ids=[],
            enemy_stats=_Stats(), with_build_order=True, build_order_slots=6,
        )
        self.assertIsNotNone(res)
        flat = m_rk.call_args_list[0].kwargs
        self.assertIs(flat.get("prefer_kit_axis_by_win"), True)
        planner = self._planner_calls(m_rk)
        self.assertTrue(planner, "planner made no ranker call")
        for kw in planner:
            self.assertIs(
                kw.get("prefer_kit_axis_by_win"), True,
                "planner ranked WITHOUT the seam the flat dispatch used",
            )

    @mock.patch("core.daemon_slayer_client.rank_for_primary_archetype")
    @mock.patch("core.archetype_picks.get_archetype_for")
    def test_rank_and_plan_agree_on_every_seam(self, m_arch, m_rk):
        """Turn on the whole seam set; assert both sides carry the same
        value for each one."""
        from coach_integration.archetype_dispatch import dispatch_for_coach
        m_arch.return_value = {"primary": "carry"}
        m_rk.return_value = _dispatcher_response()
        res = dispatch_for_coach(
            "Ezreal", mode_engine="SR", level=11, item_ids=[],
            enemy_stats=_Stats(ad_share=0.7, ap_share=0.3),
            with_build_order=True, build_order_slots=6,
            exempt_offclass_by_win=True,
            prefer_kit_axis_by_win=True,
            cost_ceiling=2800,
            prefer_survivability_by_win=True,
            assume_magic_burst=True,
            assume_passive_as_stacks=True,
            apply_target_vuln=True,
            assume_missing_hp_heal_amp=True,
            widen_carry_pool=True,
        )
        self.assertIsNotNone(res)
        flat = m_rk.call_args_list[0].kwargs
        planner = self._planner_calls(m_rk)
        self.assertTrue(planner, "planner made no ranker call")
        for kw in planner:
            for key in _SEAM_KEYS:
                if key in flat:
                    self.assertEqual(
                        kw.get(key), flat[key],
                        f"seam {key} diverges: rank={flat[key]!r} "
                        f"plan={kw.get(key)!r}",
                    )

    @mock.patch("core.daemon_slayer_client.rank_for_primary_archetype")
    @mock.patch("core.archetype_picks.get_archetype_for")
    def test_enemy_shares_reach_plan_build_order_rank_kwargs(
            self, m_arch, m_rk):
        """The planner used to receive only the four target_* stats, so a
        heavy-AD comp never reached the ordered build or its boots pick."""
        from coach_integration.archetype_dispatch import dispatch_for_coach
        m_arch.return_value = {"primary": "tank"}
        m_rk.return_value = _dispatcher_response()
        with mock.patch("core.build_order.plan_build_order") as m_plan:
            m_plan.return_value = None
            dispatch_for_coach(
                "Malphite", mode_engine="SR", level=11, item_ids=[],
                enemy_stats=_Stats(ad_share=0.75, ap_share=0.25),
                with_build_order=True,
            )
        self.assertEqual(m_plan.call_count, 1)
        rank_kwargs = m_plan.call_args.kwargs.get("rank_kwargs") or {}
        self.assertAlmostEqual(rank_kwargs.get("enemy_ad_share"), 0.75)
        self.assertAlmostEqual(rank_kwargs.get("enemy_ap_share"), 0.25)

    @mock.patch("core.daemon_slayer_client.rank_for_primary_archetype")
    @mock.patch("core.archetype_picks.get_archetype_for")
    def test_noop_pin_all_seams_off_forwards_nothing_new(self, m_arch, m_rk):
        """NO-OP PIN: seams off + the neutral 0.5/0.5 damage split (which
        IS the planner's own default) forwards no new ranker kwarg, so the
        pre-fix planner call shape is preserved exactly."""
        from coach_integration.archetype_dispatch import dispatch_for_coach
        m_arch.return_value = {"primary": "carry"}
        m_rk.return_value = _dispatcher_response()
        res = dispatch_for_coach(
            "Ezreal", mode_engine="SR", level=11, item_ids=[],
            enemy_stats=_Stats(), with_build_order=True, build_order_slots=6,
            prefer_kit_axis_by_win=False,
        )
        self.assertIsNotNone(res)
        planner = self._planner_calls(m_rk)
        self.assertTrue(planner, "planner made no ranker call")
        for kw in planner:
            for key in _SEAM_KEYS:
                self.assertNotIn(key, kw)

    @mock.patch("core.daemon_slayer_client.rank_for_primary_archetype")
    @mock.patch("core.archetype_picks.get_archetype_for")
    def test_noop_pin_rank_kwargs_absent_or_empty_when_seams_off(
            self, m_arch, m_rk):
        """Same pin at the plan_build_order boundary."""
        from coach_integration.archetype_dispatch import dispatch_for_coach
        m_arch.return_value = {"primary": "carry"}
        m_rk.return_value = _dispatcher_response()
        with mock.patch("core.build_order.plan_build_order") as m_plan:
            m_plan.return_value = None
            dispatch_for_coach(
                "Ezreal", mode_engine="SR", level=11, item_ids=[],
                enemy_stats=_Stats(), with_build_order=True,
                prefer_kit_axis_by_win=False,
            )
        self.assertEqual(m_plan.call_count, 1)
        self.assertFalse(m_plan.call_args.kwargs.get("rank_kwargs") or {})

    @mock.patch("core.daemon_slayer_client.rank_for_primary_archetype")
    @mock.patch("core.archetype_picks.get_archetype_for")
    def test_planner_no_double_unique_rule_survives_rank_kwargs(
            self, m_arch, m_rk):
        """core/build_order.py:618 re-pins filter_shared_uniques=True AFTER
        splatting caller rank_kwargs. Prove threading seams cannot weaken
        the no-double-unique rule."""
        from coach_integration.archetype_dispatch import dispatch_for_coach
        m_arch.return_value = {"primary": "carry"}
        m_rk.return_value = _dispatcher_response()
        dispatch_for_coach(
            "Ezreal", mode_engine="SR", level=11, item_ids=[],
            enemy_stats=_Stats(ad_share=0.7, ap_share=0.3),
            with_build_order=True, build_order_slots=6,
            prefer_kit_axis_by_win=True, widen_carry_pool=True,
        )
        planner = self._planner_calls(m_rk)
        self.assertTrue(planner)
        for kw in planner:
            self.assertIs(kw.get("filter_shared_uniques"), True)

    @mock.patch("core.daemon_slayer_client.rank_for_primary_archetype")
    @mock.patch("core.archetype_picks.get_archetype_for")
    def test_caster_missing_hp_pct_reaches_plan(self, m_arch, m_rk):
        """R5 self-HP is derived in dispatch_for_coach; the planner must
        see the same derived value, not a fresh default."""
        from coach_integration.archetype_dispatch import dispatch_for_coach
        m_arch.return_value = {"primary": "enchanter"}
        m_rk.return_value = _dispatcher_response()
        with mock.patch("core.build_order.plan_build_order") as m_plan:
            m_plan.return_value = None
            dispatch_for_coach(
                "Soraka", mode_engine="SR", level=11, item_ids=[],
                enemy_stats=_Stats(), with_build_order=True,
                assume_missing_hp_heal_amp=True,
                caster_hp=400.0, caster_hp_max=1600.0,
            )
        rank_kwargs = m_plan.call_args.kwargs.get("rank_kwargs") or {}
        self.assertIs(rank_kwargs.get("assume_missing_hp_heal_amp"), True)
        self.assertAlmostEqual(rank_kwargs.get("caster_missing_hp_pct"), 0.75)


if __name__ == "__main__":
    unittest.main()
