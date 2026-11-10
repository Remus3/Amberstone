"""S144-T-701 - core/damage_mix.py true-audit (lane 8, s144 cycle 267).

Each class pins one finding with a fake snapshot and a fake DS engine
(monkeypatched ``compute_ability_dps`` / ``compute_dps``), so the cache and
validation contract is tested without the live DS data:

  1. target_armor / target_mr were not in the cache key: a call with other
     targets was served the first call's mix, flagged cached=True.
  2. The snapshot was not in the cache key: a reloaded (or different)
     snapshot was served the old snapshot's mix for up to 60 s.
  3. level accepted bool / float / NaN / str: True read as level 1, 1.5 was
     computed at 1.5 but cached under level 1, NaN raised from int().
  4. A non-finite or negative engine number broke the "ratios sum to 1.0"
     docstring contract (NaN total, mix all zero, or a ratio above 1).
  5. The cached DamageMix carried a plain dict: one caller mutating
     ``mix.mix`` poisoned every later cache hit.
  6. The cache had no size bound inside the TTL window.
  7. resolve_champ_id took non-ASCII digits as a Riot key.
  8. normalize_items iterated a bare string per character and consumed an
     unbounded iterable before applying the six-item cap.
"""
from __future__ import annotations

import itertools
import math
import unittest
from dataclasses import dataclass, field
from unittest import mock

from core import damage_mix as dm


class _FakeSnap:
    def __init__(self, patch: str = "t-patch") -> None:
        self.patch = patch
        self.champions = {"Garen": {"key": "86"}, "Lux": {"key": "99"}}
        self.items = {"1001": {}, "3078": {}, "3153": {}}


@dataclass
class _Spell:
    damage_type: object
    dps: float


@dataclass
class _Abil:
    per_spell: tuple


@dataclass
class _Aa:
    weighted_dps: float
    per_attack_on_hit_damage: float = 0.0
    stats: dict = field(default_factory=lambda: {"as": 1.0})


class _EngineCase(unittest.TestCase):
    """Patches the two DS engine calls with recorders."""

    spells: tuple = (_Spell("MAGIC", 10.0),)
    aa_dps: float = 30.0
    on_hit: float = 0.0
    attack_speed: float = 1.0

    def setUp(self) -> None:
        dm.clear_cache()
        self.calls: list[tuple] = []

        def _abil(snapshot, cid, level, **kw):
            self.calls.append(("abil", id(snapshot), cid, level,
                               kw.get("target_armor"), kw.get("target_mr")))
            return _Abil(per_spell=tuple(self.spells))

        def _aa(snapshot, cid, level, **kw):
            return _Aa(weighted_dps=self.aa_dps,
                       per_attack_on_hit_damage=self.on_hit,
                       stats={"as": self.attack_speed})

        p1 = mock.patch.object(dm, "compute_ability_dps", _abil)
        p2 = mock.patch.object(dm, "compute_dps", _aa)
        p1.start()
        p2.start()
        self.addCleanup(p1.stop)
        self.addCleanup(p2.stop)
        self.addCleanup(dm.clear_cache)


class TargetsInCacheKeyTests(_EngineCase):
    def test_other_targets_are_not_served_the_cached_mix(self):
        snap = _FakeSnap()
        _, c1 = dm.compute_damage_mix(snap, "Garen", [], level=11)
        _, c2 = dm.compute_damage_mix(snap, "Garen", [], level=11,
                                      target_armor=0.0, target_mr=0.0)
        self.assertFalse(c1)
        self.assertFalse(c2, "different targets must miss the cache")
        self.assertEqual(len([c for c in self.calls if c[0] == "abil"]), 2)

    def test_same_targets_still_hit(self):
        snap = _FakeSnap()
        dm.compute_damage_mix(snap, "Garen", [], target_armor=5, target_mr=5)
        _, cached = dm.compute_damage_mix(snap, "Garen", [],
                                          target_armor=5.0, target_mr=5.0)
        self.assertTrue(cached, "5 and 5.0 are the same target")

    def test_non_finite_target_is_refused(self):
        snap = _FakeSnap()
        for bad in (math.nan, math.inf, -math.inf, "70", None, True):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                dm.compute_damage_mix(snap, "Garen", [], target_armor=bad)
            with self.subTest(bad=bad, which="mr"), \
                    self.assertRaises(ValueError):
                dm.compute_damage_mix(snap, "Garen", [], target_mr=bad)


class SnapshotInCacheKeyTests(_EngineCase):
    def test_reloaded_snapshot_misses_the_cache(self):
        old = _FakeSnap("16.1.1")
        new = _FakeSnap("16.2.1")
        dm.compute_damage_mix(old, "Garen", [])
        _, cached = dm.compute_damage_mix(new, "Garen", [])
        self.assertFalse(cached, "a different snapshot must recompute")

    def test_two_live_snapshots_keep_their_own_entries(self):
        a = _FakeSnap("16.1.1")
        b = _FakeSnap("16.2.1")
        dm.compute_damage_mix(a, "Garen", [])
        dm.compute_damage_mix(b, "Garen", [])
        _, ca = dm.compute_damage_mix(a, "Garen", [])
        _, cb = dm.compute_damage_mix(b, "Garen", [])
        self.assertTrue(ca and cb, "alternating snapshots must not evict "
                                   "each other's slot")

    def test_recycled_id_slot_is_not_served(self):
        snap = _FakeSnap()
        other = _FakeSnap()
        mix, _ = dm.compute_damage_mix(other, "Garen", [])
        # Re-file the entry under snap's identity, as id() reuse would.
        with dm._MIX_LOCK:
            (k, e), = dm._MIX_CACHE.items()
            dm._MIX_CACHE.clear()
            dm._MIX_CACHE[(id(snap),) + tuple(k[1:])] = e
        _, cached = dm.compute_damage_mix(snap, "Garen", [])
        self.assertFalse(cached, "an entry bound to another snapshot "
                                 "object must never be served")


class LevelValidationTests(_EngineCase):
    def test_non_int_levels_are_refused(self):
        snap = _FakeSnap()
        for bad in (True, False, 1.5, 11.0, math.nan, "11", None, 0, 19, -1):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                dm.compute_damage_mix(snap, "Garen", [], level=bad)
        self.assertEqual(self.calls, [], "no engine call on a bad level")

    def test_bounds_are_accepted(self):
        snap = _FakeSnap()
        for good in (1, 18):
            mix, _ = dm.compute_damage_mix(snap, "Garen", [], level=good)
            self.assertEqual(mix.level, good)

    def test_non_str_mode_is_refused(self):
        snap = _FakeSnap()
        for bad in (None, 1, b"SR", ""):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                dm.compute_damage_mix(snap, "Garen", [], mode=bad)


class NonFiniteEngineNumbersTests(_EngineCase):
    def _mix(self):
        return dm.compute_damage_mix(_FakeSnap(), "Garen", [],
                                     use_cache=False)[0]

    def _assert_contract(self, m):
        for name in ("physical_dps", "magical_dps", "true_dps",
                     "on_hit_dps", "total_dps"):
            v = getattr(m, name)
            self.assertTrue(math.isfinite(v) and v >= 0.0, (name, v))
        for k, v in m.mix.items():
            self.assertTrue(math.isfinite(v) and 0.0 <= v <= 1.0, (k, v))
        if m.total_dps > 0:
            self.assertAlmostEqual(sum(m.mix.values()), 1.0, delta=1e-9)

    def test_nan_spell_dps_is_dropped(self):
        self.spells = (_Spell("MAGIC", math.nan), _Spell("PHYSICAL", 5.0))
        m = self._mix()
        self._assert_contract(m)
        self.assertEqual(m.magical_dps, 0.0)
        self.assertGreater(m.total_dps, 0.0)

    def test_inf_spell_dps_is_dropped(self):
        self.spells = (_Spell("TRUE", math.inf),)
        m = self._mix()
        self._assert_contract(m)
        self.assertEqual(m.true_dps, 0.0)

    def test_negative_spell_dps_is_dropped(self):
        self.spells = (_Spell("MAGIC", -50.0),)
        m = self._mix()
        self._assert_contract(m)
        self.assertEqual(m.magical_dps, 0.0)

    def test_non_finite_aa_numbers(self):
        for aa, oh, aspd in ((math.nan, 0.0, 1.0), (30.0, math.nan, 1.0),
                             (30.0, 5.0, math.inf), (math.inf, 0.0, 1.0)):
            self.aa_dps, self.on_hit, self.attack_speed = aa, oh, aspd
            with self.subTest(aa=aa, oh=oh, aspd=aspd):
                self._assert_contract(self._mix())

    def test_finite_channels_whose_sum_overflows(self):
        self.spells = (_Spell("PHYSICAL", 1e308), _Spell("MAGIC", 1e308))
        m = self._mix()
        self._assert_contract(m)

    def test_non_str_damage_type_is_dropped_not_raised(self):
        self.spells = (_Spell(7, 10.0), _Spell(None, 10.0),
                       _Spell("MAGIC", 4.0))
        m = self._mix()
        self.assertEqual(m.magical_dps, 4.0)


class CachedMixIsImmutableTests(_EngineCase):
    def test_caller_mutation_cannot_poison_the_cache(self):
        snap = _FakeSnap()
        first, _ = dm.compute_damage_mix(snap, "Garen", [])
        before = dict(first.mix)
        with self.assertRaises(TypeError):
            first.mix["physical"] = 99.0  # type: ignore[index]
        second, cached = dm.compute_damage_mix(snap, "Garen", [])
        self.assertTrue(cached)
        self.assertEqual(dict(second.mix), before)
        self.assertEqual(second.to_dict()["mix"], {
            k: round(v, 6) for k, v in before.items()})


class CacheSizeBoundTests(_EngineCase):
    def test_cache_never_exceeds_its_bound(self):
        snap = _FakeSnap()
        bound = dm.MAX_CACHE_ENTRIES
        for i in range(bound + 25):
            dm.compute_damage_mix(snap, "Garen", [], target_armor=float(i))
        with dm._MIX_LOCK:
            self.assertLessEqual(len(dm._MIX_CACHE), bound)
        # The newest entry survives eviction.
        _, cached = dm.compute_damage_mix(
            snap, "Garen", [], target_armor=float(bound + 24))
        self.assertTrue(cached)


class ResolveChampIdTests(unittest.TestCase):
    def test_non_ascii_digits_are_not_a_key(self):
        snap = _FakeSnap()
        # U+0668 U+0666 is Arabic-Indic "86"; int() accepts it.
        for bad in ("\u0668\u0666", "\uff18\uff16"):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                dm.resolve_champ_id(snap, bad)

    def test_superscript_digit_raises_our_value_error(self):
        snap = _FakeSnap()
        with self.assertRaisesRegex(ValueError, "unknown champ"):
            dm.resolve_champ_id(snap, "\u00b2")

    def test_ascii_key_and_string_id_still_resolve(self):
        snap = _FakeSnap()
        self.assertEqual(dm.resolve_champ_id(snap, 86), "Garen")
        self.assertEqual(dm.resolve_champ_id(snap, " 99 "), "Lux")
        self.assertEqual(dm.resolve_champ_id(snap, "Garen"), "Garen")


class NormalizeItemsTests(unittest.TestCase):
    def test_bare_string_is_refused(self):
        snap = _FakeSnap()
        for bad in ("3078", b"3078"):
            with self.subTest(bad=bad), \
                    self.assertRaisesRegex(ValueError, "iterable of item ids"):
                dm.normalize_items(snap, bad)

    def test_unbounded_iterable_is_capped_without_draining(self):
        snap = _FakeSnap()
        pulled = []

        def _src():
            # Bounded stand-in for an endless stream (a real
            # itertools.cycle would hang the old code forever).
            for i in itertools.repeat("1001", 100_000):
                pulled.append(i)
                yield i

        with self.assertRaisesRegex(ValueError, "too many items"):
            dm.normalize_items(snap, _src())
        self.assertLessEqual(len(pulled), dm.MAX_ITEMS + 1,
                             "the cap must stop pulling at item seven")

    def test_six_items_and_blanks_still_pass(self):
        snap = _FakeSnap()
        got = dm.normalize_items(snap, ["1001", " ", 3078, "", "3153"] +
                                 ["1001"] * 3)
        self.assertEqual(got, ("1001", "3078", "3153", "1001", "1001",
                               "1001"))


if __name__ == "__main__":
    unittest.main()
