"""R197 - the ITEM lane of the wielder HSP axis, and a guard that can SEE a stranded seam.

THE DEFECT
----------
``assume_hsp_amp`` shipped in ENGINE 1.171.0 (R60) on two engine entry points -
``ehp.compute_ehp`` (the wielder's own ItemShield pool) and
``sustain.compute_sustain`` (the wielder's kit REGEN self-heal). Both read
``_hsp_amp.sum_wielder_hsp_pct``, which sums the curated
``enchanter_items.json`` ``heal_shield_amp_pct`` field.

``grep -c assume_hsp_amp agents/daemon_slayer/server.py`` returned 0. No route
parsed it. Its RUNE twin ``apply_rune_hsp_amp`` shipped on four routes at
1.225.0 (R136), so the ADDITIVE model the engine implements
(item 0.22 + rune 0.05) could only ever be armed on its rune half. The item
half was unreachable from a live coach tick, a generated build table, an
operator curl, and the Python client alike.

Same defect class as R193 / R194(a) (``assume_max_stacks_omnivamp``).

WHY BOTH EXISTING REACHABILITY GUARDS WERE GREEN
------------------------------------------------
``test_route_seams_reach_the_client.py`` and
``test_route_seams_reach_the_client_per_route.py`` both build their seam
universe by parsing ``server.py`` for body keys and subtracting what
``core/daemon_slayer_client.py`` can express. That answers "given a seam the
SERVER exposes, can the CLIENT set it". A seam the server never exposes is not
in their universe at all, so a stranded seam is structurally invisible to them -
the check is circular. R193 recorded this in prose; this file encodes it.

``test_stranded_seams`` below inverts the direction: it derives the seam set
from the ENGINE (``inspect.signature`` over the entry points ``server.py``
actually calls) and asserts each is both PARSED and PASSED by ``server.py``.
Adding a new DEFAULT-OFF engine kwarg without wiring it now goes RED by default.

Offline only - no server start, no sockets. AST + inspect + direct handler calls.
"""
from __future__ import annotations

import ast
import inspect
import pathlib
import re
import unittest

from .. import server as S
from ..data_loader import DataSnapshot
from ..ehp import compute_ehp
from ..sustain import compute_sustain
from .._hsp_amp import sum_wielder_hsp_pct

SERVER_PATH = pathlib.Path(S.__file__)
SERVER_SRC = SERVER_PATH.read_text(encoding="utf-8")

# Curated HSP inventory used by every measurement below - Redemption 0.10 +
# Mikael's Blessing 0.12 = 0.22 (additive, per _hsp_amp.sum_wielder_hsp_pct).
REDEMPTION = "3107"
MIKAELS = "3222"
HSP_PAIR = [REDEMPTION, MIKAELS]
# Wielder SELF-SHIELD items - Sterak's / Shieldbow / Maw. compute_ehp's
# shield_amp_mult multiplies the ItemShield POOL, so without one of these the
# pool is 0.0 and the amp has nothing to scale (see test_ehp_on_is_inert_...).
STERAKS, SHIELDBOW, MAW = "3053", "6673", "3156"


def _route_facing_entry_points() -> dict[str, object]:
    """Engine functions ``server.py`` actually calls, by qualified name.

    Resolved through the server module namespace so an import alias cannot hide
    an entry point, and filtered to functions DEFINED in the daemon_slayer
    package (a stdlib or local helper is not an engine seam surface).
    """
    tree = ast.parse(SERVER_SRC)
    called = {
        n.func.id
        for n in ast.walk(tree)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
    }
    out: dict[str, object] = {}
    for name in sorted(called):
        obj = getattr(S, name, None)
        if not inspect.isfunction(obj):
            continue
        mod = getattr(obj, "__module__", "") or ""
        if not mod.startswith("agents.daemon_slayer") or mod.endswith(".server"):
            continue
        out[f"{mod.rsplit('.', 1)[-1]}.{name}"] = obj
    return out


def _engine_seams() -> dict[str, list[str]]:
    """Every DEFAULT-OFF seam kwarg on a route-facing entry point -> its owners.

    A seam is a parameter named ``assume_`` / ``apply_`` / ``use_`` whose
    default is literally ``False``. ``is False`` not ``== False`` so a 0/0.0
    numeric default is not swept in as a boolean seam.
    """
    seams: dict[str, list[str]] = {}
    for fq, fn in _route_facing_entry_points().items():
        for p in inspect.signature(fn).parameters.values():
            if p.name.startswith(("assume_", "apply_", "use_")) and p.default is False:
                seams.setdefault(p.name, []).append(fq)
    return seams


def _parsed_keys(src: str) -> set[str]:
    """Body keys ``server.py`` reads through ``_opt_bool``."""
    tree = ast.parse(src)
    return {
        n.args[1].value
        for n in ast.walk(tree)
        if isinstance(n, ast.Call)
        and isinstance(n.func, ast.Name)
        and n.func.id == "_opt_bool"
        and len(n.args) >= 2
        and isinstance(n.args[1], ast.Constant)
        and isinstance(n.args[1].value, str)
    }


def _passed_kwargs(src: str) -> set[str]:
    """Keyword-argument names ``server.py`` forwards on ANY call.

    The second half of the contract. R194 recorded a PARSE-side drop - a key
    read out of the body and then never forwarded - which made a live re-rank
    read as inert, so parsing alone is NOT reachability.
    """
    tree = ast.parse(src)
    return {
        kw.arg
        for n in ast.walk(tree)
        if isinstance(n, ast.Call)
        for kw in n.keywords
        if kw.arg
    }


def stranded_seams(src: str) -> dict[str, list[str]]:
    """Seams the engine offers that ``src`` neither parses nor forwards.

    Takes the source TEXT so a caller can feed a mutated copy - that is how the
    negative control below proves the checker is not vacuously green.
    """
    parsed, passed = _parsed_keys(src), _passed_kwargs(src)
    return {
        name: owners
        for name, owners in _engine_seams().items()
        if not (name in parsed and name in passed)
    }


# ---------------------------------------------------------------------------
# THE DEBT LEDGER, NOT AN EXEMPTION LIST
#
# Every name here is a real stranded seam measured 2026-07-27 against 17
# route-facing entry points. It is written down so this guard is GREEN on
# arrival rather than blocking on 22 unrelated wirings, and the assertion is an
# EQUALITY so the ledger is self-cleaning in both directions:
#
#   * a NEW unwired engine seam            -> RED (the entire point),
#   * WIRING one of these into a route     -> RED until it is deleted here,
#     so the ledger can only shrink.
#
# These are NOT "engine-internal". Genuinely engine-internal helpers are already
# excluded by construction: _engine_seams only walks functions server.py CALLS,
# so a private helper seam (ehp._collect_shields, dps._rotation_attack_dps,
# _item_general_dr.item_general_dr_multiplier, ...) never enters the universe.
# Everything below is route-facing and unreachable, with a per-entry reason.
# ---------------------------------------------------------------------------
STRANDED_TODAY: dict[str, str] = {
    # The ABILITY lane of the same HSP axis this file wires the ITEM lane of.
    # Left for its own slice: /hps has no inventory-vs-ability split today and
    # wiring it blind would ship an unmeasured second flip.
    "apply_ability_hsp_amp": "HSP ability lane - own slice, not measured here",
    # RM-98 adjudicated the cast-rate TIME BASE; the propensity PRIOR is the
    # separate half that was never route-exposed.
    "apply_cast_rate_propensity_prior": "RM-98 cast-rate prior - never route-exposed",
    # R212 crit CHANCE / crit DAMAGE MULTIPLIER registry (Yasuo / Yone doubling
    # + overflow AD, Senna overflow life steal, Jhin's 0.86 Whisper penalty).
    # Engine-only by design: the sibling RM-46 crit-CONVERSION seam took its own
    # slice to reach rank.py + POST /rank, and wiring this one in the same slice
    # would ship an unmeasured second live flip on the same auto-attack term.
    "apply_crit_chance_overrides": "R212 crit chance/damage multiplier - engine-only, live flip unmeasured",
    # (The three rune lanes - apply_rune_offense_grants / apply_rune_self_heal /
    # apply_rune_shield_grants - were wired at ENGINE 1.267.0 and are therefore
    # gone from this ledger. See
    # test_rune_lane_route_seams_rm118.py for the measured per-seam route table.)
    # Target/caster STATE assumptions. The conditional-target-state arc is
    # operator-CLOSED (s232), so these are deliberately not client-facing.
    "assume_ally_detonation": "target-state arc operator-CLOSED s232",
    "assume_caster_lowhp": "caster-state arc operator-CLOSED s232",
    "assume_lifeline_shield": "caster-state lifeline - operator-CLOSED s232",
    "assume_item_lowhp_magic_crit": "low-HP target state - operator-CLOSED s232",
    "assume_passive_reflect": "target-state reflect - operator-CLOSED s232",
    # Per-item shield opt-ins into the EHP ItemShield pool. All five shipped
    # DEFAULT-OFF with an operator-gated live flip (docs/LIVE_GAME_GATED_SYNC.md)
    # and none was ever given a body key.
    "assume_chainlaced_shield": "per-item shield opt-in - live flip operator-gated",
    "assume_eclipse_shield": "per-item shield opt-in - live flip operator-gated",
    "assume_fimbulwinter_shield": "per-item shield opt-in - live flip operator-gated",
    "assume_kaenic_shield": "per-item shield opt-in - live flip operator-gated",
    "assume_seraphs_shield": "per-item shield opt-in - live flip operator-gated",
    # Vamp lanes whose engine half shipped in R193/R194 and whose route wire was
    # never added. Both live on ``compute_ehp`` ONLY (ehp.py:1594 / 1609), so
    # their wire is a /ehp-scalar pass; ``assume_cleave_lifesteal`` additionally
    # needs the non-boolean ``targets_in_rotation`` transport, which /ehp does not
    # parse today, so it is not a pure flag wire.
    "assume_cleave_lifesteal": "R194 cleave vamp - engine-only, needs targets_in_rotation transport",
    "assume_crit_weighted_vamp": "R193 crit-weighted vamp - engine-only",
    # Movement-speed utility term on the hybrid axis - never route-exposed.
    "assume_ms_utility": "hybrid MS utility term - never route-exposed",
}


class StrandedSeamGuard(unittest.TestCase):
    """The engine-derived reachability guard. Not circular by construction."""

    def test_universe_is_engine_derived_not_server_derived(self):
        # Anti-circularity: the seam universe must contain at least one name
        # server.py does NOT parse, otherwise this guard has degenerated into
        # the same tautology the two sibling guards suffer from.
        seams = _engine_seams()
        self.assertGreater(len(seams), 40, "engine seam universe collapsed")
        self.assertTrue(
            set(seams) - _parsed_keys(SERVER_SRC),
            "seam universe is a subset of what server.py parses - guard is circular",
        )

    def test_stranded_set_equals_the_ledger(self):
        actual = stranded_seams(SERVER_SRC)
        self.assertEqual(
            sorted(actual),
            sorted(STRANDED_TODAY),
            "stranded engine seams drifted from the ledger - wire the seam into a "
            "route, or add it to STRANDED_TODAY with a reason",
        )

    def test_assume_hsp_amp_is_no_longer_stranded(self):
        self.assertNotIn("assume_hsp_amp", stranded_seams(SERVER_SRC))
        self.assertIn("assume_hsp_amp", _parsed_keys(SERVER_SRC))
        self.assertIn("assume_hsp_amp", _passed_kwargs(SERVER_SRC))

    def test_negative_control_checker_goes_red_on_prefix_source(self):
        # Proves the guard is not vacuously green: feed it a copy of server.py
        # with every assume_hsp_amp line deleted - the pre-R197 state - and the
        # checker must report the seam stranded again.
        stripped = "\n".join(
            ln for ln in SERVER_SRC.splitlines() if "assume_hsp_amp" not in ln
        )
        self.assertEqual(stripped.count("assume_hsp_amp"), 0)
        self.assertIn(
            "assume_hsp_amp",
            stranded_seams(stripped),
            "checker stayed green on a source with the seam removed",
        )

    def test_negative_control_parse_without_pass_is_still_stranded(self):
        # The third stranded shape (R194): a key read out of the body and then
        # dropped before the engine call. Parsing alone must NOT read as wired.
        parse_only = SERVER_SRC.replace(
            "            assume_hsp_amp=assume_hsp_amp,\n", ""
        ).replace(
            "            assume_hsp_amp=assume_hsp_amp,\n        )", "        )"
        )
        parse_only = re.sub(
            r"^\s*assume_hsp_amp=assume_hsp_amp,\s*$", "", parse_only, flags=re.M
        )
        self.assertIn("assume_hsp_amp", _parsed_keys(parse_only))
        self.assertNotIn("assume_hsp_amp", _passed_kwargs(parse_only))
        self.assertIn("assume_hsp_amp", stranded_seams(parse_only))


class HspCuratedValues(unittest.TestCase):
    """Pin the curated magnitudes the OFF/ON measurements below depend on."""

    def test_redemption_and_mikaels_sum_additively(self):
        self.assertAlmostEqual(sum_wielder_hsp_pct([REDEMPTION]), 0.10, places=6)
        self.assertAlmostEqual(sum_wielder_hsp_pct([MIKAELS]), 0.12, places=6)
        self.assertAlmostEqual(sum_wielder_hsp_pct(HSP_PAIR), 0.22, places=6)


class RouteDefaultOff(unittest.TestCase):
    """Omitting the key must give a byte-identical response on both routes."""

    @classmethod
    def setUpClass(cls):
        cls.snap = DataSnapshot.load()
        S._CACHE.set(cls.snap)

    def test_ehp_route_absent_key_is_byte_identical(self):
        base = {"champion": "Sett", "level": 13, "items": HSP_PAIR}
        self.assertEqual(
            S._route_ehp(dict(base)),
            S._route_ehp({**base, "assume_hsp_amp": False}),
        )

    def test_sustain_route_absent_keys_are_byte_identical(self):
        # /sustain gained BOTH ``items`` and ``assume_hsp_amp`` in R197, so the
        # no-key response is checked against the fully-defaulted one.
        for champ in ("DrMundo", "Gragas", "Sett"):
            with self.subTest(champion=champ):
                self.assertEqual(
                    S._route_sustain({"champion": champ}),
                    S._route_sustain(
                        {"champion": champ, "items": [], "assume_hsp_amp": False}
                    ),
                )

    def test_sustain_route_items_alone_change_nothing(self):
        # WHY: an inventory with the flag OFF must not leak into the score -
        # otherwise the new ``items`` parse would itself be a behaviour change.
        self.assertEqual(
            S._route_sustain({"champion": "DrMundo"}),
            S._route_sustain({"champion": "DrMundo", "items": HSP_PAIR}),
        )


class RouteOnFlipMoves(unittest.TestCase):
    """Measured OFF/ON. Named champion, level, and inventory - not prose."""

    @classmethod
    def setUpClass(cls):
        cls.snap = DataSnapshot.load()
        S._CACHE.set(cls.snap)

    def test_sustain_on_moves_the_score_by_exactly_the_hsp_factor(self):
        # DrMundo, level-independent, SR, Redemption + Mikael's. His REGEN
        # sustain is the amped kind, so the RAW engine factor is exactly
        # (1 + 0.22): 0.5954666666666667 -> 0.7264693333333334.
        # WHY the pinned route numbers are 4dp: SustainResult.to_dict rounds, so
        # the ROUTE-visible ratio is 0.7265/0.5955 = 1.21998, not 1.22. Pinning
        # the rounded pair keeps this honest about what a client actually sees.
        off = S._route_sustain({"champion": "DrMundo", "items": HSP_PAIR})
        on = S._route_sustain(
            {"champion": "DrMundo", "items": HSP_PAIR, "assume_hsp_amp": True}
        )
        self.assertEqual(off["sustain_score"], 0.5955)
        self.assertEqual(on["sustain_score"], 0.7265)
        raw_off = compute_sustain("DrMundo", mode="SR", item_ids=HSP_PAIR)
        raw_on = compute_sustain(
            "DrMundo", mode="SR", item_ids=HSP_PAIR, assume_hsp_amp=True
        )
        self.assertAlmostEqual(
            raw_on.sustain_score / raw_off.sustain_score, 1.22, places=9
        )

    def test_sustain_vamp_only_champion_is_invariant(self):
        # HSP amplifies heals/shields, NOT vamp. Briar's sustain is all
        # lifesteal/drain, so the seam must be a no-op for her even ON.
        off = S._route_sustain({"champion": "Briar", "items": HSP_PAIR})
        on = S._route_sustain(
            {"champion": "Briar", "items": HSP_PAIR, "assume_hsp_amp": True}
        )
        self.assertEqual(off["sustain_score"], on["sustain_score"])

    def test_ehp_on_is_score_inert_without_a_self_shield_item(self):
        # HONEST RESULT, pinned deliberately. On the HSP pair ALONE the
        # ItemShield pool is empty, so arming the seam moves the reported
        # shield_amp_mult 1.0 -> 1.22 and moves NO score. Measured across all
        # 173 champions: 0 score-movers. This is the R194 "uniform multiplier
        # on an empty numerator" shape and is why /ehp is a reporting-only wire
        # until a shield item is in the build.
        body = {"champion": "Sett", "level": 13, "items": HSP_PAIR}
        off = S._route_ehp(dict(body))
        on = S._route_ehp({**body, "assume_hsp_amp": True})
        self.assertEqual(off["shield_any"], 0.0)
        self.assertAlmostEqual(off["shield_amp_mult"], 1.0, places=6)
        self.assertAlmostEqual(on["shield_amp_mult"], 1.22, places=6)
        self.assertEqual(off["blended_ehp"], on["blended_ehp"])

    def test_ehp_on_moves_the_score_once_a_self_shield_item_is_present(self):
        # Sett, level 13, SR, Redemption + Mikael + Sterak's + Shieldbow + Maw.
        # Now the pool is non-empty and the amp lands on the EHP numerator.
        body = {
            "champion": "Sett",
            "level": 13,
            "items": HSP_PAIR + [STERAKS, SHIELDBOW, MAW],
        }
        off = S._route_ehp(dict(body))
        on = S._route_ehp({**body, "assume_hsp_amp": True})
        self.assertGreater(off["shield_any"], 0.0)
        self.assertGreater(on["blended_ehp"], off["blended_ehp"])


class EngineParityWithRoute(unittest.TestCase):
    """The route must not silently diverge from a direct engine call."""

    @classmethod
    def setUpClass(cls):
        cls.snap = DataSnapshot.load()
        S._CACHE.set(cls.snap)

    def test_ehp_route_matches_compute_ehp(self):
        direct = compute_ehp(
            self.snap, champion_id="Sett", level=13, item_ids=HSP_PAIR,
            mode="SR", assume_hsp_amp=True,
        ).to_dict()
        via = S._route_ehp(
            {"champion": "Sett", "level": 13, "items": HSP_PAIR,
             "assume_hsp_amp": True}
        )
        self.assertEqual(direct["shield_amp_mult"], via["shield_amp_mult"])

    def test_sustain_route_matches_compute_sustain(self):
        direct = compute_sustain(
            "DrMundo", mode="SR", item_ids=HSP_PAIR, assume_hsp_amp=True
        ).to_dict()
        via = S._route_sustain(
            {"champion": "DrMundo", "items": HSP_PAIR, "assume_hsp_amp": True}
        )
        self.assertEqual(direct["sustain_score"], via["sustain_score"])


if __name__ == "__main__":
    unittest.main()
