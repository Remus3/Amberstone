"""P1-L15 audit hardening: engine + server CONCURRENCY and state isolation.

Lane scope: the DS engine is consumed by 4 mode coaches AND the :8893
HTTP server, potentially concurrently (coach ticks + dashboard
/api/ds-preview + direct server requests). The ThreadingHTTPServer hands
the SAME shared ``DataSnapshot`` (and the same module-level effect /
registry / abilities / weights caches) to every concurrent request. The
audit question: does a shared mutable structure get corrupted under
parallel calls, or does one request mutate data another relies on?

Audit result (all VERIFIED CORRECT - these tests pin the invariants so a
future regression trips):

  * Input non-mutation: every public scorer treats the snapshot's
    champion / item / scenario records as read-only and copies any
    passed-in stats / item-list / augment input before mutating. After a
    call the shared snapshot and the caller's own mutable arguments are
    byte-identical to a deep copy taken before the call. ``dps.py``'s
    ``stats_for_rotation = dict(stats)`` guard is one instance of a
    pattern that holds package-wide; ``engine._scale_champion_base`` /
    ``stats.aggregate_item_stats`` / ``augments.compute_augment_stats``
    all build fresh dicts rather than mutating the snapshot record.

  * Shared-cache non-aliasing: the module-level caches
    (``effects.ITEM_EFFECTS``, ``hybrid._WEIGHTS_CACHE``, the
    ability_dps block/form/max-priority registries, ``abilities._cache``,
    ``ult_rates._*_cache``, ``hps._formulas_cache``) hold either frozen
    dataclasses + tuples (deeply immutable) or plain JSON dicts that are
    only read via ``.get()``; the registry resolver helpers copy with
    ``dict(...)`` before merging caller overrides. A caller mutating a
    resolved registry map does NOT corrupt the cache, and two different
    requests (different champion / level / items / mode) never observe
    each other's resolved data.

  * Concurrency determinism: driving the engine - and the in-process
    server request handler - from many threads with mixed inputs yields
    results byte-identical to the same inputs computed single-threaded.
    The ARAM damage / AS multiplier never leaks into a concurrent SR
    call (the modifier is computed into a per-call local dict, never
    written back to the snapshot).

No hardcoded magic numbers and no fragile cross-item comparison
assertions: every expectation is "parallel == serial for the SAME
input" or "structure unchanged vs a deepcopy taken before the call".
"""

from __future__ import annotations

import copy
import json
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from dataclasses import FrozenInstanceError
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from agents.daemon_slayer import ability_dps as ad_mod
from agents.daemon_slayer import hybrid as hybrid_mod
from agents.daemon_slayer.ability_dps import (
    compute_ability_dps,
    get_block_index_for,
    get_form_index_for,
    rank_items_by_ability_dps,
)
from agents.daemon_slayer.beam import beam_search_build
from agents.daemon_slayer.burst import compute_burst_damage, rank_items_by_burst
from agents.daemon_slayer.data_loader import DataSnapshot
from agents.daemon_slayer.dps import compute_dps
from agents.daemon_slayer.effects import ITEM_EFFECTS
from agents.daemon_slayer.ehp import compute_ehp, rank_items_by_ehp
from agents.daemon_slayer.engine import build_champion
from agents.daemon_slayer.hps import compute_hps, rank_items_by_hps
from agents.daemon_slayer.hybrid import (
    compute_hybrid,
    get_weights_for,
    rank_items_by_hybrid,
)
from agents.daemon_slayer.rank import rank_items
from agents.daemon_slayer.server import start_server


# A spread of distinct (champion, level, items, mode) inputs that hit the
# AD / AP / HP cross-derivation walks, the ARAM modifier path, the augment
# overlay path, and the multi-form / block-index registries. Item ids are
# canonical patch ids present in every recent snapshot.
_CASES = (
    ("Aatrox", 11, ["6692", "3006"], "SR"),
    ("Aatrox", 11, ["6692", "3006"], "ARAM"),
    ("Lux", 13, ["6655", "3157"], "SR"),
    ("Lux", 13, ["6655", "3157"], "ARAM"),
    ("Garen", 6, ["3071"], "SR"),
    ("Kaisa", 16, ["3124", "3094"], "SR"),
    ("Cassiopeia", 11, ["6655"], "ARAM"),
    ("Soraka", 9, ["3504"], "SR"),
    ("MonkeyKing", 18, ["6692", "3047"], "SR"),
)


def _public_scorer_calls(snap: DataSnapshot):
    """Yield ``(label, thunk)`` for every public scorer over every case.

    Each thunk is a zero-arg callable returning a JSON-able dict
    (``.to_dict()`` for dataclass results, plain dict for ranked
    results). One thunk per (scorer, case) so the concurrency test can
    fan them out and compare against a serial baseline.
    """
    for champ, lvl, items, mode in _CASES:
        yield (
            f"build_champion/{champ}/{mode}/{lvl}",
            lambda c=champ, l=lvl, i=items, m=mode: build_champion(
                snap, c, l, item_ids=i, mode=m
            ).to_dict(),
        )
        yield (
            f"dps/{champ}/{mode}/{lvl}",
            lambda c=champ, l=lvl, i=items, m=mode: compute_dps(
                snap, c, l, item_ids=i, mode=m, target_armor=80.0, target_mr=40.0
            ).to_dict(),
        )
        yield (
            f"ehp/{champ}/{mode}/{lvl}",
            lambda c=champ, l=lvl, i=items, m=mode: compute_ehp(
                snap, c, l, item_ids=i, mode=m
            ).to_dict(),
        )
        yield (
            f"hps/{champ}/{mode}/{lvl}",
            lambda c=champ, l=lvl, i=items, m=mode: compute_hps(
                snap, c, l, item_ids=i, mode=m
            ).to_dict(),
        )
        yield (
            f"hybrid/{champ}/{mode}/{lvl}",
            lambda c=champ, l=lvl, i=items, m=mode: compute_hybrid(
                snap, c, l, item_ids=i, mode=m, target_armor=70.0
            ).to_dict(),
        )
        yield (
            f"ability_dps/{champ}/{mode}/{lvl}",
            lambda c=champ, l=lvl, i=items, m=mode: compute_ability_dps(
                snap, c, l, item_ids=i, mode=m, target_armor=60.0, target_mr=50.0
            ).to_dict(),
        )
        yield (
            f"burst/{champ}/{mode}/{lvl}",
            lambda c=champ, l=lvl, i=items, m=mode: compute_burst_damage(
                snap, c, l, item_ids=i, mode=m, target_armor=55.0
            ).to_dict(),
        )
        yield (
            f"rank/{champ}/{mode}/{lvl}",
            lambda c=champ, l=lvl, i=items, m=mode: rank_items(
                snap, c, l, current_item_ids=i, mode=m, top_n=8
            ).to_dict(),
        )


class InputNonMutationTests(unittest.TestCase):
    """Sub-area 1: a scorer must not mutate caller-owned data or the
    shared snapshot."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = DataSnapshot.load()

    def test_shared_snapshot_unchanged_after_every_scorer(self) -> None:
        """Deep-copy the snapshot's mutable maps, run every public scorer
        over every case, assert the maps are byte-identical afterward."""
        before_champ = copy.deepcopy(self.snap.champions)
        before_items = copy.deepcopy(self.snap.items)
        before_scen_id = copy.deepcopy(self.snap.scenarios_by_id)
        before_scen_lm = copy.deepcopy(self.snap.scenarios_by_lolmath)
        before_aug_id = copy.deepcopy(self.snap.arena_augments_by_id)

        for _label, thunk in _public_scorer_calls(self.snap):
            thunk()

        self.assertEqual(self.snap.champions, before_champ)
        self.assertEqual(self.snap.items, before_items)
        self.assertEqual(self.snap.scenarios_by_id, before_scen_id)
        self.assertEqual(self.snap.scenarios_by_lolmath, before_scen_lm)
        self.assertEqual(self.snap.arena_augments_by_id, before_aug_id)

    def test_caller_item_list_and_augments_not_mutated(self) -> None:
        """The exact list / augment-list objects the caller passes in are
        unchanged after the call (engine copies, never mutates in place)."""
        items = ["6692", "3006", "3047"]
        items_snapshot = list(items)
        augs = ["TheBrutalizer", "CelestialBody"]
        augs_snapshot = list(augs)

        build_champion(self.snap, "Aatrox", 13, item_ids=items, mode="ARAM",
                        augments=augs)
        compute_dps(self.snap, "Aatrox", 13, item_ids=items, mode="ARAM",
                    augments=augs)
        rank_items(self.snap, "Aatrox", 13, current_item_ids=items,
                   mode="SR", top_n=5)

        self.assertEqual(items, items_snapshot)
        self.assertEqual(augs, augs_snapshot)

    def test_resolved_stats_dict_is_caller_owned_copy(self) -> None:
        """Two builds of the same champion return independent stat dicts;
        mutating one must not affect the other or a later build."""
        a = build_champion(self.snap, "Lux", 11, item_ids=["6655"], mode="SR")
        b = build_champion(self.snap, "Lux", 11, item_ids=["6655"], mode="SR")
        self.assertIsNot(a.stats, b.stats)
        self.assertEqual(a.stats, b.stats)
        a.stats["ap"] = -999999.0
        c = build_champion(self.snap, "Lux", 11, item_ids=["6655"], mode="SR")
        self.assertNotEqual(c.stats.get("ap"), -999999.0)
        self.assertEqual(c.stats, b.stats)


class SharedCacheNonAliasingTests(unittest.TestCase):
    """Sub-area 2: module-level caches handed to a caller must not be
    mutable-by-reference into the cache."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = DataSnapshot.load()

    def test_item_effects_entries_are_immutable(self) -> None:
        """ITEM_EFFECTS holds frozen dataclasses (incl. nested frozen
        PeriodicProc) - attribute assignment must raise."""
        self.assertTrue(ITEM_EFFECTS, "ITEM_EFFECTS unexpectedly empty")
        sample = next(iter(ITEM_EFFECTS.values()))
        with self.assertRaises(FrozenInstanceError):
            sample.name = "tampered"  # type: ignore[misc]
        for eff in ITEM_EFFECTS.values():
            for proc in eff.periodics:
                with self.assertRaises(FrozenInstanceError):
                    proc.name = "tampered"  # type: ignore[misc]

    def test_registry_resolvers_return_fresh_maps(self) -> None:
        """get_*_for must hand back a fresh dict each call; mutating the
        returned map must not poison the next caller."""
        # Pick champions known to carry registry entries (multi-form /
        # block-index). If a snapshot lacks one the map is simply empty -
        # the freshness contract still holds and is what we assert.
        for champ in ("Cassiopeia", "Nidalee", "Aphelios", "Jayce", "Lux"):
            fm1, _ = get_form_index_for(champ)
            fm2, _ = get_form_index_for(champ)
            self.assertIsNot(fm1, fm2)
            fm1["ZZ"] = 999
            fm3, _ = get_form_index_for(champ)
            self.assertNotIn("ZZ", fm3)

            bi1, _ = get_block_index_for(champ)
            bi2, _ = get_block_index_for(champ)
            self.assertIsNot(bi1, bi2)
            bi1["ZZ"] = 999
            bi3, _ = get_block_index_for(champ)
            self.assertNotIn("ZZ", bi3)

    def test_weights_resolver_does_not_mutate_cache(self) -> None:
        """get_weights_for reads the cached table; repeated calls return
        a stable tuple and the cache dict keeps its shape."""
        hybrid_mod._load_archetype_weights()  # ensure populated
        cache_before = copy.deepcopy(hybrid_mod._WEIGHTS_CACHE)
        for champ in ("Aatrox", "JarvanIV", "MonkeyKing", "Lux", "Soraka"):
            w1 = get_weights_for(champ)
            w2 = get_weights_for(champ)
            self.assertEqual(w1, w2)
            self.assertEqual(len(w1), 2)
        self.assertEqual(hybrid_mod._WEIGHTS_CACHE, cache_before)

    def test_two_different_requests_do_not_alias(self) -> None:
        """Different (champion, mode) inputs must not see each other's
        resolved stat block via a shared cache reference."""
        sr = build_champion(self.snap, "Aatrox", 11, item_ids=["6692"],
                            mode="SR")
        aram = build_champion(self.snap, "Aatrox", 11, item_ids=["6692"],
                              mode="ARAM")
        other = build_champion(self.snap, "Lux", 11, item_ids=["6655"],
                               mode="SR")
        self.assertIsNot(sr.stats, aram.stats)
        self.assertIsNot(sr.stats, other.stats)
        # Mutating one resolved block leaves the others intact.
        sr.stats["hp"] = 1.0
        self.assertNotEqual(aram.stats.get("hp"), 1.0)
        self.assertNotEqual(other.stats.get("hp"), 1.0)


class ConcurrencyDeterminismTests(unittest.TestCase):
    """Sub-area 3: parallel == serial for the same inputs; no cross-talk."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = DataSnapshot.load()

    def _serial_baseline(self) -> dict[str, str]:
        out: dict[str, str] = {}
        for label, thunk in _public_scorer_calls(self.snap):
            out[label] = json.dumps(thunk(), sort_keys=True, default=str)
        return out

    def test_engine_parallel_matches_serial(self) -> None:
        """Fan every (scorer, case) thunk across a thread pool; each
        result must equal the serially-computed result for that label."""
        baseline = self._serial_baseline()
        thunks = list(_public_scorer_calls(self.snap))

        def run(item):
            label, thunk = item
            return label, json.dumps(thunk(), sort_keys=True, default=str)

        # Repeat the fan-out several times to give a torn-read / cache
        # race a chance to surface.
        for _ in range(6):
            with ThreadPoolExecutor(max_workers=16) as ex:
                results = list(ex.map(run, thunks * 2))
            for label, payload in results:
                self.assertEqual(
                    payload, baseline[label],
                    f"parallel result diverged from serial for {label}",
                )

    def test_aram_modifier_does_not_leak_into_concurrent_sr(self) -> None:
        """Hammer SR and ARAM DPS for the same champion/items from many
        threads simultaneously; every SR result must equal the pure-SR
        serial value and every ARAM result the pure-ARAM serial value."""
        champ, lvl, items = "Aatrox", 11, ["6692", "3006"]
        sr_expected = json.dumps(
            compute_dps(self.snap, champ, lvl, item_ids=items, mode="SR",
                        target_armor=80.0).to_dict(),
            sort_keys=True, default=str,
        )
        aram_expected = json.dumps(
            compute_dps(self.snap, champ, lvl, item_ids=items, mode="ARAM",
                        target_armor=80.0).to_dict(),
            sort_keys=True, default=str,
        )
        self.assertNotEqual(
            sr_expected, aram_expected,
            "ARAM vs SR must differ for this champion - test is vacuous "
            "otherwise",
        )

        def one(mode: str) -> str:
            return json.dumps(
                compute_dps(self.snap, champ, lvl, item_ids=items,
                            mode=mode, target_armor=80.0).to_dict(),
                sort_keys=True, default=str,
            )

        modes = (["SR"] * 24) + (["ARAM"] * 24)
        with ThreadPoolExecutor(max_workers=16) as ex:
            results = list(ex.map(one, modes * 4))
        for mode, payload in zip(modes * 4, results):
            self.assertEqual(
                payload, sr_expected if mode == "SR" else aram_expected,
                f"{mode} DPS corrupted under concurrent mixed-mode load",
            )

    def test_rankers_parallel_matches_serial(self) -> None:
        """The candidate-iterating rankers walk ``snapshot.items`` - prove
        the walk is read-only and parallel-safe by diffing vs serial."""
        jobs = []
        for champ, lvl, items, mode in _CASES[:5]:
            jobs.append(("rank-tank", champ, lvl, items, mode))
            jobs.append(("rank-bruiser", champ, lvl, items, mode))
            jobs.append(("rank-mage", champ, lvl, items, mode))
            jobs.append(("rank-assassin", champ, lvl, items, mode))
            jobs.append(("rank-enchanter", champ, lvl, items, mode))
            jobs.append(("beam", champ, lvl, items, mode))

        def run(job) -> tuple[str, str]:
            kind, champ, lvl, items, mode = job
            if kind == "rank-tank":
                r = rank_items_by_ehp(self.snap, champ, lvl,
                                      current_item_ids=items, mode=mode,
                                      top_n=6)
            elif kind == "rank-bruiser":
                r = rank_items_by_hybrid(self.snap, champ, lvl,
                                         current_item_ids=items, mode=mode,
                                         top_n=6)
            elif kind == "rank-mage":
                r = rank_items_by_ability_dps(self.snap, champ, lvl,
                                              current_item_ids=items,
                                              mode=mode, top_n=6)
            elif kind == "rank-assassin":
                r = rank_items_by_burst(self.snap, champ, lvl,
                                        current_item_ids=items, mode=mode,
                                        top_n=6)
            elif kind == "rank-enchanter":
                r = rank_items_by_hps(self.snap, champ, lvl,
                                      current_item_ids=items, mode=mode,
                                      top_n=6)
            else:
                r = beam_search_build(self.snap, champ, lvl,
                                      current_item_ids=items, mode=mode,
                                      top_n=4)
            key = f"{kind}/{champ}/{mode}/{lvl}"
            return key, json.dumps(r.to_dict(), sort_keys=True, default=str)

        baseline = dict(run(j) for j in jobs)
        with ThreadPoolExecutor(max_workers=12) as ex:
            results = list(ex.map(run, jobs * 3))
        for key, payload in results:
            self.assertEqual(
                payload, baseline[key],
                f"ranker {key} diverged under concurrency",
            )


class InProcessServerConcurrencyTests(unittest.TestCase):
    """Sub-area 3 (server): drive the real ThreadingHTTPServer request
    handler concurrently. In-process, ephemeral port - never touches the
    live :8893 server."""

    @classmethod
    def setUpClass(cls) -> None:
        snap = DataSnapshot.load()
        cls.srv = start_server(host="127.0.0.1", port=0, snapshot=snap)
        cls.host, cls.port = cls.srv.server_address
        cls.thread = threading.Thread(
            target=cls.srv.serve_forever, daemon=True,
            name="DSConcurrencyTestServer",
        )
        cls.thread.start()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.srv.shutdown()
        cls.srv.server_close()

    def _post(self, path: str, body: dict) -> tuple[int, dict]:
        url = f"http://{self.host}:{self.port}{path}"
        data = json.dumps(body).encode("utf-8")
        req = Request(url, data=data, method="POST",
                      headers={"Content-Type": "application/json"})
        try:
            with urlopen(req, timeout=20) as resp:
                return resp.status, json.loads(resp.read().decode("utf-8"))
        except HTTPError as e:
            return e.code, json.loads(e.read().decode("utf-8"))

    def test_mixed_route_concurrent_requests_match_serial(self) -> None:
        """Issue a mix of /stats /dps /ehp /rank requests (SR + ARAM,
        several champions) concurrently; each response must match the
        same request issued serially."""
        reqs: list[tuple[str, dict]] = []
        for champ, lvl, items, mode in _CASES[:6]:
            reqs.append(("/stats",
                         {"champion": champ, "level": lvl,
                          "items": items, "mode": mode}))
            reqs.append(("/dps",
                         {"champion": champ, "level": lvl, "items": items,
                          "mode": mode, "target_armor": 75}))
            reqs.append(("/ehp",
                         {"champion": champ, "level": lvl,
                          "items": items, "mode": mode}))
            reqs.append(("/rank",
                         {"champion": champ, "level": lvl,
                          "items": items, "mode": mode, "top": 6}))

        def key(path: str, body: dict) -> str:
            return path + "|" + json.dumps(body, sort_keys=True)

        baseline: dict[str, tuple[int, str]] = {}
        for path, body in reqs:
            status, payload = self._post(path, body)
            self.assertEqual(status, 200, f"{path} {body} -> {payload}")
            baseline[key(path, body)] = (
                status, json.dumps(payload, sort_keys=True, default=str)
            )

        def run(item):
            path, body = item
            status, payload = self._post(path, body)
            return (key(path, body), status,
                    json.dumps(payload, sort_keys=True, default=str))

        with ThreadPoolExecutor(max_workers=16) as ex:
            results = list(ex.map(run, reqs * 5))

        for k, status, payload in results:
            exp_status, exp_payload = baseline[k]
            self.assertEqual(status, exp_status)
            self.assertEqual(
                payload, exp_payload,
                f"concurrent server response diverged for {k}",
            )


if __name__ == "__main__":
    unittest.main()
