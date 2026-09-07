"""Seam reachability measured PER ROUTE, not per name.

WHY THIS EXISTS ALONGSIDE ``test_route_seams_reach_the_client.py``
-----------------------------------------------------------------
The sibling guard collapses the question to a NAME: it collects every
seam-shaped body key any ``_route_*`` parses, collects every name any function
in ``core/daemon_slayer_client.py`` can express, and subtracts. That answers
"can this seam be set from the client AT ALL", which was the right first
question and caught the ASSUMED-INCOMING-SHARE regression it was written for.

It is not the question a caller actually has. ``apply_mode_modifiers`` was
parsed by EIGHT routes (/dps, /rank, /ehp, /rank-tank, /hybrid, /rank-bruiser,
/v2/fight-report, /beam) and, since the RM-172 uniform wiring on 2026-08-06, by
NINETEEN; the moment ONE client function names it, the name-based guard reads it
as reached on all nineteen. The same collapse hides
``apply_item_resist_grants`` on ``/ehp`` behind its ``/rank-tank`` wire.

(The 1.250.0 and 1.251.0 write-ups of this file say SEVEN. That was a
miscount by one on my part and is corrected here; the argument is unaffected.
Those entries are append-only history and were left as written.)

Measured 2026-07-25 (ENGINE 1.250.0), the two questions differ by 3x:

  * name-collapsed stranded set  ..... 33
  * per-(route, seam) stranded set ... 101

ENGINE 1.253.0 drained the EHP-family block - the 20 seams shared by /ehp,
/hybrid, /rank-tank and /rank-bruiser, which were 76 of those 101 pairs -
leaving 25 here and 12 in the sibling. The gap between the two questions is
still real (25 vs 12) and still the reason this file exists.

So RM-115's headline "34 stranded" is an UNDERCOUNT of the operator-visible
debt, not because the census was sloppy but because it answered the weaker
question. This file carries the stronger one.

WHAT IS CHECKED
---------------
By INTROSPECTION over the two source files, never a hardcoded key list:

  * map ``"/path" -> _route_handler`` out of ``server.py``'s dispatch table,
  * for each handler, collect the seam-shaped keys it reads out of ``body``,
  * for each client function, find which ``_post_json("/path", ...)`` it calls
    and collect the names THAT function can express (its keyword arguments plus
    the string keys it writes into its request body),
  * assert the stranded set, keyed by (route, seam), is EXACTLY the ledger.

A route with NO client function at all (``/beam``, ``/v2/fight-report``) has
every one of its seams stranded, which is the correct reading.

THE LEDGER IS DEBT, NOT AN EXEMPTION
------------------------------------
Same self-cleaning equality contract as the sibling file: adding a route seam
with no client wire turns this RED, and wiring one turns it RED until the entry
is deleted. The ledger can only shrink. The intended end state is empty.

OFFLINE ONLY: pure AST over two source files. No snapshot, no engine, no
network. Host-dependent: it imports ``core.*``, so it needs the host
application on the path and cannot run against the engine package alone.
"""
from __future__ import annotations

import ast
import pathlib
import unittest

import agents.daemon_slayer.server as server_mod
import core.daemon_slayer_client as client_mod

_SERVER_PY = pathlib.Path(server_mod.__file__)
_CLIENT_PY = pathlib.Path(client_mod.__file__)

_SEAM_PREFIXES = ("apply_", "assume_", "gate_", "exclude_")
_BODY_READERS = ("_opt_bool", "_opt_float", "_opt_int", "_opt_str",
                 "_coerce_str_list", "_required_str", "get")

# ------------------------------------------------------------ the debt ledger
# route -> seams that route parses but the client function POSTing that route
# cannot express. Measured by the introspection below at ENGINE 1.275.0, NOT
# copied from prose. 7 entries across 5 routes (was 4 across 2 at 1.254.0; the
# RM-172 uniform wiring added 3, one each on /stats, /anti-tank and
# /ally-protected-ehp - see the block at the end of this ledger).
#
# Wired across the RM-115 drain passes, and therefore ABSENT here:
#   apply_ability_base_overrides ... /ability-dps, /burst, /rank-assassin,
#                                    /rank-mage   (A-03 / RM-81, gates 2+3)
#   apply_passive_aura_damage ...... /ability-dps, /rank-mage
#                                    (A-07 / RM-82 TERM 2, gate 3)
#   the 20-seam EHP-family block ... /ehp, /hybrid, /rank-tank,
#                                    /rank-bruiser (1.253.0, 76 pairs)
#   the 21-pair tail ............... /burst 7, /dps 6, /rank-assassin 4,
#                                    /rank 2, /ability-dps 1, /rank-mage 1
#                                    (1.254.0)
#
# THE HONEST END STATE OF THIS LEDGER IS 7, NOT 0 (was 4 before RM-172). The
# routes below are
# DECLINED BY DESIGN, not undrained debt. Wiring them would flip the guard
# green while manufacturing reachability with no reader - precisely the
# reachable-and-dead illusion RM-115 exists to kill. Wire the CONSUMER first;
# only then wire the seam. Both decisions are re-checkable, and the exact
# conditions that would re-open each are recorded inline.
_STRANDED_BY_ROUTE: dict[str, frozenset[str]] = {
    # DECLINED 1.254.0. /beam has exactly one live consumer,
    # coaches/sr_draft_profile.py, and it holds its OWN HTTP call
    # (sr_draft_profile.py:271-304) rather than going through this client, for
    # two reasons that a migration would have to break: it needs a 4.0s budget
    # because a cold beam exceeds a second, against this module's deliberate
    # 0.5s DEFAULT_TIMEOUT fail-silent contract; and it needs the error STRING
    # to distinguish "engine HTTP {code}" from "engine unreachable", which
    # _post_json's None collapses. The seam itself is also arithmetically inert
    # for that consumer: it hardcodes mode="SR", and no champion in
    # wiki_stats.json carries an "sr" mode_modifiers key (the seven that exist
    # are ar/aram/nb/ofa/swift/urf/usb), so both lanes resolve to identity.
    # RE-OPEN IF: a non-SR beam consumer appears (an Arena or URF draft
    # profile). At that point the reorder-capable lane is the ADDEND lane
    # (ar/swift), not URF - see the /rank docstring in the client.
    '/beam': frozenset({
        'apply_mode_modifiers',
    }),
    # DECLINED 1.254.0. /v2/fight-report has ZERO callers repo-wide. Verified
    # by grep at 1.254.0: the literal "/v2/fight-report" appears only in its
    # own docstring, the dispatch table, docs/DAEMON_SLAYER.md, the CHANGELOG,
    # and these two ledgers. cli.py has no fight-report subcommand, and
    # test_fight_report.py / test_flag_wiring_item235.py call
    # compute_fight_report IN PROCESS, never the route. The route is served and
    # has never been requested by anything. The three seams are engine-complete
    # (gate_ammo -> mana_sim.py:600-604, apply_ability_haste ->
    # mana_sim.py:609-611, apply_mode_modifiers -> the self-shred physical-DPS
    # term), so this is a consumer gap, not an engine gap.
    # RE-OPEN IF: any caller of the ROUTE appears. Wire the consumer first.
    '/v2/fight-report': frozenset({
        'apply_ability_haste',
        'apply_mode_modifiers',
        'gate_ammo',
    }),
    # ---------------------------------------------------------------- RM-172
    # The three entries below were ADDED 2026-08-06 (ENGINE 1.275.0) by the
    # RM-172 uniform wiring, taking this ledger 4 -> 7. That is a real cost and
    # it is recorded rather than avoided: RM-172's decision (LEDGER 1217) was to
    # make ``apply_mode_modifiers`` ASKABLE on every route that can reach
    # ``build_champion``, DEFAULT-OFF, instead of leaving 45 champions' ARENA
    # stat lines unreachable. All three routes have NO client function at all -
    # verified by grep at 1.275.0, the literals "/stats", "/anti-tank" and
    # "/ally-protected-ehp" do not appear in core/daemon_slayer_client.py - so
    # per this file's own reading ("a route with NO client function at all has
    # every one of its seams stranded, which is the correct reading") they land
    # in the same category as /beam and /v2/fight-report above.
    #
    # This is a CONSUMER gap, not an engine gap: all three seams are wired end
    # to end and were proven by RESPONSE-CHANGES, not by signature, in
    # tests/test_rm172_mode_modifier_seam_characterization.py.
    # RE-OPEN EACH IF: a client function for that route appears. Add the keyword
    # argument to it and delete the entry here - do not grow this ledger.
    #
    # /stats is the direct build_champion route and the sharpest instance
    # RM-172 named; 45 of 45 arena-axis champions move on it.
    '/stats': frozenset({
        'apply_mode_modifiers',
    }),
    # /anti-tank forwards the flag only on its LIVE-build branch. Measured
    # UNOBSERVABLE today for a structural reason, not a broken transport: of the
    # 7 registry champions with a nonzero ap/ad ratio row, only KogMaw also
    # carries an ARENA axis, and KogMaw's only nonzero ratio is an AP ratio
    # while the ARENA addends move ad/as and never ap. Pinned by
    # test_antitank_is_unobservable_for_a_STRUCTURAL_reason.
    '/anti-tank': frozenset({
        'apply_mode_modifiers',
    }),
    # /ally-protected-ehp reaches compute_ehp, which has accepted the flag since
    # item 232; the consumer simply never forwarded it. 45 of 45 move.
    '/ally-protected-ehp': frozenset({
        'apply_mode_modifiers',
    }),
}


def _seam_keys(fn: ast.FunctionDef) -> set[str]:
    """Seam-shaped body keys read inside one ``_route_*`` handler."""
    keys: list[str] = []
    for node in ast.walk(fn):
        if isinstance(node, ast.Call):
            name = getattr(node.func, "id", None) or getattr(node.func, "attr", None)
            if name in _BODY_READERS:
                keys += [
                    a.value for a in node.args
                    if isinstance(a, ast.Constant) and isinstance(a.value, str)
                ]
        elif isinstance(node, ast.Compare) and isinstance(node.left, ast.Constant):
            # the ``"key" in body`` tri-state idiom
            if isinstance(node.left.value, str):
                keys.append(node.left.value)
    return {k for k in keys if k.startswith(_SEAM_PREFIXES)}


def _route_table() -> tuple[dict[str, frozenset[str]], dict[str, str]]:
    """``"/path" -> seams parsed`` and ``"/path" -> handler name``."""
    tree = ast.parse(_SERVER_PY.read_text(encoding="utf-8"))
    handlers = {
        f.name: f for f in ast.walk(tree)
        if isinstance(f, ast.FunctionDef) and f.name.startswith("_route_")
    }
    path_of: dict[str, str] = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.Dict):
            continue
        for k, v in zip(node.keys, node.values):
            if not (isinstance(k, ast.Constant) and isinstance(k.value, str)):
                continue
            if not k.value.startswith("/"):
                continue
            nm = getattr(v, "id", None) or getattr(v, "attr", None)
            if nm in handlers:
                path_of.setdefault(k.value, nm)
    parsed = {p: frozenset(_seam_keys(handlers[h])) for p, h in path_of.items()}
    return {p: s for p, s in parsed.items() if s}, path_of


def _client_by_route() -> dict[str, frozenset[str]]:
    """``"/path" -> names the client function(s) POSTing it can express``."""
    tree = ast.parse(_CLIENT_PY.read_text(encoding="utf-8"))
    out: dict[str, set[str]] = {}
    for fn in ast.walk(tree):
        if not isinstance(fn, ast.FunctionDef):
            continue
        posts: set[str] = set()
        for node in ast.walk(fn):
            if isinstance(node, ast.Call):
                nm = getattr(node.func, "id", None) or getattr(node.func, "attr", None)
                if nm == "_post_json" and node.args:
                    a = node.args[0]
                    if isinstance(a, ast.Constant) and isinstance(a.value, str):
                        posts.add(a.value)
        if not posts:
            continue
        a = fn.args
        names = {x.arg for x in list(a.posonlyargs) + list(a.args) + list(a.kwonlyargs)}
        for node in ast.walk(fn):
            if isinstance(node, ast.Subscript) and isinstance(node.slice, ast.Constant):
                if isinstance(node.slice.value, str):
                    names.add(node.slice.value)
            elif isinstance(node, ast.Dict):
                names.update(
                    k.value for k in node.keys
                    if isinstance(k, ast.Constant) and isinstance(k.value, str)
                )
        for p in posts:
            out.setdefault(p, set()).update(names)
    return {p: frozenset(n) for p, n in out.items()}


class PerRouteSeamReachabilityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.parsed, cls.path_of = _route_table()
        cls.client = _client_by_route()
        cls.stranded = {
            path: frozenset(seams - cls.client.get(path, frozenset()))
            for path, seams in cls.parsed.items()
        }
        cls.stranded = {p: s for p, s in cls.stranded.items() if s}

    def test_introspection_actually_found_routes(self) -> None:
        """Guard the guard - a broken parse must not read as a clean bill."""
        self.assertGreater(
            len(self.parsed), 10,
            "the server.py dispatch-table scan found almost no seam-parsing "
            "routes - the parse shape drifted, so every other assertion here "
            "is vacuous",
        )
        self.assertIn("/rank-tank", self.parsed)
        self.assertIn("/rank-mage", self.parsed)
        # the client side must resolve too, or everything reads as stranded
        self.assertIn("/rank", self.client)
        self.assertIn("/rank-mage", self.client)

    def test_no_new_per_route_stranded_seam(self) -> None:
        new = sorted(
            (path, seam)
            for path, seams in self.stranded.items()
            for seam in seams
            if seam not in _STRANDED_BY_ROUTE.get(path, frozenset())
        )
        self.assertEqual(
            new, [],
            "route seam(s) parsed by server.py that the client function "
            f"POSTing that route cannot express: {new}. Add the keyword "
            "argument to that specific client function rather than adding the "
            "pair to _STRANDED_BY_ROUTE.",
        )

    def test_ledger_has_no_stale_entries(self) -> None:
        stale = sorted(
            (path, seam)
            for path, seams in _STRANDED_BY_ROUTE.items()
            for seam in seams
            if seam not in self.stranded.get(path, frozenset())
        )
        self.assertEqual(
            stale, [],
            "these (route, seam) pairs are now reachable - delete them from "
            f"_STRANDED_BY_ROUTE so the debt ledger keeps shrinking: {stale}",
        )

    def test_rm115_wired_seams_are_reachable_on_their_own_routes(self) -> None:
        """The named RM-115 wirings, asserted per ROUTE rather than per name.

        This is the assertion the name-collapsed sibling guard cannot make:
        ``kit_conversion_strength`` was already a client keyword on the CARRY
        path, so the sibling stayed green while /rank-assassin could not set
        it. These pairs pin the actual wire.
        """
        expected = {
            "apply_ability_base_overrides": (
                "/ability-dps", "/burst", "/rank-assassin", "/rank-mage",
            ),
            "apply_passive_aura_damage": ("/ability-dps", "/rank-mage"),
        }
        for seam, routes in expected.items():
            for path in routes:
                self.assertIn(
                    seam, self.parsed.get(path, frozenset()),
                    f"{path} no longer parses {seam}",
                )
                self.assertIn(
                    seam, self.client.get(path, frozenset()),
                    f"{seam} is parsed by {path} but the client function "
                    f"POSTing {path} cannot express it",
                )

    def test_kit_conversion_reaches_the_assassin_route(self) -> None:
        """RM-83 Naafiri: the wire the name-based guard is blind to.

        ``kit_conversion_strength`` is not seam-PREFIXED, so it never appears
        in either ledger; and it was already expressible via ``rank_for`` on
        the carry path, so a name-based check reads green either way. Assert
        the route-specific pair directly.
        """
        for path in ("/rank", "/rank-assassin"):
            self.assertIn(
                "kit_conversion_strength", self.client.get(path, frozenset()),
                f"the client function POSTing {path} cannot set "
                "kit_conversion_strength",
            )

    def test_per_route_debt_is_never_smaller_than_the_name_collapsed_debt(
        self,
    ) -> None:
        """The structural relationship between the two ledgers.

        The original form of this test pinned a FLOOR of 33 - the sibling's
        size at the time - on the theory that the per-route total dropping
        below it would mean the two files had stopped measuring what their
        docstrings claim. That premise was wrong, and draining the EHP-family
        block at 1.253.0 disproved it: the per-route total legitimately fell to
        25 while the sibling fell to 12. A hard floor was never the invariant.

        The real one is an inequality that holds by construction. If a seam is
        stranded by NAME it is expressible from no client function at all, so it
        is stranded on EVERY route that parses it - at least one (route, seam)
        pair. Therefore per-route total >= name-collapsed total, always, and
        equality only when every stranded name is parsed by exactly one route.
        A violation means one of the two introspections has drifted.
        """
        from agents.daemon_slayer.tests import (  # noqa: PLC0415
            test_route_seams_reach_the_client as sibling,
        )

        per_route = sum(len(s) for s in _STRANDED_BY_ROUTE.values())
        by_name = len(sibling._STRANDED_TODAY)
        self.assertGreaterEqual(
            per_route, by_name,
            f"per-route debt ({per_route}) is below the name-collapsed debt "
            f"({by_name}), which is impossible if both introspections are "
            "sound: a name stranded everywhere must contribute at least one "
            "(route, seam) pair. One of the two scans has drifted.",
        )
        # And the gap is the whole reason this file exists - if it ever closes,
        # every stranded name is single-route and the sibling would suffice.
        self.assertGreater(
            per_route, by_name,
            "the two ledgers have converged; re-read both docstrings before "
            "assuming this file still earns its keep",
        )


if __name__ == "__main__":
    unittest.main()
