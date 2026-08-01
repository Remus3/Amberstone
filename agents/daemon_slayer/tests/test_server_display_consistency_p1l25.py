"""P1-L25 - Daemon Slayer :8860 served-number display/precision/consistency.

Lane: is the DISPLAYED number (the JSON the server emits) consistent with
the engine's INTERNAL value, and is the per-hit / per-second / delta
arithmetic self-consistent within one response payload?

Audit outcome was VERIFIED-CORRECT: the engine performs zero round() /
format-truncation in any ``to_dict()`` path (server uses ``to_dict()``,
not ``format_table()``), so the JSON surfaces raw engine floats at full
precision and "displayed == internal" holds by construction. These tests
are the hardening regression so a future refactor that (a) rounds a value
that then feeds a computed field, (b) flips ``dps_per_1k_gold`` to a
per-gold off-by-1000, (c) desyncs the crit/amp basis between
``avg_attack_dmg`` and ``raw_attack_dps``, or (d) returns a stale field
not recomputed for the requested level, fails deterministically.

No hardcoded engine magic numbers. Every expected value is either
recomputed from the SAME response's other fields via the documented
``dps.py`` formula, or compared against a fresh in-process engine call /
the loaded snapshot. Server is bound on an ephemeral port in-process
(port=0, injected snapshot) - the live :8860 daemon is never touched.
"""
from __future__ import annotations

import json
import math
import threading
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from agents.daemon_slayer.data_loader import DataSnapshot
from agents.daemon_slayer.dps import (
    DEFAULT_CRIT_BONUS,
    _armor_factor,
    compute_dps,
)
from agents.daemon_slayer.effects import (
    collect_effects,
    effective_target_armor,
    total_crit_damage_bonus,
)
from agents.daemon_slayer.rank import rank_items
from agents.daemon_slayer.server import start_server

# Tight tolerance: we are asserting the SERVED number reproduces an
# independent recompute to full float precision, not "approximately".
# JSON round-trips a Python float losslessly (repr-faithful) so the only
# slack needed is IEEE addition reordering, well under 1e-9 here.
_EXACT = 1e-9


def _start() -> tuple[str, int, object]:
    snap = DataSnapshot.load()
    srv = start_server(host="127.0.0.1", port=0, snapshot=snap)
    host, port = srv.server_address
    t = threading.Thread(
        target=srv.serve_forever, daemon=True, name="DSDisplayP1L25"
    )
    t.start()
    return host, port, srv


def _get(url: str) -> tuple[int, dict, bytes]:
    try:
        with urlopen(url, timeout=15) as resp:
            raw = resp.read()
            return resp.status, json.loads(raw.decode("utf-8")), raw
    except HTTPError as e:
        raw = e.read()
        return e.code, json.loads(raw.decode("utf-8")), raw


def _post(url: str, body: dict) -> tuple[int, dict, bytes]:
    data = json.dumps(body).encode("utf-8")
    req = Request(
        url, data=data, method="POST",
        headers={"Content-Type": "application/json"},
    )
    try:
        with urlopen(req, timeout=15) as resp:
            raw = resp.read()
            return resp.status, json.loads(raw.decode("utf-8")), raw
    except HTTPError as e:
        raw = e.read()
        return e.code, json.loads(raw.decode("utf-8")), raw


def _finite(*vals: object) -> bool:
    for v in vals:
        if v is None or not isinstance(v, (int, float)):
            return False
        if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
            return False
    return True


class _Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.host, cls.port, cls.srv = _start()
        cls.base = f"http://{cls.host}:{cls.port}"
        cls.snap = DataSnapshot.load()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.srv.shutdown()
        cls.srv.server_close()


class DpsDisplayEqualsInternalTests(_Base):
    """Sub-area 1: the number in the /dps JSON equals the engine's
    computed value to full precision (no lossy display round)."""

    CASES = [
        # (champion, level, items, mode, target_armor)
        ("Aatrox", 1, [], "SR", 0.0),
        ("Aatrox", 11, ["6692", "3031"], "SR", 80.0),
        ("Aatrox", 18, [], "SR", 0.0),
        ("Lux", 11, [], "SR", 50.0),
        ("Jinx", 13, ["3031", "3094"], "SR", 60.0),
    ]

    def test_dps_served_fields_equal_in_process_engine(self) -> None:
        for champ, lvl, items, mode, armor in self.CASES:
            with self.subTest(champ=champ, lvl=lvl, items=items):
                q = (
                    f"{self.base}/dps?champion={champ}&level={lvl}"
                    f"&mode={mode}&target_armor={armor}"
                )
                if items:
                    q += "&items=" + ",".join(items)
                status, body, _ = _get(q)
                self.assertEqual(status, 200, body)

                ref = compute_dps(
                    self.snap, champion_id=champ, level=lvl,
                    item_ids=items, mode=mode, target_armor=armor,
                ).to_dict()

                # Every numeric scalar the server surfaces must equal the
                # in-process engine value bit-for-bit (no round in to_dict
                # -> the served number IS the internal number).
                for key in (
                    "weighted_dps", "avg_attack_dmg", "raw_attack_dps",
                    "mode_multiplier", "per_attack_on_hit_damage",
                    "spellblade_per_proc_damage",
                    "lightshield_strike_per_proc_damage",
                    "target_armor", "target_mr",
                ):
                    self.assertAlmostEqual(
                        body[key], ref[key], delta=_EXACT,
                        msg=f"{champ} L{lvl}: served {key}={body[key]} "
                            f"!= engine {ref[key]}",
                    )
                # phase_dps dict: each phase value matches the engine.
                for ph, val in ref["phase_dps"].items():
                    self.assertAlmostEqual(
                        body["phase_dps"][ph], val, delta=_EXACT,
                        msg=f"{champ} L{lvl}: phase_dps[{ph}] drift",
                    )
                # stats block: every stat matches (the /dps stats are the
                # resolved build, same as /stats - assert no display loss).
                for sk, sv in ref["stats"].items():
                    self.assertAlmostEqual(
                        body["stats"][sk], sv, delta=_EXACT,
                        msg=f"{champ} L{lvl}: stats[{sk}] drift",
                    )

    def test_served_floats_are_repr_faithful_not_pre_rounded(self) -> None:
        # A real lossy display round (e.g. round(x, 2)) would make the
        # served value land on a 2-decimal grid. Assert at least one
        # high-information field carries >2 fractional digits, proving
        # the server did NOT round before serialto. (Aatrox L11 naked:
        # weighted_dps is a long repeating fraction.)
        _, body, _ = _get(f"{self.base}/dps?champion=Aatrox&level=11")
        wd = body["weighted_dps"]
        self.assertTrue(_finite(wd))
        # round(wd, 2) would differ from wd by up to 5e-3; the raw engine
        # value differs from its own 2dp rounding by a non-trivial amount.
        self.assertGreater(
            abs(wd - round(wd, 2)), 1e-6,
            msg=f"weighted_dps={wd} looks pre-rounded to 2dp (display "
                "round leaking into the payload)",
        )


class DpsPayloadSelfConsistencyTests(_Base):
    """Sub-area 2: within ONE /dps response the documented relationships
    hold - per-hit vs per-second, phase vs weighted, amp/crit basis."""

    def test_raw_dps_equals_avg_dmg_times_as_when_unmitigated(self) -> None:
        # dps.py: avg_attack_dmg = ad*(1+crit*cb)*armor_factor*mode*amp
        #         raw_attack_dps = ad*as*(1+crit*cb)
        # With no items / no armor / SR: armor_factor=mode=amp=1, so the
        # two displayed numbers MUST satisfy raw == avg * as exactly.
        # This is the core per-hit <-> per-second invariant.
        for champ, lvl in (("Aatrox", 1), ("Aatrox", 18), ("Garen", 11),
                           ("Lux", 6)):
            with self.subTest(champ=champ, lvl=lvl):
                _, b, _ = _get(
                    f"{self.base}/dps?champion={champ}&level={lvl}"
                )
                avg = b["avg_attack_dmg"]
                raw = b["raw_attack_dps"]
                as_ = b["stats"]["as"]
                self.assertTrue(_finite(avg, raw, as_))
                self.assertEqual(b["mode_multiplier"], 1.0)
                self.assertAlmostEqual(
                    raw, avg * as_, delta=_EXACT,
                    msg=f"{champ} L{lvl}: raw_attack_dps={raw} != "
                        f"avg_attack_dmg*as={avg*as_} (per-hit/per-sec "
                        "arithmetic desync)",
                )

    def test_avg_dmg_and_raw_dps_share_crit_basis_with_armor(self) -> None:
        # With target armor + a crit item, both displayed numbers must use
        # the SAME (1 + crit*crit_bonus) factor. Recompute that factor two
        # independent ways from the response and require equality - a
        # crit/amp-basis mismatch (e.g. avg uses post-clamp crit, raw uses
        # raw crit) would split them.
        champ, lvl, items, armor = "Aatrox", 11, ["6692", "3031"], 80.0
        _, b, _ = _get(
            f"{self.base}/dps?champion={champ}&level={lvl}"
            f"&items={','.join(items)}&target_armor={armor}"
        )
        avg = b["avg_attack_dmg"]
        raw = b["raw_attack_dps"]
        ad = b["stats"]["ad"]
        as_ = b["stats"]["as"]
        self.assertTrue(_finite(avg, raw, ad, as_))
        # crit factor implied by raw_attack_dps = ad*as*factor
        factor_from_raw = raw / (ad * as_)
        # crit factor implied by avg = ad*factor*armor_factor (mode=amp=1)
        eff = collect_effects(tuple(items))
        af = _armor_factor(effective_target_armor(armor, eff, lvl))
        factor_from_avg = avg / (ad * af)
        self.assertAlmostEqual(
            factor_from_raw, factor_from_avg, delta=1e-9,
            msg="avg_attack_dmg and raw_attack_dps disagree on the "
                f"crit-damage factor ({factor_from_avg} vs "
                f"{factor_from_raw}) - shared-basis invariant broken",
        )
        # And that factor must equal 1 + crit*(DEFAULT_CRIT_BONUS + IE...)
        crit = b["stats"]["crit"]
        expect_factor = 1.0 + crit * (
            DEFAULT_CRIT_BONUS + total_crit_damage_bonus(eff)
        )
        self.assertAlmostEqual(factor_from_raw, expect_factor, delta=1e-9)

    def test_weighted_dps_is_exactly_the_selected_phase_value(self) -> None:
        # weighted_dps must be byte-identical to phase_dps[phase] - it is
        # a SELECT, never a re-rounded recompute.
        for champ, lvl in (("Aatrox", 3), ("Aatrox", 11), ("Aatrox", 17),
                           ("Jinx", 9)):
            with self.subTest(champ=champ, lvl=lvl):
                _, b, _ = _get(
                    f"{self.base}/dps?champion={champ}&level={lvl}"
                )
                ph = b["phase"]
                self.assertIn(ph, b["phase_dps"])
                self.assertEqual(
                    b["weighted_dps"], b["phase_dps"][ph],
                    msg=f"{champ} L{lvl}: weighted_dps != "
                        f"phase_dps[{ph}] (selected-phase mismatch)",
                )

    def test_explicit_phase_override_selects_that_phase_value(self) -> None:
        # Requesting ?phase=early must make weighted_dps == phase_dps.early
        # (a stale-field hunt: the served weighted must track the request,
        # not a level-default phase).
        for phase in ("early", "mid", "late"):
            with self.subTest(phase=phase):
                _, b, _ = _get(
                    f"{self.base}/dps?champion=Aatrox&level=11&phase={phase}"
                )
                self.assertEqual(b["phase"], phase)
                self.assertEqual(b["weighted_dps"], b["phase_dps"][phase])


class RankPayloadSelfConsistencyTests(_Base):
    """Sub-area 2 (ranker): delta == new - baseline, gold == snapshot
    Meraki total, dps_per_1k_gold == delta/(gold/1000) (NOT per-gold)."""

    def test_rank_row_arithmetic_matches_displayed_baseline(self) -> None:
        _, b, _ = _get(
            f"{self.base}/rank?champion=Aatrox&level=11&mode=SR"
            "&target_armor=50&top=8"
        )
        base = b["baseline_dps"]
        self.assertTrue(_finite(base))
        self.assertTrue(b["ranked"], "expected non-empty ranking")
        for r in b["ranked"]:
            delta = r["delta_dps"]
            new = r["new_dps"]
            gold = r["gold"]
            eff = r["dps_per_1k_gold"]
            self.assertTrue(_finite(delta, new, gold, eff))
            # delta == new - baseline (displayed baseline, exact).
            self.assertAlmostEqual(
                delta, new - base, delta=_EXACT,
                msg=f"{r['item_id']}: delta_dps != new_dps - "
                    "baseline_dps (displayed-baseline desync)",
            )
            # dps_per_1k_gold is per-1000-gold, not per-gold. Recompute
            # the field's own contract and assert it is NOT the per-gold
            # value (off-by-1000 hunt).
            want_eff = (delta / (gold / 1000.0)) if (gold > 0 and delta > 0) else 0.0
            self.assertAlmostEqual(
                eff, want_eff, delta=_EXACT,
                msg=f"{r['item_id']}: dps_per_1k_gold formula drift",
            )
            if gold > 0 and delta > 0:
                per_gold = delta / gold
                # The 1k-scaled value is exactly 1000x the per-gold value;
                # if the server mislabeled per-gold as per-1k they'd be
                # equal. They must differ by the 1000x factor.
                self.assertAlmostEqual(
                    eff, per_gold * 1000.0, delta=1e-9,
                    msg=f"{r['item_id']}: dps_per_1k_gold is not 1000x "
                        "per-gold (suffix/units mismatch)",
                )

    def test_rank_gold_equals_snapshot_meraki_total(self) -> None:
        # The displayed gold must be the item's snapshot gold.total - the
        # exact integer dps_per_1k_gold divides by. A stale/derived gold
        # would silently skew every efficiency number.
        _, b, _ = _get(
            f"{self.base}/rank?champion=Aatrox&level=11&mode=SR&top=15"
        )
        for r in b["ranked"]:
            rec = self.snap.items.get(r["item_id"]) or {}
            snap_gold = int((rec.get("gold") or {}).get("total", 0) or 0)
            self.assertEqual(
                r["gold"], snap_gold,
                msg=f"{r['item_id']} ({r['item_name']}): served gold "
                    f"{r['gold']} != snapshot gold.total {snap_gold}",
            )

    def test_rank_served_rows_equal_in_process_ranker(self) -> None:
        # End-to-end: the served ranking equals an in-process rank_items
        # call field-for-field (no display round anywhere in the chain).
        _, b, _ = _get(
            f"{self.base}/rank?champion=Jinx&level=13&mode=SR"
            "&target_armor=60&top=10"
        )
        ref = rank_items(
            self.snap, champion_id="Jinx", level=13, mode="SR",
            target_armor=60.0, top_n=10,
        ).to_dict()
        self.assertAlmostEqual(
            b["baseline_dps"], ref["baseline_dps"], delta=_EXACT
        )
        self.assertEqual(len(b["ranked"]), len(ref["ranked"]))
        for got, exp in zip(b["ranked"], ref["ranked"]):
            self.assertEqual(got["item_id"], exp["item_id"])
            for k in ("delta_dps", "new_dps", "dps_per_1k_gold"):
                self.assertAlmostEqual(
                    got[k], exp[k], delta=_EXACT,
                    msg=f"{got['item_id']}: served {k} != engine {k}",
                )
            self.assertEqual(got["gold"], exp["gold"])


class DeterminismAndMonotonicityTests(_Base):
    """Sub-area 3: identical query -> identical bytes; rising level ->
    monotone where the math demands; edge queries stay coherent."""

    def test_same_query_identical_bytes(self) -> None:
        url = (
            f"{self.base}/dps?champion=Aatrox&level=11"
            "&items=6692,3031&target_armor=80&mode=SR"
        )
        _, _, raw1 = _get(url)
        _, _, raw2 = _get(url)
        _, _, raw3 = _get(url)
        self.assertEqual(raw1, raw2)
        self.assertEqual(raw2, raw3)

    def test_post_and_get_same_inputs_same_numbers(self) -> None:
        # GET query form and POST JSON body must yield identical served
        # numbers for the same inputs (one display path, not two).
        _, g, _ = _get(
            f"{self.base}/dps?champion=Aatrox&level=11"
            "&items=6692,3031&target_armor=80"
        )
        _, p, _ = _post(
            f"{self.base}/dps",
            {"champion": "Aatrox", "level": 11,
             "items": ["6692", "3031"], "target_armor": 80},
        )
        for k in ("weighted_dps", "avg_attack_dmg", "raw_attack_dps"):
            self.assertEqual(g[k], p[k], msg=f"GET vs POST {k} differ")

    def test_naked_dps_monotone_nondecreasing_in_level(self) -> None:
        # No items, fixed target: a champion's auto-attack avg_attack_dmg
        # and raw_attack_dps are non-decreasing in level (AD and AS only
        # grow with Riot quadratic scaling - never regress).
        prev_avg = prev_raw = -1.0
        for lvl in (1, 3, 6, 9, 11, 13, 16, 18):
            with self.subTest(level=lvl):
                _, b, _ = _get(
                    f"{self.base}/dps?champion=Aatrox&level={lvl}"
                )
                avg = b["avg_attack_dmg"]
                raw = b["raw_attack_dps"]
                self.assertTrue(_finite(avg, raw))
                self.assertGreaterEqual(
                    avg + 1e-9, prev_avg,
                    msg=f"avg_attack_dmg regressed at L{lvl}",
                )
                self.assertGreaterEqual(
                    raw + 1e-9, prev_raw,
                    msg=f"raw_attack_dps regressed at L{lvl}",
                )
                prev_avg, prev_raw = avg, raw

    def test_edge_queries_return_coherent_numbers(self) -> None:
        # L1, L18, no items, and a caster with sparse scenarios must each
        # return finite (never None/NaN/inf) displayed numbers. weighted
        # may legitimately be 0 (no scenario) but must be a real 0.0.
        for champ, lvl in (("Aatrox", 1), ("Aatrox", 18),
                           ("Lux", 1), ("Lux", 18), ("Garen", 6)):
            with self.subTest(champ=champ, lvl=lvl):
                _, b, _ = _get(
                    f"{self.base}/dps?champion={champ}&level={lvl}"
                )
                self.assertTrue(
                    _finite(
                        b["weighted_dps"], b["avg_attack_dmg"],
                        b["raw_attack_dps"], b["mode_multiplier"],
                        b["per_attack_on_hit_damage"],
                    ),
                    msg=f"{champ} L{lvl}: a displayed number is "
                        f"None/NaN/inf: {b}",
                )
                self.assertGreaterEqual(b["weighted_dps"], 0.0)
                self.assertGreaterEqual(b["avg_attack_dmg"], 0.0)
                # stats block: no None/NaN leaking into a displayed stat.
                for sk, sv in b["stats"].items():
                    self.assertTrue(
                        _finite(sv),
                        msg=f"{champ} L{lvl}: stats[{sk}]={sv} not finite",
                    )

    def test_out_of_range_level_errors_not_silently_rescored(self) -> None:
        # Display-consistency hygiene: an out-of-range level must NOT come
        # back silently scored at a clamped level with a surprising echoed
        # ``level`` (that would be a stale/misleading displayed field).
        # Verified contract: clamp_level raises -> server maps ValueError
        # to a clean 422 {"error","status"} for both > 18 and < 1, with
        # ONE documented exception: level 0 is falsy and the server's
        # ``_opt_int(...) or 1`` coerces it to 1 BEFORE clamp_level sees
        # it, so 0 returns a coherent L1 payload (level echoed == 1 ==
        # level scored - still self-consistent, not stale).
        for bad in (99, 19, -3):
            with self.subTest(level=bad):
                status, body, _ = _get(
                    f"{self.base}/dps?champion=Aatrox&level={bad}"
                )
                self.assertEqual(status, 422, body)
                self.assertEqual(set(body), {"error", "status"})
                self.assertEqual(body["status"], 422)
                self.assertNotIn("level", body)
        # The level-0 -> L1 coercion path: served level echo must equal
        # the level actually scored (consistency, not a stale echo).
        status0, b0, _ = _get(f"{self.base}/dps?champion=Aatrox&level=0")
        self.assertEqual(status0, 200, b0)
        self.assertEqual(b0["level"], 1)
        _, l1, _ = _get(f"{self.base}/dps?champion=Aatrox&level=1")
        self.assertEqual(b0["weighted_dps"], l1["weighted_dps"])
        self.assertEqual(b0["avg_attack_dmg"], l1["avg_attack_dmg"])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
