"""RM-660: Arena BotRK 223153 Mist's Edge honours the current-HP lever.

Adjudicated 2026-10-22 (RM-660 ruling, W2-E slice). The SR row and its
Arena mirror model the SAME proc (DDragon names 3153 and 223153 the same
item), but only the SR row read the target-current-HP% seam:

  - SR 3153 (``_effects_data.py:603``):
    ``0.09 * c.target_max_hp * c.target_current_hp_pct``
  - Arena 223153 (``_effects_data.py:4520-4530``) carried
    ``0.09 * c.target_max_hp`` with no seam factor and a note saying
    "9% target max HP".

Seam ground truth (cited before writing this file):
  - ``CallContext.target_current_hp_pct: float = 1.0``
    (``_effects_types.py:137``); ``CallContext`` and ``ITEM_EFFECTS`` are
    re-exported by ``agents.daemon_slayer.effects`` (``effects.py:43-45``).
  - ``PeriodicProc.resolve_damage(ctx)`` (``_effects_types.py:262``).
  - ``compute_dps(snapshot, champion_id, level, item_ids, ...,
    target_max_hp, ..., target_current_hp_pct=1.0)`` (``dps.py:768-778``).
  - The d(p) harness mirrors ``test_target_current_hp_pct_lever.py:35-41``.
  - The pre-existing 223153 pin
    (``test_meraki_formula_audit_pipeline_a.py:186-192``) evaluates the
    proc at the default 1.0 and must stay green.

The seam stays default 1.0 (no default, flag or route is changed here),
so every live default-path result is byte-identical; only a caller that
passes a non-1.0 lever sees the Arena proc scale, exactly like SR.
"""

import unittest

from agents.daemon_slayer.data_loader import DataSnapshot
from agents.daemon_slayer.dps import compute_dps
from agents.daemon_slayer.effects import ITEM_EFFECTS, CallContext


_CHAMP = "Aatrox"
_LEVEL = 11
_TARGET_MAX_HP = 3000.0
_ARENA_BOTRK = "223153"
_SR_BOTRK = "3153"

# The ONLY ITEM_EFFECTS rows whose proc reads the current-HP lever after
# RM-660: the three SR current-HP procs plus the Arena BotRK mirror.
# Genuine %-MAX-HP procs (Eclipse 6692, Titanic 3748, Hullbreaker 223181,
# Azakana's Gaze, Reaper's Toll 443090) must never join this set.
_EXPECTED_LEVER_ROWS = frozenset({"3153", "223153", "4017", "443055"})

# Rows whose periodic raised on the fixed guard ctx, id -> reason. Empty
# at RM-660 (measured): a new raising row must be recorded here with its
# reason, never skipped silently.
_KNOWN_RAISING_ROWS: dict[str, str] = {}


def _dps(snap, item_id, *, target_current_hp_pct=1.0):
    """weighted_dps for the FIXED single-item build at the given lever."""
    return compute_dps(
        snap, _CHAMP, level=_LEVEL, item_ids=[item_id],
        target_max_hp=_TARGET_MAX_HP,
        target_current_hp_pct=target_current_hp_pct,
    ).weighted_dps


def _mists_edge(item_id):
    eff = ITEM_EFFECTS[item_id]
    procs = [p for p in eff.periodics if p.name == "Mist's Edge"]
    assert len(procs) == 1, f"{item_id} expected exactly one Mist's Edge"
    return procs[0]


def _ctx(p, *, target_max_hp=2500.0):
    return CallContext(
        base_ad=60.0, bonus_ad=0.0, level=11,
        target_max_hp=target_max_hp, target_current_hp_pct=p,
    )


class ArenaBotrkDefaultUnchangedTests(unittest.TestCase):
    """(a) the live default path (seam left at 1.0) is byte-identical."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = DataSnapshot.load()

    def test_default_dps_equals_explicit_one(self) -> None:
        base = compute_dps(
            self.snap, _CHAMP, level=_LEVEL, item_ids=[_ARENA_BOTRK],
            target_max_hp=_TARGET_MAX_HP,
        ).weighted_dps
        explicit_one = _dps(self.snap, _ARENA_BOTRK, target_current_hp_pct=1.0)
        self.assertEqual(base, explicit_one)

    def test_default_proc_equals_pre_rm660_formula(self) -> None:
        # Pre-RM-660 the row was exactly ``0.09 * c.target_max_hp``; at the
        # default lever the new row must reproduce it bit-for-bit.
        proc = _mists_edge(_ARENA_BOTRK)
        for hp in (0.0, 1000.0, 2500.0, 3000.0):
            with self.subTest(target_max_hp=hp):
                ctx = CallContext(
                    base_ad=60.0, bonus_ad=0.0, level=11, target_max_hp=hp,
                )
                self.assertEqual(proc.resolve_damage(ctx), 0.09 * hp)


class ArenaBotrkLeverScalesTests(unittest.TestCase):
    """(b) halving the lever halves the Arena proc's DPS contribution."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = DataSnapshot.load()

    def test_half_lever_halves_proc_magnitude(self) -> None:
        d_full = _dps(self.snap, _ARENA_BOTRK, target_current_hp_pct=1.0)
        d_half = _dps(self.snap, _ARENA_BOTRK, target_current_hp_pct=0.5)
        d_zero = _dps(self.snap, _ARENA_BOTRK, target_current_hp_pct=0.0)
        full_proc = d_full - d_zero
        half_proc = d_half - d_zero
        self.assertGreater(full_proc, 0.0)
        self.assertAlmostEqual(half_proc, full_proc * 0.5, places=6)


class ArenaBotrkMirrorParityTests(unittest.TestCase):
    """(c) the Arena proc resolves exactly like the SR proc at every lever."""

    def test_proc_is_9pct_of_current_hp(self) -> None:
        proc = _mists_edge(_ARENA_BOTRK)
        for p in (0.0, 0.25, 0.5, 1.0):
            with self.subTest(p=p):
                self.assertAlmostEqual(
                    proc.resolve_damage(_ctx(p)), 0.09 * 2500.0 * p, places=6,
                )

    def test_arena_proc_matches_sr_proc(self) -> None:
        arena = _mists_edge(_ARENA_BOTRK)
        sr = _mists_edge(_SR_BOTRK)
        for p in (0.0, 0.25, 0.5, 1.0):
            with self.subTest(p=p):
                self.assertEqual(
                    arena.resolve_damage(_ctx(p)), sr.resolve_damage(_ctx(p)),
                )


class LeverRowSetGuardTests(unittest.TestCase):
    """(d) tightest set: only the four current-HP rows move with the lever."""

    def test_only_current_hp_rows_read_the_lever(self) -> None:
        def ctx(p):
            return CallContext(
                base_ad=60.0, bonus_ad=0.0, level=11,
                target_max_hp=2500.0, caster_max_hp=2500.0,
                target_current_hp_pct=p,
            )

        self.assertGreater(len(ITEM_EFFECTS), 0)
        n_procs = 0
        moved: set[str] = set()
        raised: dict[str, str] = {}
        for item_id, eff in ITEM_EFFECTS.items():
            for proc in eff.periodics:
                n_procs += 1
                try:
                    full = proc.resolve_damage(ctx(1.0))
                    half = proc.resolve_damage(ctx(0.5))
                except Exception as exc:  # recorded, never silently skipped
                    raised[item_id] = f"{type(exc).__name__}: {exc}"
                    continue
                if full != half:
                    moved.add(item_id)
        # An empty enumeration must fail, not pass vacuously.
        self.assertGreater(n_procs, 0)
        self.assertEqual(raised, _KNOWN_RAISING_ROWS)
        self.assertEqual(moved, set(_EXPECTED_LEVER_ROWS))


if __name__ == "__main__":
    unittest.main()
