"""RM-118 residual: the four EHP SURVIVABILITY seams reach their routes.

THE DEFECT
----------
``test_stranded_hsp_seam_r197.py::STRANDED_TODAY`` ledgers 22 engine seams that
``server.py`` neither parses nor forwards. Four of them are the same defect class
R197 / RM-118 fixed for ``assume_hsp_amp``: the ENGINE half shipped complete,
with a live consumer and a live registry, and the ROUTE wire was simply never
added - so no coach tick, no operator curl and no Python client could arm them.

  * ``assume_passive_flat_mitigation`` (1.148.0, R9) - the per-instance FLAT
    damage-block the PERCENT mitigation registry excluded (Fizz P, Amumu E,
    Leona W), folded into the EHP numerator by
    ``_passive_flat_mitigation_overrides.flat_mitigation_hp``.
  * ``assume_passive_health_stacks`` (R46) - permanent bonus max HP from a
    stacking passive (Sion W, Cho'Gath R, Swain P) via
    ``_passive_health_overrides.passive_health_stack_hp``.
  * ``assume_item_revive`` (1.195.0) - the ITEM lane of the death-triggered
    second life (Guardian Angel 3026 Rebirth = 50 percent of BASE health).
  * ``assume_item_stasis`` (1.196.0) - the ITEM lane of the cast-triggered
    self-stasis window (Zhonya's Hourglass 3157, Seeker's Armguard 2420,
    Wooglet's Witchcap 228002).

WHY THESE FOUR AND NOT THE OTHER EIGHTEEN
-----------------------------------------
The ledger is not uniform debt. Ten entries are DECLINED BY DESIGN, not
undrained: the five target/caster-STATE assumptions belong to the
conditional-target-state arc the operator CLOSED at s232, and the five per-item
shield opt-ins each carry an operator-gated live default-ON flip in
``docs/LIVE_GAME_GATED_SYNC.md``. Wiring either group would re-open a closed
decision. Three more (``apply_ability_hsp_amp``,
``apply_cast_rate_propensity_prior``, ``apply_crit_chance_overrides``) are
flagged in the ledger itself as needing their own measured slice. The remaining
five (the three rune lanes plus the two R193/R194 vamp lanes) reach a DIFFERENT
route family - ``compute_dps`` / ``compute_hybrid`` / ``rank_items_by_hybrid`` -
so they are a separate edit pass on ``server.py``, not this one.

The four here share ONE engine module (``ehp.py``) and therefore one coherent
route pass, and every one already has its TRANSPORT on the route: the two
champion-keyed registries need only ``champion`` + ``level``, and the two
item-keyed ones need only ``items`` - all four parsed by ``/ehp`` since Phase 1.
Nothing here is reachable-and-dead (the RM-115 failure mode).

ROUTE OWNERSHIP IS PER-SEAM, NOT PER-FAMILY (reference_ds_seam_reachability_per_route)
-------------------------------------------------------------------------------------
Measured off ``inspect.signature``, not assumed:

  * ``assume_passive_flat_mitigation`` is on ``compute_ehp`` (ehp.py:1372) AND
    ``rank_items_by_ehp`` (ehp.py:3127) -> BOTH ``/ehp`` and ``/rank-tank``.
  * the other three are on ``compute_ehp`` ONLY -> ``/ehp`` alone.

So the flat-mitigation wire is the one that can change an item CHOICE, and the
other three stay reporting-only until their ranker half exists. Emitting any of
the three from ``rank_tank_for`` would manufacture a key ``_route_rank_tank``
does not parse - asserted against below rather than left to convention.

DEFAULT-OFF
-----------
All four default False on every engine entry point, so an omitted body key is a
byte-identical route response. Measured below, not asserted in prose.

OFFLINE ONLY: no live :8893, no network. Direct handler + engine + client calls.
"""
from __future__ import annotations

import inspect
import unittest
from unittest import mock

import core.daemon_slayer_client as client_mod
from agents.daemon_slayer import server
from agents.daemon_slayer.data_loader import DataSnapshot
from agents.daemon_slayer.ehp import compute_ehp, rank_items_by_ehp
from agents.daemon_slayer.tests.test_route_seams_reach_the_client_per_route import (
    _client_by_route,
    _route_table,
)
from agents.daemon_slayer.tests.test_stranded_hsp_seam_r197 import (
    STRANDED_TODAY,
    stranded_seams,
)

_FLAT_MIT = "assume_passive_flat_mitigation"
_HP_STACKS = "assume_passive_health_stacks"
_ITEM_REVIVE = "assume_item_revive"
_ITEM_STASIS = "assume_item_stasis"

# Every seam this slice wires, and the route(s) each one reaches.
_SEAMS = (_FLAT_MIT, _HP_STACKS, _ITEM_REVIVE, _ITEM_STASIS)
# The three that reach the SCALAR route only - rank_items_by_ehp has no such
# parameter, so /rank-tank must NOT grow these keys.
_EHP_ONLY = (_HP_STACKS, _ITEM_REVIVE, _ITEM_STASIS)

_LEVEL = 13
# Probe hygiene (reference_ds_probe_empty_build_artifact): never an empty build.
_SUNFIRE, _WARMOGS = "3068", "3083"
_PREFIX = (_SUNFIRE, _WARMOGS)
_GUARDIAN_ANGEL = "3026"   # assume_item_revive transport
_ZHONYAS = "3157"          # assume_item_stasis transport
_RANDUINS = "3143"         # ranker row whose delta the flat-mit credit raises

# Registry members - the champions each champion-keyed seam actually credits.
_FLAT_MIT_CHAMPS = ("Amumu", "Leona", "Fizz")
_HP_STACK_CHAMPS = ("Sion", "Chogath", "Swain")
# In NEITHER registry, so it is the invariant control for both.
_OFF_REGISTRY = "Sett"

_SNAP = None


def _snap() -> DataSnapshot:
    global _SNAP
    if _SNAP is None:
        _SNAP = DataSnapshot.load()
    return _SNAP


def _ehp_body(champion: str, items=_PREFIX, **extra) -> dict:
    body = {
        "champion": champion,
        "level": _LEVEL,
        "items": list(items),
        "mode": "SR",
        "enemy_ad_share": 0.5,
        "enemy_ap_share": 0.5,
    }
    body.update(extra)
    return body


def _tank_body(champion: str, **extra) -> dict:
    body = _ehp_body(champion)
    body["top"] = 200
    body.update(extra)
    return body


def _rank(champion: str, **kwargs):
    return rank_items_by_ehp(
        _snap(),
        champion_id=champion,
        level=_LEVEL,
        current_item_ids=list(_PREFIX),
        mode="SR",
        enemy_ad_share=0.5,
        enemy_ap_share=0.5,
        # No truncation (reference_ds_probe_depth_top40_truncation).
        top_n=None,
        **kwargs,
    )


def _order(result) -> tuple[str, ...]:
    return tuple(r.item_id for r in result.ranked)


def _legacy_rows(result) -> tuple[tuple, ...]:
    """Every pre-existing row field, in order - the byte-identical contract."""
    return tuple(
        (r.item_id, r.gold, r.delta_ehp, r.new_ehp, r.ehp_per_1k_gold,
         r.cc_blended_ehp, r.delta_cc_blended_ehp, r.survivability_score,
         r.team_blended_ehp, r.delta_team_blended_ehp,
         r.delta_sustain_ehp, r.delta_armor, r.delta_mr)
        for r in result.ranked
    )


def _route_delta(result_dict: dict, item_id: str) -> float:
    for r in result_dict["ranked"]:
        if r["item_id"] == item_id:
            return r["delta_ehp"]
    raise AssertionError(f"{item_id} not in route ranked")


class _Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        server._CACHE.set(_snap())


class EngineSeamExposureTests(_Base):
    """Gate 1: the engine half - already shipped, pinned so it cannot regress."""

    def test_compute_ehp_exposes_all_four_default_off(self) -> None:
        params = inspect.signature(compute_ehp).parameters
        for seam in _SEAMS:
            with self.subTest(seam=seam):
                self.assertIn(seam, params)
                self.assertIs(
                    params[seam].default, False,
                    f"{seam} must ship DEFAULT-OFF - a True default would move "
                    "every shipped EHP number at once",
                )

    def test_only_flat_mitigation_reaches_the_ranker(self) -> None:
        """The scope pin the per-route guard exists to protect.

        ``rank_items_by_ehp`` names exactly ONE of the four. If a later slice
        adds a second, THIS assertion goes red and points at the route wire that
        now needs to grow with it - the alternative is a route key silently
        dropped before the engine call (the R194 parse-without-pass shape).
        """
        params = inspect.signature(rank_items_by_ehp).parameters
        self.assertIn(_FLAT_MIT, params)
        self.assertIs(params[_FLAT_MIT].default, False)
        for seam in _EHP_ONLY:
            with self.subTest(seam=seam):
                self.assertNotIn(
                    seam, params,
                    f"{seam} grew a ranker lane - wire it into _route_rank_tank "
                    "and rank_tank_for in the same slice, then relax this pin",
                )


class ScalarRouteDefaultOffTests(_Base):
    """Omitting a key must give a byte-identical ``/ehp`` response."""

    def test_absent_key_equals_explicit_false(self) -> None:
        for seam in _SEAMS:
            with self.subTest(seam=seam):
                self.assertEqual(
                    server._route_ehp(_ehp_body(_OFF_REGISTRY)),
                    server._route_ehp(_ehp_body(_OFF_REGISTRY, **{seam: False})),
                )

    def test_all_four_together_are_byte_identical_off(self) -> None:
        explicit = dict.fromkeys(_SEAMS, False)
        self.assertEqual(
            server._route_ehp(_ehp_body("Leona")),
            server._route_ehp(_ehp_body("Leona", **explicit)),
        )


class ScalarRouteFlipMovesTests(_Base):
    """Measured OFF/ON per seam - named champion, level and inventory."""

    def _blended(self, champion: str, items=_PREFIX, **extra) -> float:
        return server._route_ehp(_ehp_body(champion, items, **extra))["blended_ehp"]

    def test_flat_mitigation_moves_every_registry_champion(self) -> None:
        for champ in _FLAT_MIT_CHAMPS:
            with self.subTest(champion=champ):
                self.assertGreater(
                    self._blended(champ, **{_FLAT_MIT: True}),
                    self._blended(champ),
                    f"{_FLAT_MIT} was parsed but never reached compute_ehp",
                )

    def test_flat_mitigation_amumu_is_the_measured_pair(self) -> None:
        # Amumu, level 13, SR, Sunfire + Warmog's. flat_mitigation_hp returns
        # (66.0, 0.0, 0.0) for him - a PHYSICAL-only block, so the credit is
        # asymmetric across damage types rather than a uniform lift.
        off = server._route_ehp(_ehp_body("Amumu"))
        on = server._route_ehp(_ehp_body("Amumu", **{_FLAT_MIT: True}))
        self.assertGreater(on["physical_ehp"], off["physical_ehp"])
        self.assertEqual(on["magical_ehp"], off["magical_ehp"])

    def test_health_stacks_moves_every_registry_champion(self) -> None:
        for champ in _HP_STACK_CHAMPS:
            with self.subTest(champion=champ):
                self.assertGreater(
                    self._blended(champ, **{_HP_STACKS: True}),
                    self._blended(champ),
                    f"{_HP_STACKS} was parsed but never reached compute_ehp",
                )

    def test_item_revive_moves_only_with_guardian_angel(self) -> None:
        with_ga = _PREFIX + (_GUARDIAN_ANGEL,)
        self.assertGreater(
            self._blended(_OFF_REGISTRY, with_ga, **{_ITEM_REVIVE: True}),
            self._blended(_OFF_REGISTRY, with_ga),
            f"{_ITEM_REVIVE} was parsed but never reached compute_ehp",
        )

    def test_item_stasis_moves_only_with_zhonyas(self) -> None:
        with_zhonyas = _PREFIX + (_ZHONYAS,)
        self.assertGreater(
            self._blended("Vladimir", with_zhonyas, **{_ITEM_STASIS: True}),
            self._blended("Vladimir", with_zhonyas),
            f"{_ITEM_STASIS} was parsed but never reached compute_ehp",
        )


class ScalarRouteInvariantTests(_Base):
    """The other half of honesty: ON must be a NO-OP off its registry."""

    def _blended(self, champion: str, items=_PREFIX, **extra) -> float:
        return server._route_ehp(_ehp_body(champion, items, **extra))["blended_ehp"]

    def test_champion_keyed_seams_are_inert_off_registry(self) -> None:
        for seam in (_FLAT_MIT, _HP_STACKS):
            with self.subTest(seam=seam):
                self.assertEqual(
                    self._blended(_OFF_REGISTRY, **{seam: True}),
                    self._blended(_OFF_REGISTRY),
                    f"{seam} credited a champion that is not in its registry",
                )

    def test_item_keyed_seams_are_inert_without_their_item(self) -> None:
        for seam in (_ITEM_REVIVE, _ITEM_STASIS):
            with self.subTest(seam=seam):
                self.assertEqual(
                    self._blended(_OFF_REGISTRY, **{seam: True}),
                    self._blended(_OFF_REGISTRY),
                    f"{seam} credited a build that owns no registered item",
                )


class RankerRouteTests(_Base):
    """``/rank-tank``: the lane where the flat-mit credit changes a CHOICE."""

    def test_absent_key_is_byte_identical(self) -> None:
        self.assertEqual(
            server._route_rank_tank(_tank_body("Leona")),
            server._route_rank_tank(_tank_body("Leona", **{_FLAT_MIT: False})),
        )

    def test_route_forwards_the_seam(self) -> None:
        off = server._route_rank_tank(_tank_body("Leona"))
        on = server._route_rank_tank(_tank_body("Leona", **{_FLAT_MIT: True}))
        self.assertGreater(
            _route_delta(on, _RANDUINS), _route_delta(off, _RANDUINS),
            f"{_FLAT_MIT} was parsed but never reached rank_items_by_ehp",
        )

    def test_engine_default_path_is_byte_identical(self) -> None:
        omitted = _rank("Leona")
        explicit = _rank("Leona", **{_FLAT_MIT: False})
        self.assertEqual(_order(omitted), _order(explicit))
        self.assertEqual(_legacy_rows(omitted), _legacy_rows(explicit))

    def test_the_order_actually_moves_for_a_registry_champion(self) -> None:
        # Leona, level 13, SR, Sunfire + Warmog's prefix over the full 137-row
        # pool: her W flat block raises the physical numerator, and the rows that
        # buy armor gain relatively more from it than the pure-MR rows do.
        off = _rank("Leona")
        on = _rank("Leona", **{_FLAT_MIT: True})
        self.assertNotEqual(
            _order(off), _order(on),
            "the credit raised a delta but reordered nothing - it must be able "
            "to change WHICH item ranks where, not just a row value",
        )

    def test_off_registry_champion_is_wholly_invariant(self) -> None:
        off = _rank(_OFF_REGISTRY)
        on = _rank(_OFF_REGISTRY, **{_FLAT_MIT: True})
        self.assertEqual(_order(off), _order(on))
        self.assertEqual(_legacy_rows(off), _legacy_rows(on))


class ClientWiringTests(_Base):
    """Gate 3: the client functions must be able to express what they POST."""

    def test_ehp_for_names_all_four_default_off(self) -> None:
        params = inspect.signature(client_mod.ehp_for).parameters
        for seam in _SEAMS:
            with self.subTest(seam=seam):
                self.assertIn(seam, params)
                self.assertIs(params[seam].default, False)

    def test_rank_tank_for_names_only_flat_mitigation(self) -> None:
        params = inspect.signature(client_mod.rank_tank_for).parameters
        self.assertIn(_FLAT_MIT, params)
        self.assertIs(params[_FLAT_MIT].default, False)
        for seam in _EHP_ONLY:
            with self.subTest(seam=seam):
                self.assertNotIn(
                    seam, params,
                    f"rank_tank_for can express {seam}, which _route_rank_tank "
                    "does not parse - a key that dies on the wire",
                )

    def _sent(self, fn, **kwargs) -> dict:
        seen: dict = {}

        def _fake(path, body, timeout=0.0):
            seen["path"] = path
            seen["body"] = body
            return {"ranked": []}

        with mock.patch.object(client_mod, "_post_json", _fake):
            fn(_OFF_REGISTRY, level=_LEVEL, item_ids=list(_PREFIX), **kwargs)
        return seen

    def test_ehp_for_emits_only_when_armed(self) -> None:
        bare = self._sent(client_mod.ehp_for)
        self.assertEqual(bare["path"], "/ehp")
        for seam in _SEAMS:
            with self.subTest(seam=seam):
                self.assertNotIn(seam, bare["body"])
                armed = self._sent(client_mod.ehp_for, **{seam: True})
                self.assertIs(armed["body"][seam], True)

    def test_rank_tank_for_emits_only_when_armed(self) -> None:
        bare = self._sent(client_mod.rank_tank_for)
        self.assertEqual(bare["path"], "/rank-tank")
        self.assertNotIn(_FLAT_MIT, bare["body"])
        armed = self._sent(client_mod.rank_tank_for, **{_FLAT_MIT: True})
        self.assertIs(armed["body"][_FLAT_MIT], True)


class PerRouteStrandedSeamTests(_Base):
    """PER-(route, seam), never name-collapsed."""

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.parsed, _ = _route_table()
        cls.client = _client_by_route()

    def test_scalar_pairs_are_parsed_and_expressible(self) -> None:
        for seam in _SEAMS:
            with self.subTest(seam=seam, route="/ehp"):
                self.assertIn(seam, self.parsed["/ehp"])
                self.assertIn(seam, self.client["/ehp"])

    def test_ranker_pair_is_parsed_and_expressible(self) -> None:
        self.assertIn(_FLAT_MIT, self.parsed["/rank-tank"])
        self.assertIn(_FLAT_MIT, self.client["/rank-tank"])

    def test_ranker_does_not_parse_the_scalar_only_seams(self) -> None:
        for seam in _EHP_ONLY:
            with self.subTest(seam=seam):
                self.assertNotIn(seam, self.parsed["/rank-tank"])


class StrandedLedgerTests(_Base):
    """The debt ledger can only shrink - these four must have left it."""

    def test_the_four_are_no_longer_stranded(self) -> None:
        stranded = stranded_seams(_server_source())
        for seam in _SEAMS:
            with self.subTest(seam=seam):
                self.assertNotIn(seam, stranded)
                self.assertNotIn(
                    seam, STRANDED_TODAY,
                    "the seam is wired - delete its STRANDED_TODAY entry so the "
                    "ledger keeps shrinking",
                )


def _server_source() -> str:
    import pathlib
    return pathlib.Path(server.__file__).read_text(encoding="utf-8")


if __name__ == "__main__":
    unittest.main()
