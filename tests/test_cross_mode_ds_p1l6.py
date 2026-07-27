# arch: P1-L6 cross-mode Daemon Slayer integration contract tests | section=coaching | frozen=no
"""Cross-mode Daemon Slayer integration correctness (audit P1-L6).

Lane: the four live-game coaches (SR via ``coach_integration/_coach.py``,
ARAM via ``coaches/aram_coach.py``, Arena via ``coaches/arena_coach.py``,
Brawl via ``coaches/brawl_coach.py``) inject scorer-aware DS picks before
each Haiku call via ``coach_integration/archetype_dispatch.py`` and
preserve the legacy ``daemon_slayer_picks`` payload shape for dashboard
compat.

The P1-L6 audit found the integration VERIFIED-CORRECT. These are
characterization / contract tests pinning the behaviour so a regression
(a mode bypassing the dispatcher, a divergent picks shape, an ARAM
multiplier dropped or leaking into SR, the Arena Arcane Sweeper /
Galeforce / 22-prefix-alias rules not holding) is caught.

Three groups:

1. Dispatch shape contract - the ``display_rows`` payload that becomes
   ``daemon_slayer_picks`` has an identical, back-compatible schema
   regardless of mode/scorer (a single dashboard consumer must not
   break per mode). Property-style over every scorer.
2. Mode-specific correctness against the real DS engine - ARAM
   ``aramDamageDealt`` / ``aramDamageTaken`` are actually applied;
   Arena strips the Arcane Sweeper trinket and keeps Galeforce on
   map 30; the byName -> 22-prefix alias resolves per mode.
3. No cross-mode leakage - ARAM modifiers do not bleed into SR;
   Arena-only pool rules do not affect ARAM/SR/Brawl.

Engine-touching tests use the real patch-current snapshot (same as the
DS suite). Dispatcher-shape tests mock at the
``rank_for_primary_archetype`` boundary - no live :8893 server.

No hardcoded magic numbers for engine outputs; no fragile cross-item
comparison assertions. ARAM-multiplier assertions read the modifier the
engine itself loaded from the snapshot and assert the *relationship*
(ratio == that modifier), so the test stays correct across patches.
"""
from __future__ import annotations

import unittest
from unittest import mock

from coach_integration.archetype_dispatch import (
    CoachDispatchResult,
    dispatch_for_coach,
)


# Legacy daemon_slayer_picks schema the dashboard JS reads. The two new
# fields (delta, scorer) are additive; the 4 legacy keys must always be
# present with their legacy types.
_LEGACY_KEYS = ("id", "name", "delta_dps", "gold")
_NEW_KEYS = ("delta", "scorer")
_ALL_SCORERS = ("dps", "ehp", "hybrid", "ability", "burst", "hps")


class _Stats:
    """Duck-typed coach_integration.enemy_stats.EnemyStats stub."""

    def __init__(self, armor=80.0, mr=40.0, max_hp=2000.0, bonus_hp=500.0):
        self.armor = armor
        self.mr = mr
        self.max_hp = max_hp
        self.bonus_hp = bonus_hp


def _resp(scorer: str, rows: list[dict]) -> dict:
    return {
        "ok": True,
        "scorer": scorer,
        "archetype": "carry" if scorer == "dps" else scorer,
        "ranked": rows,
        "fell_back": False,
    }


# A representative ranked row for every scorer, mirroring the real
# rank_for_primary_archetype payload (hybrid ships hybrid_delta_pct;
# others ship a unified ``delta``).
def _rows_for(scorer: str) -> list[dict]:
    if scorer == "hybrid":
        return [
            {"item_id": "3078", "item_name": "Trinity Force",
             "delta_dps": 18.5, "delta_ehp": 90.0,
             "hybrid_delta_pct": 0.08, "gold": 3333},
            {"item_id": "6333", "item_name": "Death's Dance",
             "delta_dps": 12.0, "delta_ehp": 150.0,
             "hybrid_delta_pct": 0.06, "gold": 3300},
        ]
    return [
        {"item_id": "3031", "item_name": "Infinity Edge",
         "delta": 250.0, "gold": 3500},
        {"item_id": "3094", "item_name": "Rapid Firecannon",
         "delta": 180.0, "gold": 2900},
    ]


class CrossModeDispatchShapeContractTests(unittest.TestCase):
    """The daemon_slayer_picks payload shape is identical + back-compat
    across all four modes and every scorer (one dashboard consumer)."""

    MODES = ("SR", "ARAM", "ARENA", "BRAWL")

    def _assert_legacy_shape(self, display_rows: list[dict], scorer: str):
        self.assertIsInstance(display_rows, list)
        for row in display_rows:
            for k in _LEGACY_KEYS:
                self.assertIn(k, row, f"missing legacy key {k!r}")
            for k in _NEW_KEYS:
                self.assertIn(k, row, f"missing new key {k!r}")
            self.assertIsInstance(row["id"], str)
            self.assertIsInstance(row["name"], str)
            self.assertIsInstance(row["delta_dps"], float)
            self.assertIsInstance(row["delta"], float)
            self.assertIsInstance(row["gold"], int)
            self.assertEqual(row["scorer"], scorer)
            # Legacy delta_dps slot must carry the scorer's primary delta
            # (numerically equal to the new ``delta`` field) so old
            # readers see a value, new readers can disambiguate by scorer.
            self.assertEqual(row["delta_dps"], row["delta"])

    @mock.patch("core.daemon_slayer_client.rank_for_primary_archetype")
    @mock.patch("core.archetype_picks.get_archetype_for")
    def test_shape_identical_across_modes_and_scorers(self, mock_arch, mock_disp):
        for scorer in _ALL_SCORERS:
            arch = "carry" if scorer == "dps" else (
                "bruiser" if scorer == "hybrid" else scorer)
            mock_arch.return_value = {"primary": arch}
            mock_disp.return_value = _resp(scorer, _rows_for(scorer))
            shapes = []
            for mode in self.MODES:
                result = dispatch_for_coach(
                    "Caitlyn", mode_engine=mode, level=11,
                    item_ids=[], enemy_stats=_Stats(),
                )
                self.assertIsInstance(result, CoachDispatchResult)
                self._assert_legacy_shape(result.display_rows, scorer)
                # Key-set per row must be byte-identical across modes.
                shapes.append(
                    tuple(sorted(result.display_rows[0].keys()))
                )
            self.assertEqual(
                len(set(shapes)), 1,
                f"display_rows key-set diverged across modes for "
                f"scorer={scorer}: {shapes}",
            )

    @mock.patch("core.daemon_slayer_client.rank_for_primary_archetype")
    @mock.patch("core.archetype_picks.get_archetype_for")
    def test_engine_down_propagates_none_every_mode(self, mock_arch, mock_disp):
        """A mode must not paper over an engine-down with partial rows -
        all four propagate None identically (caller writes
        picks_str='unavailable' + skips calibration)."""
        mock_arch.return_value = {"primary": "carry"}
        mock_disp.return_value = None
        for mode in self.MODES:
            self.assertIsNone(
                dispatch_for_coach(
                    "Caitlyn", mode_engine=mode, level=11,
                    item_ids=[], enemy_stats=_Stats(),
                ),
                f"mode {mode} did not propagate engine-down as None",
            )

    @mock.patch("core.daemon_slayer_client.rank_for_primary_archetype")
    @mock.patch("core.archetype_picks.get_archetype_for")
    def test_mode_engine_string_forwarded_verbatim(self, mock_arch, mock_disp):
        """Each coach passes its own mode_engine through to the engine
        kwarg unchanged - the engine's per-mode item/modifier logic keys
        off exactly this string."""
        mock_arch.return_value = {"primary": "carry"}
        mock_disp.return_value = _resp("dps", _rows_for("dps"))
        for mode in self.MODES:
            dispatch_for_coach(
                "Caitlyn", mode_engine=mode, level=11,
                item_ids=[], enemy_stats=_Stats(),
            )
            self.assertEqual(mock_disp.call_args.kwargs["mode"], mode)


class CrossModeBrawlRoutingTests(unittest.TestCase):
    """Brawl is the umbrella for several modes. Only literal BRAWL is
    map 35; URF/OFA/NexusBlitz ride SR base item IDs + SR engine identity
    (no aram_modifiers, which is correct - those modes have no ARAM
    tweaks). Pin the static routers."""

    def test_resolver_and_engine_mode_split(self):
        from coaches.brawl_coach import Coach as BrawlCoach
        cases = {
            "BRAWL": ("brawl", "BRAWL"),
            "ULTBOOK": ("sr", "SR"),
            "NEXUSBLITZ": ("sr", "SR"),
            "GAMEMODEX": ("sr", "SR"),
            "": ("sr", "SR"),
        }
        for gm, (want_res, want_eng) in cases.items():
            self.assertEqual(BrawlCoach._ds_resolver_mode(gm), want_res)
            self.assertEqual(BrawlCoach._ds_engine_mode(gm), want_eng)

    def test_brawl_engine_mode_never_aram(self):
        """Regression guard: a Brawl variant must never resolve to ARAM
        engine mode (would wrongly apply aramDamageDealt)."""
        from coaches.brawl_coach import Coach as BrawlCoach
        for gm in ("BRAWL", "ULTBOOK", "NEXUSBLITZ", "GAMEMODEX",
                   "URF", "ONEFORALL", "", "weird"):
            self.assertNotEqual(BrawlCoach._ds_engine_mode(gm), "ARAM")


class AramModifierAppliedTests(unittest.TestCase):
    """ARAM aramDamageDealt (DPS side) / aramDamageTaken (EHP side) are
    actually applied by the engine and gated strictly on mode == 'ARAM'.

    Asserts the *relationship* using the modifier the engine loaded from
    the snapshot - patch-stable, no hardcoded numbers.
    """

    @classmethod
    def setUpClass(cls):
        from agents.daemon_slayer.data_loader import DataSnapshot
        cls.snap = DataSnapshot.load()

    def _champ_with(self, key: str):
        """First champion whose aram_modifiers[key] is a real != 1.0
        multiplier. Returns (champion_id, modifier_value)."""
        for cid, c in self.snap.champions.items():
            am = ((c.get("lolmath") or {}).get("aram_modifiers") or {})
            v = am.get(key)
            if v is not None and float(v) != 1.0:
                return cid, float(v)
        # The snapshot is TRACKED and ARAM balance always carries a large
        # non-unit cohort (MEASURED 2026-07-27: 101 champions for
        # aramDamageDealt, 102 for aramDamageTaken). An empty result means the
        # snapshot lost its aram_modifiers block - a data regression that must
        # fail, not silently retire both mode-gating tests below.
        self.fail(f"no champion with non-trivial {key} in the tracked snapshot")

    def test_aram_damage_dealt_applied_dps_layer(self):
        from agents.daemon_slayer import dps as dps_mod
        cid, mult = self._champ_with("aramDamageDealt")
        common = dict(item_ids=["3031"], target_armor=80.0, target_mr=40.0,
                      target_max_hp=2000.0, target_bonus_hp=500.0)
        sr = dps_mod.compute_dps(self.snap, cid, 11, mode="SR", **common)
        aram = dps_mod.compute_dps(self.snap, cid, 11, mode="ARAM", **common)
        # SR is unmodified; ARAM carries exactly the snapshot multiplier.
        self.assertEqual(sr.mode_multiplier, 1.0)
        self.assertAlmostEqual(aram.mode_multiplier, mult, places=6)
        self.assertGreaterEqual(sr.weighted_dps, 0.0)
        self.assertAlmostEqual(
            aram.weighted_dps / sr.weighted_dps, mult, places=4,
            msg="ARAM/SR DPS ratio must equal aramDamageDealt",
        )

    def test_aram_damage_taken_applied_ehp_layer(self):
        from agents.daemon_slayer import ehp as ehp_mod
        cid, mult = self._champ_with("aramDamageTaken")
        e_sr = ehp_mod.compute_ehp(self.snap, cid, 11, item_ids=[], mode="SR")
        e_ar = ehp_mod.compute_ehp(self.snap, cid, 11, item_ids=[], mode="ARAM")
        self.assertEqual(e_sr.mode_multiplier, 1.0)
        self.assertAlmostEqual(e_ar.mode_multiplier, mult, places=6)

    def test_aram_modifier_not_leaked_to_sr_or_brawl(self):
        """The defining no-leakage assertion: a champ with a non-1.0
        ARAM modifier still gets mode_multiplier == 1.0 in SR and in the
        Brawl-on-SR engine identity."""
        from agents.daemon_slayer import dps as dps_mod
        cid, _ = self._champ_with("aramDamageDealt")
        common = dict(item_ids=["3031"], target_armor=80.0, target_mr=40.0,
                      target_max_hp=2000.0, target_bonus_hp=500.0)
        for mode in ("SR", "BRAWL"):
            r = dps_mod.compute_dps(self.snap, cid, 11, mode=mode, **common)
            self.assertEqual(
                r.mode_multiplier, 1.0,
                f"ARAM damage multiplier leaked into mode={mode}",
            )


class ArenaItemPoolRuleTests(unittest.TestCase):
    """Arena-specific item rules hold and do not affect other modes:
      - Arcane Sweeper (3348) trinket stripped from current_item_ids
        only in ARENA; never elsewhere.
      - Arcane Sweeper is non-purchasable -> excluded from the candidate
        pool by _is_purchasable.
      - Galeforce (446671) is map-30-only via DDragon ``maps`` and is
        NOT denied globally; legal in ARENA, illegal in SR/ARAM.
    """

    @classmethod
    def setUpClass(cls):
        from agents.daemon_slayer.data_loader import DataSnapshot
        cls.snap = DataSnapshot.load()

    def test_arcane_sweeper_stripped_only_in_arena(self):
        from agents.daemon_slayer.rank import strip_arena_trinkets
        ids = ("3348", "3031", "1055")
        kept_arena, stripped_arena = strip_arena_trinkets(ids, "ARENA")
        self.assertNotIn("3348", kept_arena)
        self.assertIn("3348", stripped_arena)
        self.assertEqual(kept_arena, ("3031", "1055"))
        # Outside ARENA the function is a no-op - the rule must NOT leak.
        for mode in ("SR", "ARAM", "BRAWL"):
            kept, stripped = strip_arena_trinkets(ids, mode)
            self.assertEqual(kept, ids, f"trinket strip leaked into {mode}")
            self.assertEqual(stripped, ())

    def test_arcane_sweeper_not_purchasable(self):
        from agents.daemon_slayer.rank import _is_purchasable
        rec = self.snap.item("3348")
        self.assertFalse(
            _is_purchasable(rec),
            "Arcane Sweeper must be excluded from the candidate pool",
        )

    def test_galeforce_is_arena_map_only_not_global_denylist(self):
        from agents.daemon_slayer.rank import _is_legal_in_mode
        rec = self.snap.item("446671")
        # Legit ONLY on Arena map 30 - not deny-listed across the board.
        self.assertTrue(_is_legal_in_mode(rec, "ARENA"))
        self.assertFalse(_is_legal_in_mode(rec, "SR"))
        self.assertFalse(_is_legal_in_mode(rec, "ARAM"))

    def test_galeforce_ddragon_maps_block(self):
        rec = self.snap.item("446671")
        maps = rec.get("maps") or {}
        self.assertTrue(maps.get("30"))
        self.assertFalse(maps.get("11"))
        self.assertFalse(maps.get("12"))


class ByNameAliasPerModeTests(unittest.TestCase):
    """The items_index byName -> 22-prefixed alias quirk: mode-aware
    resolution returns the base ID for SR/ARAM/Brawl and the 22-prefix
    Arena alias only for Arena. Pin a known dual-mapped item."""

    def test_heartsteel_resolves_per_mode(self):
        from core import daemon_slayer_resolver as r
        sr_id = r.name_to_id("Heartsteel", mode="sr")
        arena_id = r.name_to_id("Heartsteel", mode="arena")
        aram_id = r.name_to_id("Heartsteel", mode="aram")
        brawl_id = r.name_to_id("Heartsteel", mode="brawl")
        self.assertEqual(sr_id, aram_id)
        self.assertEqual(sr_id, brawl_id)
        self.assertNotEqual(sr_id, arena_id)
        # The Arena alias is the 22-prefixed quirk; non-Arena is the
        # canonical 4-digit base id (the arena coach pins the alias on
        # purpose - that is correct, not a bug).
        self.assertTrue(arena_id.startswith("22"),
                         f"Arena alias expected 22-prefix, got {arena_id}")
        self.assertFalse(sr_id.startswith("22"))

    def test_galeforce_resolves_to_map30_id_in_arena(self):
        from core import daemon_slayer_resolver as r
        self.assertEqual(r.name_to_id("Galeforce", mode="arena"), "446671")

    def test_resolve_inventory_drops_non_inventory_in_all_modes(self):
        """SR coach uses resolve_inventory; trinket/consumable drop must
        behave the same regardless of the mode arg (orthogonal to the
        Arena trinket strip, which is engine-side)."""
        from core import daemon_slayer_resolver as r
        for mode in ("sr", "aram", "arena", "brawl"):
            ids = r.resolve_inventory(
                ["Infinity Edge", "Stealth Ward", "Health Potion"],
                mode=mode,
            )
            for banned in ("3340", "2003"):
                self.assertNotIn(banned, ids,
                                 f"{banned} not dropped for mode={mode}")


if __name__ == "__main__":
    unittest.main()
