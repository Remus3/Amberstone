"""R160 - PERCENT penetration catalog parity, the axis R152 and R153 left
unguarded.

R152 closed the LETHALITY catalog (31 exact-match, 0 absent) and R153 closed
FLAT magic pen and shipped a permanent guard for it. Neither swept the PERCENT
axis, so ``ITEM_EFFECTS[...].armor_pen_pct`` / ``.magic_pen_pct`` had no
catalog-derived test at all: nothing in the repo would notice a future item
that states percent pen in prose and never gets registered.

Penetration has no generic stat path. ``stats.py`` ``ITEM_STAT_KEY_MAP``
carries 12 keys and none of them is a penetration key, and DDragon's structured
``stats`` block has no penetration entry either, so the magnitude survives only
inside the ``<stats>`` HTML or the passive prose of ``description`` and
``ITEM_EFFECTS`` is the SOLE credit path. An id absent from ``ITEM_EFFECTS``,
or present with the field omitted, silently reads 0.0.

WHAT THIS SWEEP FOUND, AS OF R161 (no live data bug, two holdout classes and
NEITHER of them is a magnitude divergence any more):

* Percent armor pen - 12 swept ids, 8 exact, 2 stacking-convention, 2 inert.
* Percent magic pen - 9 swept ids, 7 exact, 0 divergent, 2 inert.

R161 - THE ARENA-FEED DOCTRINE QUESTION IS ANSWERED. R160 shipped an
``_ARENA_FEED_DRIFT`` holdout for ``223036`` and ``226694``, which state 40
percent in the Arena feed while the registry credited their SR twins' 35
percent, and recorded the open question: do Arena mirrors inherit their SR
coefficients, or does an explicitly different DDragon stat line win? The
director answered DOCTRINE B - when a DDragon Arena mirror states its OWN
explicit stat line that differs from its SR twin, THE ARENA FEED VALUE WINS.
Both rows passed the plain parity assertion at 0.40 and the holdout is GONE,
along with the sibling escalations R152 recorded for its 7 lethality rows and
R153 pinned for ``223020`` / ``224645``. SR parents are untouched (``3036``
and ``6694`` stay 0.35).

DDragon 16.17.1 then moved ``226694`` alone to 45 percent (``223036`` held at
40, both SR twins held at 35), and the registry carried it: ``226694`` now
credits 0.45. Doctrine B is unchanged - the row still takes its OWN stated
Arena value, that value simply moved. Because the DS per-patch snapshot stays
PINNED at 16.15.1, the live and pinned catalogs now state different numbers
for this id; that divergence is recorded in ``_PINNED_CARRY_FORWARD`` and the
magnitude-parity assertions skip in any tree that lacks the live catalog. The inheritance-side guard in
``test_effects_expansion`` was inverted in the same slice and is now
``test_arena_serylda_armor_pen_diverges_from_sr``.

``_STACKING_FULL_STACK`` - Terminus. This one SURVIVES doctrine B because it
is a units convention, not a divergence: DDragon states a PER-STACK magnitude
(10 percent SR, 8 percent Arena) and never prints the 3-stack cap, while the
registry credits the full-stack steady state under the Black Cleaver / Guinsoo
convention. So a plain stated-equals-credited assertion is wrong by
construction on these two rows regardless of doctrine. Under R161 BOTH rows
derive from their OWN stated per-stack value times the cap - SR 10 x 3 = 0.30,
Arena 8 x 3 = 0.24 - so the Arena row no longer inherits anything.

``_INERT_DELISTED`` - ``6632`` / ``226632`` Divine Sunderer state 3 percent of
both pen axes in leftover ``{{ Item_Mythic_Passive }}`` text. They are the only
two items in all 706 still carrying that template token, and both are unmapped,
unpurchasable and out of the store, so the uncredited stat is inert rather than
a bug. Pinned WITH their unbuyable flags: if a patch ever re-lists one, this
test goes red instead of quietly shipping an item that is missing pen.

Ordering and composition are deliberately NOT re-asserted here.
``agents/daemon_slayer/tests/test_engine_math_correctness_pipeline_c.py``
already pins the four-stage
order, multiplicative composition on both axes, the zero floor and the negative
passthrough. Duplicating it would add maintenance and catch nothing.
"""

from __future__ import annotations

import json
import re
import unittest
from pathlib import Path

from agents.daemon_slayer._effects_data import ITEM_EFFECTS
from agents.daemon_slayer.effects import (
    effective_target_armor,
    effective_target_mr,
)

_REPO_ROOT = Path(__file__).resolve().parents[3]

# Two layouts carry the catalog - the live data/meta copy and the per-patch
# vendored snapshot - so resolve either. Both were verified to yield an
# identical swept set and identical magnitudes for all three regexes.
_META_CATALOG = _REPO_ROOT / "data" / "meta" / "ddragon_items.json"
_PATCH_ROOT = _REPO_ROOT / "data" / "daemon_slayer"


# Is the LIVE DDragon catalog present? ``data/meta/ddragon_items.json`` tracks
# live DDragon; the per-patch snapshot under ``data/daemon_slayer/<patch>/``
# is PINNED (16.15.1 today) and the registry deliberately runs AHEAD of it.
# RM-190 carried item 3175 ``magic_pen_flat`` 18 -> 20 out of the 16.16.1
# mirror while leaving the DS snapshot pinned, and 16.17.1 carried 226694
# ``armor_pen_pct`` 0.40 -> 0.45 the same way. So a magnitude-parity assertion
# is only meaningful against the LIVE catalog. Comparing the registry against
# the pinned snapshot instead measures it against a catalog it no longer
# describes and manufactures a FALSE failure. The swept SET is stable across
# the two layouts, so the population sweeps keep the fallback; magnitude
# parity demands the live catalog.
def _require_live_catalog(case: "unittest.TestCase") -> None:
    """Require the live catalog before a magnitude-parity assertion.

    FAILS rather than skips on absence. ``data/meta/ddragon_items.json`` is
    TRACKED, so its absence is a deleted committed file - a DEFECT that must
    fail loudly - and a skip keyed on it would be an always-passing guard
    (tests/test_skip_condition_hygiene.py, docs/SKIPIF_AUDIT_2026-07-27.md).
    """
    case.assertTrue(
        _META_CATALOG.is_file(), f"tracked {_META_CATALOG} is missing"
    )

# Percent only. The mandatory "%" before the closing tag is the exact
# mirror-image of R153's flat regex, whose digits must butt directly against
# the closing tag. That makes the two sweeps disjoint by MAGNITUDE - neither
# can ever capture the other's number - but NOT by id: 3175 states both a
# flat and a percent magic pen line, and is pinned below.
_PCT_ARMOR_ATTENTION_RE = re.compile(
    r"<attention>\s*(\d+(?:\.\d+)?)\s*%\s*</attention>\s*Armor Penetration"
)
_PCT_MAGIC_ATTENTION_RE = re.compile(
    r"<attention>\s*(\d+(?:\.\d+)?)\s*%\s*</attention>\s*Magic Penetration"
)
# Terminus authors its magnitude as bare passive prose in different markup,
# so the stat-block regex above cannot see it. Its magic pen shares the same
# number and is stated only as a trailing <scaleMR> clause, which is why the
# magic sweep has no prose form.
_PCT_ARMOR_PROSE_RE = re.compile(
    r"(\d+(?:\.\d+)?)%\s*<scaleArmor>Armor Penetration</scaleArmor>"
)

# item_id -> (percent stated PER STACK, percent credited at full stacks)
# The ONE surviving holdout class after R161: a units convention, not a
# magnitude divergence. Each row credits ITS OWN stated per-stack value
# times the 3-stack cap - no cross-map inheritance on either row.
_STACKING_FULL_STACK = {
    "3302": (10.0, 0.30),     # SR: 10 per stack x 3 == the credited 0.30
    "223302": (8.0, 0.24),    # Arena: its own 8 per stack x 3 == 0.24
}
_TERMINUS_STACK_CAP = 3

# Delisted, unbuyable on every map, sole survivors of the mythic-passive
# template. Uncredited on BOTH pen axes, and that is correct.
_INERT_DELISTED = ("6632", "226632")

# Ids where the LIVE data/meta catalog and the PINNED per-patch snapshot
# legitimately state different percentages, because Riot moved the magnitude
# after the DS snapshot was pinned and the registry carried the NEW value
# forward (a1 posture: carry the magnitude, do not bump the snapshot).
# Keyed by regex source -> {item_id: (live_stated, pinned_stated)}.
# ITEM_EFFECTS credits the LIVE value in every case.
_PINNED_CARRY_FORWARD = {
    # 16.17.1 moved Serylda's Grudge Arena armor pen 40 -> 45 while leaving
    # the SR twin 6694 at 35. Snapshot 16.15.1 still states 40.
    _PCT_ARMOR_ATTENTION_RE.pattern: {"226694": ("45", "40")},
}


def _catalog() -> dict:
    if _META_CATALOG.is_file():
        raw = _META_CATALOG.read_text(encoding="utf-8")
    else:
        patch = (_PATCH_ROOT / "current.txt").read_text(encoding="utf-8").strip()
        raw = (_PATCH_ROOT / patch / "items.json").read_text(encoding="utf-8")
    return json.loads(raw)["data"]


def _sweep(*patterns: re.Pattern) -> dict:
    """item_id -> (name, percent stated anywhere in the description)."""
    found = {}
    for iid, entry in _catalog().items():
        description = entry.get("description", "")
        for pattern in patterns:
            match = pattern.search(description)
            if match:
                found[iid] = (entry.get("name", ""), float(match.group(1)))
                break
    return found


def _swept_armor_pct() -> dict:
    return _sweep(_PCT_ARMOR_ATTENTION_RE, _PCT_ARMOR_PROSE_RE)


def _swept_magic_pct() -> dict:
    return _sweep(_PCT_MAGIC_ATTENTION_RE)


def _parity_mismatches(swept: dict, credited: dict) -> list:
    """(item_id, stated_percent, credited_fraction) for every divergent row.

    Kept as a free function taking its credited values as an argument so the
    detector itself can be tested against a deliberately perturbed input -
    a sweep that cannot fail is worse than no sweep.
    """
    mismatches = []
    for iid, (_name, stated) in sorted(swept.items()):
        got = credited.get(iid, 0.0)
        if abs(got - stated / 100.0) > 1e-6:
            mismatches.append((iid, stated, got))
    return mismatches


def _credited(swept: dict, field: str) -> dict:
    out = {}
    for iid in swept:
        effect = ITEM_EFFECTS.get(iid)
        out[iid] = 0.0 if effect is None else float(getattr(effect, field))
    return out


_HOLDOUTS = set(_STACKING_FULL_STACK) | set(_INERT_DELISTED)


class R160PercentPenPopulationTests(unittest.TestCase):
    """The swept populations, pinned so a DROPPED item is as loud as a new one."""

    def test_armor_pct_population(self) -> None:
        self.assertEqual(
            sorted(_swept_armor_pct()),
            sorted(
                [
                    "223033", "223036", "223302", "226632", "226694", "3033",
                    "3035", "3036", "3302", "4015", "6632", "6694",
                ]
            ),
        )

    def test_magic_pct_population(self) -> None:
        self.assertEqual(
            sorted(_swept_magic_pct()),
            sorted(
                [
                    "223135", "223137", "226632", "3135", "3137", "3175",
                    "4015", "4630", "6632",
                ]
            ),
        )

    def test_one_item_states_both_flat_and_percent_magic_pen(self) -> None:
        _require_live_catalog(self)
        # The two sweeps are disjoint by MAGNITUDE, not by id: the percent
        # regex requires a "%" the flat regex forbids, so neither can ever
        # capture the other's number. But an item may legitimately state
        # BOTH lines, and exactly one does - 3175 Spellslinger's Shoes,
        # "20 Magic Penetration" and "8% Magic Penetration" on consecutive
        # stat rows. DS credits both axes independently and correctly.
        # Pinned because a cross-fold (percent magnitude landing in the flat
        # term or the reverse) would be a real bug, and because a second such
        # item is exactly the shape that would slip past a single-axis sweep.
        from agents.daemon_slayer.tests.test_magic_pen_flat_catalog_r153 import (
            _swept_flat_magic_pen,
        )

        flat = _swept_flat_magic_pen()
        pct = _swept_magic_pct()
        self.assertEqual(sorted(set(flat) & set(pct)), ["3175"])
        self.assertAlmostEqual(flat["3175"][1], 20.0, places=3)
        self.assertAlmostEqual(pct["3175"][1], 8.0, places=3)
        effect = ITEM_EFFECTS["3175"]
        self.assertAlmostEqual(effect.magic_pen_flat, 20.0, places=3)
        self.assertAlmostEqual(effect.magic_pen_pct, 0.08, places=3)

    def test_both_catalog_layouts_agree(self) -> None:
        # The two layouts - the pinned per-patch snapshot and the live
        # data/meta catalog - agreed exactly until the DS snapshot fell behind
        # live DDragon: the snapshot is PINNED at 16.15.1 while data/meta
        # tracks live, so a magnitude Riot moves in between shows up in one
        # layout only. That is EXPECTED under the a1 posture (carry the
        # magnitude, leave the snapshot pinned), so this guard no longer
        # demands equality - it demands that every divergence is one of the
        # DOCUMENTED carry-forwards below. An undocumented divergence is real
        # drift and still goes red, and a carry-forward that disappears (a
        # snapshot bump that realigns the layouts) goes red too, so the list
        # cannot rot silently.
        patch = (_PATCH_ROOT / "current.txt").read_text(encoding="utf-8").strip()
        patch_file = _PATCH_ROOT / patch / "items.json"
        # Both layouts are TRACKED in the main repo - absence is a deleted
        # committed catalog, not a missing capability.
        self.assertTrue(_META_CATALOG.is_file(), f"tracked {_META_CATALOG} is missing")
        self.assertTrue(patch_file.is_file(), f"tracked {patch_file} is missing")
        meta = json.loads(_META_CATALOG.read_text(encoding="utf-8"))["data"]
        vendored = json.loads(patch_file.read_text(encoding="utf-8"))["data"]
        for pattern in (
            _PCT_ARMOR_ATTENTION_RE,
            _PCT_ARMOR_PROSE_RE,
            _PCT_MAGIC_ATTENTION_RE,
        ):
            with self.subTest(pattern=pattern.pattern):
                live = {
                    i: pattern.search(e["description"]).group(1)
                    for i, e in meta.items()
                    if pattern.search(e.get("description", ""))
                }
                pinned = {
                    i: pattern.search(e["description"]).group(1)
                    for i, e in vendored.items()
                    if pattern.search(e.get("description", ""))
                }
                diverged = {
                    i: (live.get(i), pinned.get(i))
                    for i in sorted(set(live) | set(pinned))
                    if live.get(i) != pinned.get(i)
                }
                self.assertEqual(
                    diverged,
                    _PINNED_CARRY_FORWARD.get(pattern.pattern, {}),
                    "live data/meta vs the pinned DS snapshot diverged on an "
                    "id that is not a documented carry-forward. Either a new "
                    "patch moved a percent-pen magnitude (carry it into "
                    "ITEM_EFFECTS and record it in _PINNED_CARRY_FORWARD), or "
                    "the DS snapshot was bumped and the entry is now stale.",
                )


class R160PercentPenParityTests(unittest.TestCase):
    """stated == credited on every row that is not a documented holdout."""

    def test_armor_pct_parity(self) -> None:
        _require_live_catalog(self)
        swept = {
            k: v for k, v in _swept_armor_pct().items() if k not in _HOLDOUTS
        }
        self.assertEqual(
            _parity_mismatches(swept, _credited(swept, "armor_pen_pct")), []
        )

    def test_magic_pct_parity(self) -> None:
        _require_live_catalog(self)
        swept = {
            k: v for k, v in _swept_magic_pct().items() if k not in _HOLDOUTS
        }
        self.assertEqual(
            _parity_mismatches(swept, _credited(swept, "magic_pen_pct")), []
        )

    def test_every_live_swept_item_carries_a_nonzero_credit(self) -> None:
        for field, swept in (
            ("armor_pen_pct", _swept_armor_pct()),
            ("magic_pen_pct", _swept_magic_pct()),
        ):
            for iid, (name, stated) in sorted(swept.items()):
                if iid in _INERT_DELISTED:
                    continue
                with self.subTest(field=field, item_id=iid, name=name):
                    effect = ITEM_EFFECTS.get(iid)
                    self.assertIsNotNone(
                        effect,
                        f"{iid} ({name}) states {stated} percent pen but has "
                        "no ITEM_EFFECTS entry",
                    )
                    self.assertGreater(
                        float(getattr(effect, field)),
                        0.0,
                        f"{iid} ({name}) states {stated} percent pen but "
                        f"credits 0.0 on {field}",
                    )

    def test_detector_is_not_hollow(self) -> None:
        # Perturb one real credit and prove the comparison reports exactly
        # that id. Without this, every assertion above could be vacuous.
        # Needs the LIVE catalog: the assertion is that the perturbed id is
        # the ONLY mismatch, which presumes a clean baseline. Against the
        # pinned snapshot the documented carry-forwards are already
        # mismatches, so the list would carry them too and this would fail
        # for a reason that has nothing to do with detector integrity.
        _require_live_catalog(self)
        swept = {
            k: v for k, v in _swept_armor_pct().items() if k not in _HOLDOUTS
        }
        credited = _credited(swept, "armor_pen_pct")
        self.assertIn("3035", credited)
        credited["3035"] = credited["3035"] + 0.05
        self.assertEqual(
            [row[0] for row in _parity_mismatches(swept, credited)], ["3035"]
        )

    def test_detector_reports_a_dropped_registration(self) -> None:
        # Same clean-baseline premise as test_detector_is_not_hollow.
        _require_live_catalog(self)
        swept = {
            k: v for k, v in _swept_armor_pct().items() if k not in _HOLDOUTS
        }
        credited = _credited(swept, "armor_pen_pct")
        credited["6694"] = 0.0
        self.assertEqual(
            [row[0] for row in _parity_mismatches(swept, credited)], ["6694"]
        )


class R160HeldDivergenceTests(unittest.TestCase):
    """The two surviving holdout classes, asserted so no silent drift.

    R161 removed the third (``_ARENA_FEED_DRIFT``): under doctrine B those
    rows credit their own feed and are covered by the plain parity tests.
    """

    def test_terminus_credits_the_full_stack_steady_state(self) -> None:
        swept = _swept_armor_pct()
        for iid, (per_stack, credited) in sorted(_STACKING_FULL_STACK.items()):
            with self.subTest(item_id=iid):
                self.assertAlmostEqual(swept[iid][1], per_stack, places=3)
                # Both pen axes share the one magnitude on this item.
                self.assertAlmostEqual(
                    ITEM_EFFECTS[iid].armor_pen_pct, credited, places=3
                )
                self.assertAlmostEqual(
                    ITEM_EFFECTS[iid].magic_pen_pct, credited, places=3
                )

    def test_terminus_sr_credit_equals_per_stack_times_cap(self) -> None:
        stated = _swept_armor_pct()["3302"][1]
        self.assertAlmostEqual(
            ITEM_EFFECTS["3302"].armor_pen_pct,
            stated / 100.0 * _TERMINUS_STACK_CAP,
            places=6,
        )

    def test_terminus_arena_credits_its_own_feed(self) -> None:
        # R161 doctrine B: the Arena row is derived STRUCTURALLY from its
        # own stated per-stack value times the cap (8 x 3), not copied
        # from SR. Derived rather than hardcoded so a per-stack or cap
        # change in a future patch lands here instead of drifting.
        feed_accurate = (
            _swept_armor_pct()["223302"][1] / 100.0 * _TERMINUS_STACK_CAP
        )
        self.assertAlmostEqual(feed_accurate, 0.24, places=6)
        for field in ("armor_pen_pct", "magic_pen_pct"):
            with self.subTest(field=field):
                self.assertAlmostEqual(
                    float(getattr(ITEM_EFFECTS["223302"], field)),
                    feed_accurate,
                    places=6,
                )
        # And it must now DIVERGE from the SR twin, which keeps its own
        # 10-per-stack derivation at 0.30.
        self.assertNotAlmostEqual(
            ITEM_EFFECTS["223302"].armor_pen_pct,
            ITEM_EFFECTS["3302"].armor_pen_pct,
            places=6,
        )

    def test_inert_delisted_rows_are_unbuyable_and_uncredited(self) -> None:
        catalog = _catalog()
        for iid in _INERT_DELISTED:
            with self.subTest(item_id=iid):
                entry = catalog[iid]
                self.assertFalse(
                    [k for k, v in entry.get("maps", {}).items() if v],
                    f"{iid} became available on a map - its 3 percent pen is "
                    "no longer inert and must be credited or re-adjudicated",
                )
                self.assertFalse(entry["gold"]["purchasable"])
                effect = ITEM_EFFECTS[iid]
                self.assertAlmostEqual(effect.armor_pen_pct, 0.0, places=3)
                self.assertAlmostEqual(effect.magic_pen_pct, 0.0, places=3)


class R160PercentPenConsumerTests(unittest.TestCase):
    """A credited field with no consumer is inert, so pin the consumers."""

    def test_armor_pct_reaches_the_armor_consumer(self) -> None:
        # 100 armor, 35 percent pen -> 65.
        self.assertAlmostEqual(
            effective_target_armor(100.0, [ITEM_EFFECTS["6694"]]),
            65.0,
            places=3,
        )

    def test_magic_pct_reaches_the_mr_consumer(self) -> None:
        # 100 MR, 40 percent pen -> 60.
        self.assertAlmostEqual(
            effective_target_mr(100.0, [ITEM_EFFECTS["3135"]]),
            60.0,
            places=3,
        )


if __name__ == "__main__":
    unittest.main()
