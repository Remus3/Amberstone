"""Alias / mode-mirror duplicate rejection in the build-ORDER planner (W3).

THE DEFECT (measured in the shipped tables at ENGINE 1.248.0 / patch 16.14.1)
---------------------------------------------------------------------------
``data/daemon_slayer/16.14.1/build_orders_sr.json`` shipped builds that buy the
SAME item twice under two different catalog ids, so the "six item build" is
really a five item build with one slot burned:

    Viego  (all 3 comp classes): 3153 3111 3004 3143 323004 3046
                                            ^^^^      ^^^^^^ both Manamune
    Samira (all 3 comp classes): 3031 3006 3036 6697 6676 667666
                                                       ^^^^ ^^^^^^ both Collector

ROOT CAUSE
----------
``core.build_order.plan_build_order`` rejects duplicates with a RAW id string
compare::

    rows = [r for r in rows if str(r.get("item_id")) not in picked_ids]

DDragon ships one item under several ids (Summoner's Rift canonical + mode
mirrors). ``3004`` and ``323004`` are both Manamune; ``6676`` and ``667666`` are
both The Collector. Two different strings, so neither the planner guard nor the
engine's own owned-id skip (which compares the same way) ever fires, and the
mirror is offered as a fresh candidate for a later slot.

The fix canonicalizes BOTH sides of the guard through
``core.build_planner.kit_synergy.canonical_item_id``. It is champion-agnostic
and family-agnostic - no Viego / Samira special case - so every alias pair in
the catalog is covered by construction, including the latent tank case (Locket
``3190`` + its SR mirror ``323190``) that is masked today only because neither
form wins a slot at the shipped ally-grant coefficient.

ASCII only - use " - " for a clause break (repo hard rule).
"""
from __future__ import annotations

import json
import time
import unittest

from core.build_order import plan_build_order
from core.build_planner import kit_synergy as ks
from core.build_planner.kit_synergy import canonical_item_id

# Real alias pairs, taken from the live 16.14.1 catalog (asserted below, not
# assumed): (canonical_4_digit, alias_form).
ALIAS_PAIRS = (
    ("3004", "323004"),    # Manamune          - the shipped Viego defect
    ("6676", "667666"),    # The Collector     - the shipped Samira defect
    ("3190", "323190"),    # Locket of the Iron Solari - the latent tank case
)


def _catalog() -> dict:
    patch = ks._resolve_ds_patch()
    path = ks._DS_DIR / patch / "items.json"
    raw = json.loads(path.read_text(encoding="utf-8"))
    data = raw.get("data", raw)
    return {str(k): v for k, v in data.items() if isinstance(v, dict)}


class AliasPairsAreRealTests(unittest.TestCase):
    """Ground the fixture: every pair really IS one item under two ids."""

    def test_each_alias_pair_is_the_same_catalog_item(self):
        cat = _catalog()
        for canon, alias in ALIAS_PAIRS:
            self.assertIn(canon, cat, canon)
            self.assertIn(alias, cat, alias)
            a, b = cat[canon], cat[alias]
            self.assertEqual(
                (a.get("name") or "").strip(), (b.get("name") or "").strip(),
                f"{canon} / {alias} are not the same item",
            )
            self.assertEqual(
                sorted(a.get("tags") or []), sorted(b.get("tags") or []),
                f"{canon} / {alias} carry different tags",
            )


class CanonicalItemIdCoversEveryAliasFormTests(unittest.TestCase):
    """The normalizer must fold every alias form onto its canonical id.

    ``667666`` is NOT a 2-digit-prefix mirror (its trailing 4 digits, ``7666``,
    are not a catalog id at all), so the purely structural rule that covers
    ``323004`` misses it. The helper has to resolve that residue against the
    catalog or the planner guard below is only half wired.
    """

    def test_every_alias_form_normalizes_to_its_canonical_id(self):
        for canon, alias in ALIAS_PAIRS:
            self.assertEqual(canonical_item_id(alias), canon,
                             f"{alias} must canonicalize to {canon}")

    def test_canonical_ids_are_left_alone(self):
        for canon, _alias in ALIAS_PAIRS:
            self.assertEqual(canonical_item_id(canon), canon)

    def test_still_identity_on_every_four_digit_catalog_id(self):
        """The extension must not merge two genuinely different items."""
        for iid in _catalog():
            if len(iid) == 4:
                self.assertEqual(canonical_item_id(iid), iid, iid)

    def test_idempotent_over_the_live_catalog(self):
        for iid in _catalog():
            once = canonical_item_id(iid)
            self.assertEqual(canonical_item_id(once), once, iid)


# --------------------------------------------------------------------------- #
# Fake engine - mirrors rank.py: it skips ids literally present in item_ids,
# which is exactly why the alias form leaks through to a later slot.
# --------------------------------------------------------------------------- #
class _AliasFakeEngine:
    """Offers a canonical item and its alias form as two separate rows."""

    def __init__(self, catalog: dict[str, tuple[str, float]]):
        self.cat = catalog
        self.calls: list[list[str]] = []

    def __call__(self, champion, archetype, **kw):
        item_ids = [str(i) for i in (kw.get("item_ids") or [])]
        self.calls.append(list(item_ids))
        rows = []
        for iid, (name, delta) in self.cat.items():
            if iid in item_ids:          # RAW compare - the engine's own rule
                continue
            rows.append({"item_id": iid, "item_name": name, "delta": delta,
                         "gold": 3000, "shares_dead_unique": False,
                         "dead_unique_key": "", "unique_passive_key": ""})
        rows.sort(key=lambda r: r["delta"], reverse=True)
        return {"ok": True, "scorer": "dps", "archetype": archetype,
                "ranked": rows[: int(kw.get("top", 40) or 40)],
                "fell_back": False}


def _alias_catalog() -> dict[str, tuple[str, float]]:
    """Canonical item #2 in the ranking, its alias form #3 - so a raw-id
    guard picks the canonical at slot 1 and the alias at slot 2."""
    return {
        "3153": ("Blade of The Ruined King", 100.0),
        "3004": ("Manamune", 99.0),
        "323004": ("Manamune (mirror)", 98.0),
        "6676": ("The Collector", 97.0),
        "667666": ("The Collector (mirror)", 96.0),
        "3190": ("Locket of the Iron Solari", 95.0),
        "323190": ("Locket of the Iron Solari (mirror)", 94.0),
        "3143": ("Randuin's Omen", 93.0),
        "3046": ("Phantom Dancer", 92.0),
        "3036": ("Lord Dominik's Regards", 91.0),
        "6697": ("Hubris", 90.0),
        "3031": ("Infinity Edge", 89.0),
    }


class PlannerRejectsAliasDuplicatesTests(unittest.TestCase):
    """RED before the fix: the planned order contains Manamune twice."""

    def _plan(self, slots=6):
        eng = _AliasFakeEngine(_alias_catalog())
        res = plan_build_order(
            "AnyChamp", "carry", level=18, owned_item_ids=[], mode="SR",
            slots=slots, inject_boots=False, rank_fn=eng,
        )
        self.assertIsNotNone(res)
        return res, eng

    def test_planned_order_has_no_duplicate_canonical_item(self):
        res, _eng = self._plan()
        canon = [canonical_item_id(s.item_id) for s in res.order]
        self.assertEqual(
            len(canon), len(set(canon)),
            f"planned order buys the same item twice: "
            f"{[(s.item_id, s.item_name) for s in res.order]}",
        )

    def test_full_six_distinct_items_are_still_planned(self):
        """The freed slot must be refilled by the engine, not dropped."""
        res, _eng = self._plan()
        self.assertEqual(len(res.order), 6,
                         "de-dup must not shorten the build")

    def test_alias_form_is_never_sent_back_as_owned_context(self):
        """The accumulated item_ids handed to the engine stay duplicate-free."""
        _res, eng = self._plan()
        for sent in eng.calls:
            canon = [canonical_item_id(i) for i in sent]
            self.assertEqual(len(canon), len(set(canon)),
                             f"engine context carries a duplicate item: {sent}")

    def test_owned_alias_blocks_the_canonical_form(self):
        """Symmetry - already owning the MIRROR must block the canonical."""
        eng = _AliasFakeEngine(_alias_catalog())
        res = plan_build_order(
            "AnyChamp", "carry", level=18, owned_item_ids=["323004"],
            mode="SR", slots=6, inject_boots=False, rank_fn=eng,
        )
        self.assertIsNotNone(res)
        picked = [canonical_item_id(s.item_id) for s in res.order]
        self.assertNotIn("3004", picked,
                         "owned Manamune mirror did not block plain Manamune")

    def test_latent_locket_pair_is_covered(self):
        """Guard case - Locket 3190 + its SR mirror 323190 (tank build)."""
        cat = {"3190": ("Locket of the Iron Solari", 100.0),
               "323190": ("Locket of the Iron Solari (mirror)", 99.0),
               "3143": ("Randuin's Omen", 98.0),
               "3075": ("Thornmail", 97.0),
               "3193": ("Gargoyle Stoneplate", 96.0),
               "3065": ("Spirit Visage", 95.0),
               "3110": ("Frozen Heart", 94.0)}
        eng = _AliasFakeEngine(cat)
        res = plan_build_order(
            "AnyTank", "tank", level=18, owned_item_ids=[], mode="SR",
            slots=6, inject_boots=False, rank_fn=eng,
        )
        self.assertIsNotNone(res)
        canon = [canonical_item_id(s.item_id) for s in res.order]
        self.assertEqual(len(canon), len(set(canon)),
                         f"tank order doubles Locket: "
                         f"{[s.item_id for s in res.order]}")


# --------------------------------------------------------------------------- #
# xdist root cause (MEASURED 2026-07-26) - the same pair of transport faults
# documented at length in tests/test_ds_client_conversion_seam_plumb_w2.py.
#
# ``_post_json`` (``core/daemon_slayer_client.py:95-112``) maps every transport
# failure to ``None``. ``core/build_order_precompute.py:330-335`` then turns
# that into ``order=[]``, and ``core/build_order.py:727-731`` swallows a
# mid-plan failure into a SHORT order. Both are the right production shape - a
# dead engine must not sink a whole sweep - so the fix does not belong in
# ``core/`` and this file works around it at the transport seam instead.
#
#   1. DEADLINE. ``core/daemon_slayer_client.py:33`` sets
#      ``DEFAULT_TIMEOUT = 0.5`` s. A solo POST /rank is 22 - 37 ms, but at
#      8-way concurrency the tail reaches 513 ms and 3 of 24 calls return None.
#      Reproduced deterministically by squeezing the deadline to 1 ms:
#      ``compute_cell -> []`` after exactly 1 call, that call returning None,
#      so ``_assert_distinct`` reported "expected 6 slots, got []" - an
#      ALIAS-DEDUPE verdict manufactured entirely by a socket timeout.
#
#   2. LISTEN BACKLOG. ``agents/daemon_slayer/server.py:2630`` builds a stdlib
#      ``ThreadingHTTPServer`` and never raises ``request_queue_size``, so the
#      socketserver default of 5 applies and the OS refuses connects beyond it:
#      MEASURED 3 of 500 sequential POSTs raising ``ConnectionRefusedError
#      [WinError 10061]`` under a 12-way load at a 30 s deadline. No timeout
#      can fix that one, so the CONNECT is retried.
#
# What is NOT retried: any assertion. A retry happens only while the response
# is ``None``, i.e. before any verdict exists. The engine is a pure function of
# the request body against a fixed snapshot, so a re-connected call returns the
# same order and every assertion below is evaluated exactly once, on real data.
# If every attempt fails, the teardown hook fails the test LOUDLY instead.
#
# Route, body, engine and every assertion are untouched.
# --------------------------------------------------------------------------- #
_LIVE_TIMEOUT = 30.0
# 5 attempts x a backoff longer than the measured 1.9 s worst-case service time
# clears a transient backlog overflow; a genuinely dead engine still fails.
_TRANSPORT_ATTEMPTS = 5
_TRANSPORT_BACKOFF = 0.4


class _PatientTransport:
    """Force ``_LIVE_TIMEOUT`` on every live call and re-connect on a None."""

    def __init__(self, real) -> None:
        self._real = real
        self.failures: list[tuple[str, dict]] = []
        self.reconnects = 0

    def __call__(self, path, body, timeout=None):
        for attempt in range(_TRANSPORT_ATTEMPTS):
            out = self._real(path, body, timeout=_LIVE_TIMEOUT)
            if out is not None:
                self.reconnects += attempt
                return out
            time.sleep(_TRANSPORT_BACKOFF * (attempt + 1))
        self.failures.append((path, dict(body)))
        return None


class LiveEngineBothKeyspacesTests(unittest.TestCase):
    """The acceptance criterion, against the real engine - skipped when down.

    Both shipped keyspaces are covered because they are two different callers of
    the same planner and a fix landed in only one of them is the classic RC trap
    (memory reference_build_order_two_keyspaces_both_need_regen).
    """

    @classmethod
    def setUpClass(cls):
        from core import daemon_slayer_client as dsc
        # Retried, and 5.0s rather than 2.0s, for the SAME backlog-overflow
        # reason as above: a single refused connect here would silently SKIP
        # this class, which is worse than a failure because the acceptance
        # criterion disappears with no signal.
        #
        # RM-119 B2 (2026-08-06): the verdict is delegated to the shared gate
        # so RC_REQUIRE_DS_ENGINE=1 turns the down-engine skip into a failure
        # where the engine is supposed to be up. The retry stays HERE because
        # the backoff is this suite's own answer to the backlog overflow.
        from tests.test_ds_live_route_gate import require_live_engine
        up = False
        for attempt in range(_TRANSPORT_ATTEMPTS):
            if dsc.is_engine_up(timeout=5.0):
                up = True
                break
            time.sleep(_TRANSPORT_BACKOFF * (attempt + 1))
        require_live_engine("the alias-dedupe live slot-count acceptance",
                            up=up)

    def setUp(self):
        # Rebind the single transport function every live caller below funnels
        # through - ``plan_build_order`` imports ``rank_for_primary_archetype``,
        # which resolves ``_post_json`` from its own module globals at call
        # time. This is the same seam production uses at
        # ``core/build_order_precompute.py:604-638``.
        from unittest import mock

        from core import daemon_slayer_client as dsc
        self.transport = _PatientTransport(dsc._post_json)
        patcher = mock.patch.object(dsc, "_post_json", self.transport)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self._assert_no_swallowed_transport_failure)

    def _assert_no_swallowed_transport_failure(self):
        """A None body reaching the assertions below is a defect in the
        MEASUREMENT, not an alias-dedupe regression - surface it as such."""
        self.assertEqual(
            self.transport.failures, [],
            f"{len(self.transport.failures)} live engine call(s) returned no "
            f"body at a {_LIVE_TIMEOUT}s deadline - any slot-count verdict "
            f"above is a transport artefact, not a dedupe result",
        )

    def _assert_distinct(self, ids, label):
        canon = [canonical_item_id(str(i)) for i in ids]
        self.assertEqual(
            len(canon), 6,
            f"{label}: expected 6 slots, got {ids} - a SHORT order means the "
            f"planner ran out of candidates or an engine call returned no "
            f"body; a duplicate order is the separate assertion below",
        )
        self.assertEqual(len(set(canon)), 6,
                         f"{label}: duplicate item in {ids} -> {canon}")

    def test_flat_damage_profile_keyspace(self):
        import tools.daemon_slayer_build_orders_generate as gen
        for champ in ("Viego", "Samira"):
            arch = gen.archetype_for(champ)
            for comp in gen.ENEMY_COMP_CLASSES:
                ids = gen.build_order_for_class(champ, arch, "sr", comp)
                self._assert_distinct(ids, f"flat/{champ}/{comp}")

    def test_comp_archetype_precompute_keyspace(self):
        from core import build_order_precompute as pre
        for champ in ("Viego", "Samira"):
            for comp in pre.COMP_ARCHETYPES:
                cell = pre.compute_cell(champ, comp, mode="sr")
                self._assert_distinct(cell.get("order") or [],
                                      f"precompute/{champ}/{comp}")


if __name__ == "__main__":
    unittest.main()
