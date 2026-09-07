"""RM-172 characterization: the ``apply_mode_modifiers`` seam, pinned END TO END.

RM-169 pinned ONE path (``matchup.compute_matchup``). This file pins the whole
seam, so a PARTIAL wiring cannot land silently. MEASURED 2026-08-06 at
ENGINE 1.275.0 / patch 16.15.1.

STATUS: the seam is now WIRED UNIFORMLY (LEDGER 1217, executed 2026-08-06). It
stays DEFAULT-OFF everywhere - the acceptance was that the axis became ASKABLE,
not that it became active. The three gates moved A 13 -> 25, B 8 -> 19 of 34,
C 6 -> 14. What this file pinned BEFORE that change was the partial state; those
assertions are inverted below rather than deleted, and the weak
"SOME routes are blind" check has been REPLACED by a strictly stronger
machine-checked invariant (``parses IFF transitively reaches build_champion``)
plus per-route RESPONSE-CHANGES proof. A test that the parameter is merely
ACCEPTED is not proof a transport carries it; only a changed response is.

WHAT THE FLAG ACTUALLY GATES (this is the finding that reframes the row).
``build_champion`` has TWO mode lanes and the flag gates only ONE of them:

* ``engine._resolve_mode_addends`` (engine.py:106) - the ARENA/Swiftplay
  stat-growth ADDEND lane. Reads the wiki sidecar via
  ``DataSnapshot.mode_modifier(champ, mode)``. THIS is the 45-champion ``ar``
  axis. It is called ONLY when ``apply_mode_modifiers`` is True (engine.py:329).
* ``engine._apply_mode_modifiers`` (engine.py:225) - the ARAM MULTIPLIER lane
  (aramAttackSpeed / aramAbilityHaste / aramTenacity). It is called
  UNCONDITIONALLY at engine.py:450 and early-returns for any mode != "ARAM".

So the function named ``_apply_mode_modifiers`` and the flag named
``apply_mode_modifiers`` do NOT control each other. Do not read one as evidence
about the other.

THE ARENA TABLE EXISTS. This row is a WIRING row, not a data row, for the
addend lane: ``mode_modifier(champ, "ARENA")`` returns real per-champion axes
for 45 of 173 champions (``test_arena_addend_table_exists``). What does NOT
exist for ARENA is a MULTIPLIER table - and Riot publishes no such axis for
Arena, so there is nothing upstream to plug in there.

THE ENGINE NOTE AT engine.py:458 IS MISLEADING, AND IT IS WHY THIS ROW EXISTS.
It appends "mode=ARENA - modifier table not plugged in for this mode" whenever
``mode not in ("SR", "ARAM")`` - including on calls where the ARENA addend
table WAS resolved and applied one line earlier. The two notes contradict each
other in the same list. That is pinned by
``test_engine_note_contradicts_itself_when_addends_applied`` so the wording
cannot be "fixed" without someone reading this file first. Changing that string
is an engine-output change and would need an ENGINE_VERSION bump, which is why
RM-172 does NOT change it.

COST OF THE CURRENT STATE (measured, see the module docstring assertions below).
No production caller anywhere in the repo sets the flag True - the only non-test
occurrences of ``apply_mode_modifiers=True`` are docstrings. So every shipped
ARENA number today, including the generated ARENA build-order tables, is
computed from the SR stat line for those 45 champions. THAT IS STILL TRUE after
the RM-172 wiring: wiring made the axis reachable, it did not arm it, and no
table was regenerated. ``test_no_production_caller_sets_the_flag_true`` is the
guard that keeps the tables and the engine in agreement.

Deliberately NOT asserted here as exact numbers, because they are data-fragile
across a patch bump and this file must survive a DDragon re-extract: the L18
stat error reaches +21.3 pct (MissFortune ad 95.80 -> 116.20) and -14.5 pct
(Kalista hp at L11); ``compute_dps.weighted_dps`` moves on 17 of 45 champions
and ``compute_ehp.blended_ehp`` on 39 of 45, both mean |7.6-7.9| pct; and
``rank_items`` ORDER flips on 37 of 45 at L11 while the top-1 pick changes on
only 4 of 45 (0 of 45 for ``rank_items_by_ehp``). The tests below assert the
DIRECTION and the POPULATION of those effects, which are structural, rather
than the magnitudes, which are not.
"""

from __future__ import annotations

import ast
import importlib
import inspect
import json
import pkgutil
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import agents.daemon_slayer as ds_pkg  # noqa: E402
from agents.daemon_slayer.data_loader import DataSnapshot  # noqa: E402
from agents.daemon_slayer.engine import build_champion  # noqa: E402

FLAG = "apply_mode_modifiers"

# GATE A - engine/scorer functions that ACCEPT the kwarg. Measured with
# inspect.signature, never inherited from a docstring (see CLAUDE.md: the
# RM-118 ownership prose was wrong in OPPOSITE directions in a single run).
EXPECTED_GATE_A = {
    # Pre-RM-172 (13).
    "beam.beam_search_build",
    "dps.compute_dps",
    "dps.compute_dps_curve",
    "ehp.compute_ehp",
    "ehp.ehp_gold_efficiency",
    "ehp.rank_items_by_ehp",
    "engine.build_champion",
    "fight_report.compute_fight_report",
    "hybrid.compute_hybrid",
    "hybrid.rank_items_by_hybrid",
    "onhit_dps.compute_onhit_dps",
    "onhit_dps.rank_items_by_onhit",
    "rank.rank_items",
    # RM-172 widening (12). Every one of these already resolved a champion via
    # build_champion but had no way to ask for the corrected stat line.
    "_rank_mage.rank_items_by_ability_dps",
    "ability_dps.compute_ability_dps",
    "ability_hps.compute_ability_hps",
    "antitank.compute_antitank_live",
    "burst.compute_burst_damage",
    "burst.rank_items_by_burst",
    "dsp_live_consumers.ally_protected_ehp",
    "hps.compute_hps",
    "hps.rank_items_by_hps",
    "matchup.compute_matchup",
    "matchup._combo_into",
    "matchup._defensive_stats",
}

# GATE B - HTTP routes that PARSE the flag out of the POST body.
EXPECTED_GATE_B = {
    # Pre-RM-172 (8).
    "_route_beam",
    "_route_dps",
    "_route_ehp",
    "_route_fight_report",
    "_route_hybrid",
    "_route_rank",
    "_route_rank_bruiser",
    "_route_rank_tank",
    # RM-172 widening (11).
    "_route_ability_dps",
    "_route_ally_protected_ehp",
    "_route_antitank",
    "_route_burst",
    "_route_hps",
    "_route_matchup",
    "_route_rank_assassin",
    "_route_rank_enchanter",
    "_route_rank_mage",
    "_route_rank_onhit",
    "_route_stats",
}

# GATE C - core/daemon_slayer_client.py transport functions carrying the flag.
EXPECTED_GATE_C = {
    # Pre-RM-172 (6).
    "dps_for",
    "ehp_for",
    "hybrid_for",
    "rank_bruiser_for",
    "rank_for",
    "rank_tank_for",
    # RM-172 widening (8).
    "ability_dps_for",
    "burst_for",
    "hps_for",
    "matchup",
    "rank_assassin_for",
    "rank_enchanter_for",
    "rank_mage_for",
    "rank_onhit_for",
}

# Routes with NO client function at all. Gate C is VACUOUS for these, not
# incoherent - RM-172 wired the flag, it did not invent a client API surface.
# These are the same five carried as DECLINED-BY-DESIGN debt in
# agents/daemon_slayer/tests/test_route_seams_reach_the_client_per_route.py;
# keep the two lists in step.
ROUTES_WITH_NO_CLIENT_FN = {
    "/stats", "/beam", "/v2/fight-report", "/anti-tank", "/ally-protected-ehp",
}

_SNAP: DataSnapshot | None = None


def _snapshot() -> DataSnapshot:
    global _SNAP
    if _SNAP is None:
        _SNAP = DataSnapshot.load()
    return _SNAP


def _measure_gate_a() -> set[str]:
    found: set[str] = set()
    for mi in pkgutil.iter_modules(ds_pkg.__path__):
        name = f"agents.daemon_slayer.{mi.name}"
        # Narrow on purpose: every DS module imports cleanly today, so any
        # NON-import failure should surface loudly rather than silently shrink
        # the measured gate-A set (a swallowed error would read as "this
        # function no longer accepts the kwarg").
        try:
            mod = importlib.import_module(name)
        except ImportError:
            continue
        for fname, fn in vars(mod).items():
            if not inspect.isfunction(fn) or fn.__module__ != name:
                continue
            try:
                sig = inspect.signature(fn)
            except (ValueError, TypeError):
                continue
            if FLAG in sig.parameters:
                found.add(f"{mi.name}.{fname}")
    return found


def _route_defs() -> dict[str, bool]:
    """Per-route: does the handler REALLY read the flag and forward it?

    DELIBERATELY NOT a substring match over the route's source segment. That is
    what this helper did until 2026-08-07, and an adversarial pass proved it
    blind in one direction: the RM-172 prose on ``_route_stats`` and
    ``_route_matchup`` names the flag inside a DOCSTRING, so a handler that
    stopped parsing AND stopped forwarding it still measured as parses=True on
    the strength of its own comment. A mutant that made /stats reach
    build_champion without parsing stayed GREEN, with 0 flag literals and 0
    keyword forwards left in the handler. Exactly 2 of the 19 wired routes were
    affected, and for those two the response-changes proof was the ONLY guard.

    A route counts only when BOTH of these hold, and both are read off the AST
    so prose can never satisfy either:

      * the flag appears as a STRING LITERAL ARGUMENT to a call - i.e. it is
        actually looked up out of the request body - and
      * the flag appears as a CALL KEYWORD - i.e. it is forwarded downstream.

    Requiring both is also strictly better than the old "parses" question:
    parse-without-forward is precisely the settable-but-inert shape RM-172
    found live on /v2/fight-report, and it now reads as False rather than True.
    """
    src = (REPO_ROOT / "agents/daemon_slayer/server.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    out: dict[str, bool] = {}
    for node in ast.walk(tree):
        if not (isinstance(node, ast.FunctionDef)
                and node.name.startswith("_route_")):
            continue
        reads = forwards = False
        for sub in ast.walk(node):
            if isinstance(sub, ast.Call):
                # "apply_mode_modifiers" passed as a literal arg to a body
                # reader such as _opt_bool(body, "apply_mode_modifiers", False).
                for arg in sub.args:
                    if isinstance(arg, ast.Constant) and arg.value == FLAG:
                        reads = True
                for kw in sub.keywords:
                    if kw.arg == FLAG:
                        forwards = True
            elif isinstance(sub, ast.Subscript):
                # defensive: the body["key"] form, unused for this flag today
                idx = sub.slice
                if isinstance(idx, ast.Constant) and idx.value == FLAG:
                    reads = True
            elif isinstance(sub, ast.Compare) and isinstance(sub.left, ast.Constant):
                # defensive: the `"key" in body` tri-state idiom
                if sub.left.value == FLAG:
                    reads = True
        out[node.name] = reads and forwards
    return out


def _reaches_build_champion() -> dict[str, bool]:
    """Per-route: can it reach ``engine.build_champion`` transitively?

    AST call-graph over the whole ``agents/daemon_slayer`` package, matched on
    call NAME (plain and attribute form). Deliberately name-based rather than
    import-resolved: it over-approximates rather than under-approximates, so a
    genuinely unreachable route is never mistaken for a reachable one, which is
    the direction that would let a real gap through.
    """
    calls: dict[str, set[str]] = {}
    for py in sorted((REPO_ROOT / "agents/daemon_slayer").glob("*.py")):
        try:
            tree = ast.parse(py.read_text(encoding="utf-8"))
        except (SyntaxError, OSError, UnicodeDecodeError):
            continue
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            found: set[str] = set()
            for sub in ast.walk(node):
                if isinstance(sub, ast.Call):
                    fn = sub.func
                    if isinstance(fn, ast.Name):
                        found.add(fn.id)
                    elif isinstance(fn, ast.Attribute):
                        found.add(fn.attr)
            calls.setdefault(node.name, set()).update(found)

    def walk(fn: str, seen: set[str]) -> bool:
        if fn in seen:
            return False
        seen.add(fn)
        for callee in calls.get(fn, ()):
            if callee == "build_champion":
                return True
            if callee in calls and walk(callee, seen):
                return True
        return False

    return {n: walk(n, set()) for n in calls if n.startswith("_route_")}


def _client_fns() -> set[str]:
    src = (REPO_ROOT / "core/daemon_slayer_client.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    out: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            names = [a.arg for a in node.args.args + node.args.kwonlyargs]
            if FLAG in names:
                out.add(node.name)
    return out


def _arena_axis_champions(snap: DataSnapshot) -> list[str]:
    return [c for c in sorted(snap.champions) if snap.mode_modifier(c, "ARENA")]


class TestSeamThreeGates(unittest.TestCase):
    """The three gates a DS seam has to clear: kwarg, route parse, transport."""

    def test_gate_a_kwarg_acceptance_is_exactly_these_functions(self):
        self.assertEqual(
            _measure_gate_a(),
            EXPECTED_GATE_A,
            "GATE A drift: a function gained or lost the apply_mode_modifiers "
            "kwarg. If this is an intentional widening, update EXPECTED_GATE_A "
            "AND check gates B and C in the same change - a kwarg nobody can "
            "reach over HTTP is inert.",
        )

    def test_gate_b_route_parse_is_exactly_these_routes(self):
        parsing = {name for name, parses in _route_defs().items() if parses}
        self.assertEqual(
            parsing,
            EXPECTED_GATE_B,
            "GATE B drift: the set of routes parsing apply_mode_modifiers "
            "changed. A partial wiring is exactly what RM-172 exists to catch.",
        )

    def test_gate_c_client_transport_is_exactly_these_functions(self):
        self.assertEqual(
            _client_fns(),
            EXPECTED_GATE_C,
            "GATE C drift: core/daemon_slayer_client.py transport coverage "
            "changed. A flag the transport does not carry is settable, "
            "guard-green and arithmetically INERT (measured precedent, "
            "reference_ds_route_seam_transport_vs_flag).",
        )

    def test_seam_is_COHERENT_parses_iff_reaches_build_champion(self):
        """RM-172's acceptance, as a machine-checked invariant.

        REPLACES the old ``test_seam_is_currently_INCOHERENT_by_construction``,
        which asserted only that SOME routes were blind. That was a weak,
        one-directional check: it passed for the shipped partial state AND for
        almost any other partial state. The invariant below is strictly
        stronger in both directions -

        * a route that can reach ``build_champion`` but does NOT parse the flag
          is an UNASKABLE axis (the RM-172 defect), and
        * a route that parses the flag but can never reach ``build_champion``
          is a SETTABLE-BUT-INERT seam (the RM-115 defect, memory
          ``reference_ds_route_seam_transport_vs_flag``).

        Reachability is computed transitively over the whole DS package by AST,
        not read off a docstring - CLAUDE.md records a run where the ownership
        prose was wrong in OPPOSITE directions for two lanes at once.
        """
        routes = _route_defs()
        reach = _reaches_build_champion()
        violations = sorted(
            (name, parses, reach.get(name, False))
            for name, parses in routes.items()
            if parses != reach.get(name, False)
        )
        self.assertEqual(
            violations,
            [],
            "parses/reaches disagree (name, parses_flag, reaches_build_champion). "
            "parses=False reaches=True -> the axis is unaskable on that route. "
            "parses=True reaches=False -> the flag is settable and inert.",
        )
        # Guard against the invariant passing vacuously if the route table or
        # the reachability walk ever collapses to empty.
        self.assertGreaterEqual(len(routes), 30, "route table collapsed")
        self.assertGreaterEqual(
            sum(1 for v in routes.values() if v), 19,
            "the parsing-route population shrank below the RM-172 measurement",
        )

    def test_the_sharpest_pre_rm172_instances_are_now_wired(self):
        """The specific routes RM-172 named, asserted INDIVIDUALLY.

        The invariant above would still pass if all of these regressed together
        with their reachability; naming them keeps the row's actual findings
        pinned. Inverted from the pre-wiring assertions, not deleted.
        """
        routes = _route_defs()
        # /stats is the direct build_champion route - the sharpest instance.
        self.assertTrue(
            routes.get("_route_stats"),
            "/stats no longer parses the flag; it is the direct build_champion "
            "route and the one route RM-172 said must work",
        )
        # The four archetype rankers that exposed no way to set it.
        for name in ("_route_rank_mage", "_route_rank_assassin",
                     "_route_rank_enchanter", "_route_rank_onhit"):
            self.assertTrue(routes.get(name), f"{name} stopped parsing {FLAG}")
        # /beam and /v2/fight-report parsed it before RM-172 but had no client
        # function; they must still parse it.
        for name in ("_route_beam", "_route_fight_report"):
            self.assertTrue(routes.get(name), f"{name} stopped parsing {FLAG}")

    def test_routes_without_a_client_fn_are_a_known_closed_set(self):
        """Gate C is VACUOUS, not incoherent, for three routes.

        ``/stats``, ``/beam`` and ``/v2/fight-report`` have no client function
        at all - not a client function missing the flag. RM-172 wired the seam;
        it deliberately did not invent a new client API surface. If a client
        function is ever added for one of these, it must carry the flag and this
        set must shrink in the same change.
        """
        src = (REPO_ROOT / "core/daemon_slayer_client.py").read_text(
            encoding="utf-8"
        )
        for path in sorted(ROUTES_WITH_NO_CLIENT_FN):
            self.assertNotIn(
                f'_post_json("{path}"',
                src,
                f"a client function for {path} now exists; it must carry "
                f"{FLAG} and be added to EXPECTED_GATE_C",
            )

    def test_no_production_caller_sets_the_flag_true(self):
        """Every shipped ARENA number is computed with the flag OFF.

        Only docstrings mention the True form outside tests. If a production
        caller ever sets it, the generated ARENA build-order / laning tables
        must be regenerated in the same change or the tables and the live
        engine will disagree.
        """
        needle = f"{FLAG}=True"
        offenders: list[str] = []
        skip_parts = ("tests", "test_", "docs", "_archive")
        for py in REPO_ROOT.rglob("*.py"):
            rel = py.relative_to(REPO_ROOT).as_posix()
            if any(p in rel for p in skip_parts):
                continue
            try:
                src = py.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            if needle not in src:
                continue
            tree = ast.parse(src, filename=rel)
            docstrings = set()
            for node in ast.walk(tree):
                if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef,
                                     ast.AsyncFunctionDef)):
                    doc = ast.get_docstring(node, clean=False)
                    if doc:
                        docstrings.add(doc)
            # A real call site is a keyword arg literal-True in the AST.
            for node in ast.walk(tree):
                if isinstance(node, ast.Call):
                    for kw in node.keywords:
                        if (kw.arg == FLAG and isinstance(kw.value, ast.Constant)
                                and kw.value.value is True):
                            offenders.append(f"{rel}:{node.lineno}")
            if needle in src and not any(needle in d for d in docstrings):
                pass  # comment-only mentions are harmless
        self.assertEqual(
            offenders,
            [],
            "a production caller now sets apply_mode_modifiers=True; the "
            "generated ARENA tables were built with it OFF and must be "
            "regenerated in the SAME change (see RM-155 on regen cost)",
        )


class TestArenaTableExists(unittest.TestCase):
    """Is this a wiring row or a data row? Wiring - the table is present."""

    def test_arena_addend_table_exists(self):
        snap = _snapshot()
        movers = _arena_axis_champions(snap)
        self.assertEqual(
            len(snap.champions), 173, "champion roster size changed"
        )
        self.assertEqual(
            len(movers),
            45,
            "the ARENA 'ar' axis population changed; RM-172 measured 45 of 173",
        )
        axes = {k for c in movers for k in snap.mode_modifier(c, "ARENA")}
        self.assertEqual(
            axes,
            {"arm_lvl", "as_lvl", "dam_lvl", "hp_base", "hp_lvl"},
            "the ARENA axis KEY SET changed - a new axis may need a "
            "_ADDEND_AXIS_MAP entry in engine.py or it is silently dropped",
        )

    def test_every_arena_axis_key_is_mapped_by_the_engine(self):
        """An unmapped axis is discarded silently by _resolve_mode_addends."""
        from agents.daemon_slayer.engine import _ADDEND_AXIS_MAP

        snap = _snapshot()
        axes = {
            k
            for c in _arena_axis_champions(snap)
            for k in snap.mode_modifier(c, "ARENA")
        }
        unmapped = axes - set(_ADDEND_AXIS_MAP)
        self.assertEqual(
            unmapped,
            set(),
            f"ARENA axes present in the data but dropped by the engine: {unmapped}",
        )

    def test_arena_multiplier_lane_is_genuinely_absent(self):
        """The OTHER half of engine.py:458 - no ARENA multiplier axis exists.

        _apply_mode_modifiers reads champ['lolmath']['aram_modifiers']. There is
        no arena_modifiers sibling, and Riot publishes no such axis for Arena,
        so that half is not a wiring gap that could be closed.
        """
        snap = _snapshot()
        for cid in sorted(snap.champions)[:40]:
            lolmath = snap.champion(cid).get("lolmath", {}) or {}
            self.assertNotIn(
                "arena_modifiers",
                lolmath,
                f"{cid} unexpectedly carries an arena multiplier block - if "
                "this appears, engine._apply_mode_modifiers must grow an "
                "ARENA branch and engine.py:458 becomes accurate",
            )


class TestCurrentBehaviourPinned(unittest.TestCase):
    """What the seam does TODAY, so a partial wiring cannot land silently."""

    def test_default_off_arena_stat_block_equals_sr_for_all_173(self):
        snap = _snapshot()
        for cid in sorted(snap.champions):
            for lvl in (2, 11, 18):
                sr = build_champion(snap, cid, lvl, [], mode="SR")
                ar = build_champion(snap, cid, lvl, [], mode="ARENA")
                self.assertEqual(
                    sr.stats,
                    ar.stats,
                    f"{cid} L{lvl}: ARENA stat block diverged from SR at the "
                    "DEFAULT. If this is intentional, RM-172's premise is "
                    "obsolete and this file must be rewritten.",
                )

    def test_flag_on_moves_exactly_the_45_and_nobody_else(self):
        snap = _snapshot()
        movers = set(_arena_axis_champions(snap))
        for cid in sorted(snap.champions):
            off = build_champion(snap, cid, 18, [], mode="ARENA",
                                 apply_mode_modifiers=False)
            on = build_champion(snap, cid, 18, [], mode="ARENA",
                                apply_mode_modifiers=True)
            moved = off.stats != on.stats
            self.assertEqual(
                moved,
                cid in movers,
                f"{cid}: moved={moved} but has_arena_axis={cid in movers} - "
                "the axis population and the behavioural effect must agree",
            )

    def test_flag_is_inert_for_sr_and_aram(self):
        """The flag must not perturb the two modes RC actually ships most."""
        snap = _snapshot()
        for cid in sorted(snap.champions)[:60]:
            for mode in ("SR", "ARAM"):
                off = build_champion(snap, cid, 18, [], mode=mode,
                                     apply_mode_modifiers=False)
                on = build_champion(snap, cid, 18, [], mode=mode,
                                    apply_mode_modifiers=True)
                self.assertEqual(
                    off.stats, on.stats,
                    f"{cid} {mode}: the flag is supposed to be a no-op here",
                )

    def test_engine_note_contradicts_itself_when_addends_applied(self):
        """engine.py:458 says the table is not plugged in on a call that just
        plugged it in. Pinned so the wording is fixed deliberately, not by
        accident - it is engine OUTPUT, so changing it needs an ENGINE_VERSION
        bump on the same commit.
        """
        snap = _snapshot()
        movers = _arena_axis_champions(snap)
        self.assertTrue(movers)
        cid = movers[0]
        on = build_champion(snap, cid, 11, [], mode="ARENA",
                            apply_mode_modifiers=True)
        applied = [n for n in on.notes if "stat-growth addends applied" in n]
        denied = [n for n in on.notes if "modifier table not plugged in" in n]
        self.assertTrue(applied, f"{cid}: expected an addends-applied note")
        self.assertTrue(
            denied,
            "expected the (contradictory) not-plugged-in note; if it is gone, "
            "engine.py:458 was corrected - delete this test and confirm "
            "ENGINE_VERSION moved with it",
        )

    def test_notes_differ_by_mode_even_at_the_default(self):
        snap = _snapshot()
        for cid in sorted(snap.champions)[:40]:
            sr = build_champion(snap, cid, 11, [], mode="SR")
            ar = build_champion(snap, cid, 11, [], mode="ARENA")
            self.assertNotEqual(sr.notes, ar.notes, f"{cid}: notes matched")
            self.assertTrue(
                any("not plugged in" in n for n in ar.notes),
                f"{cid}: ARENA lost its not-plugged-in note",
            )


class TestDownstreamCostDirection(unittest.TestCase):
    """The axis is MATERIAL, not cosmetic - structural assertions only.

    Magnitudes are deliberately not pinned (data-fragile across a patch bump).
    """

    def test_flag_moves_dps_and_ehp_for_a_substantial_minority(self):
        from agents.daemon_slayer import dps as ds_dps, ehp as ds_ehp

        snap = _snapshot()
        movers = _arena_axis_champions(snap)
        dps_moved = ehp_moved = 0
        for cid in movers:
            a = ds_dps.compute_dps(snap, cid, 11, [], mode="ARENA",
                                   apply_mode_modifiers=False)
            b = ds_dps.compute_dps(snap, cid, 11, [], mode="ARENA",
                                   apply_mode_modifiers=True)
            if abs(a.weighted_dps - b.weighted_dps) > 1e-6:
                dps_moved += 1
            c = ds_ehp.compute_ehp(snap, cid, 11, [], mode="ARENA",
                                   apply_mode_modifiers=False)
            d = ds_ehp.compute_ehp(snap, cid, 11, [], mode="ARENA",
                                   apply_mode_modifiers=True)
            if abs(c.blended_ehp - d.blended_ehp) > 1e-6:
                ehp_moved += 1
        self.assertGreater(
            dps_moved, 5,
            "weighted_dps stopped responding to the ARENA addends; RM-172 "
            "measured 17 of 45 at L11",
        )
        self.assertGreater(
            ehp_moved, 20,
            "blended_ehp stopped responding to the ARENA addends; RM-172 "
            "measured 39 of 45 at L11",
        )

    def test_flag_reorders_arena_item_rankings(self):
        """The number that decides the row: shipped ARENA build tables move."""
        from agents.daemon_slayer import rank as ds_rank

        snap = _snapshot()
        movers = _arena_axis_champions(snap)
        flips = 0
        for cid in movers:
            a = [r.item_id for r in ds_rank.rank_items(
                snap, cid, 11, [], mode="ARENA",
                apply_mode_modifiers=False).ranked]
            b = [r.item_id for r in ds_rank.rank_items(
                snap, cid, 11, [], mode="ARENA",
                apply_mode_modifiers=True).ranked]
            if a != b:
                flips += 1
        self.assertGreater(
            flips, 20,
            "rank_items ORDER stopped responding to the ARENA addends; RM-172 "
            "measured 37 of 45 at L11. If this drops to 0 the axis has become "
            "cosmetic and the row can be closed as 'discard on purpose'.",
        )


class TestTransportActuallyCarriesTheFlag(unittest.TestCase):
    """RESPONSE-CHANGES proof, per route. Signature evidence is NOT proof.

    ``inspect.signature`` says a kwarg exists; it says nothing about whether the
    route forwards it, or whether the value survives to the arithmetic. The
    measured precedent in this repo is a seam that was settable, guard-green and
    arithmetically INERT (``reference_ds_route_seam_transport_vs_flag``), and
    RM-172 found a live instance of exactly that in ``/v2/fight-report``: it
    parsed the flag and forwarded it to ``compute_fight_report``, which passed
    it to ONE of its five sections, and 0 of 45 arena-axis champions moved.

    Each case below calls the real route handler twice with the SAME body except
    for the flag, and asserts the serialized response differs. The champion on
    each row was measured 2026-08-06 to move on that route; the counts in the
    comments are the full 45-champion population for context, not assertions
    (they are patch-fragile).
    """

    # route handler -> (champion measured to move, body factory)
    CASES = {
        "_route_stats": ("Akali", 45),            # 45/45
        "_route_dps": ("Akali", 45),              # 45/45
        "_route_ehp": ("Akali", 45),              # 45/45
        "_route_hybrid": ("Akali", 44),           # 44/45
        "_route_rank": ("Akali", 43),             # 43/45
        "_route_rank_tank": ("Akali", 39),        # 39/45
        "_route_rank_bruiser": ("Akali", 44),     # 44/45
        "_route_beam": ("Akshan", 39),            # 39/45
        # 2/45 MOVE. Not "2 carriers" - 19 of the 45 carry nonzero ability HPS
        # (measured 2026-08-07). The other 17 heal off ``ap``, and the ARENA
        # addends move hp/ad/armor/as and never ``ap``, so only Briar and Galio
        # can move. Both halves of the HPS lane are wired correctly; the small
        # number is the data, not a gap.
        "_route_fight_report": ("Briar", 2),      # 2/45
        "_route_ability_dps": ("Akali", 45),      # 45/45
        "_route_rank_mage": ("Akshan", 28),       # 28/45
        "_route_rank_onhit": ("Akali", 43),       # 43/45
        "_route_burst": ("Akali", 45),            # 45/45
        "_route_rank_assassin": ("Akshan", 20),   # 20/45
        "_route_hps": ("Briar", 2),               # 2/45 move, 19/45 carry
        "_route_rank_enchanter": ("Briar", 2),    # 2/45 move, 19/45 carry
        "_route_matchup": ("Akali", 45),          # 45/45
        "_route_ally_protected_ehp": ("Akali", 45),  # 45/45
    }

    LVL = 11

    @classmethod
    def setUpClass(cls):
        from agents.daemon_slayer import server as ds_server

        cls.server = ds_server
        ds_server._CACHE.set(_snapshot())

    # Per-route EXTRA body keys. These are not decoration: the effect is
    # input-sensitive, and a body that differs from the one that was measured
    # can make a correctly-wired route look inert (adding target_max_hp=2000 to
    # /rank-onhit is enough to stop Akali moving). Each row below is exactly the
    # body the 2026-08-06 sweep used for that route.
    _AR_MR = {"target_armor": 60, "target_mr": 40}
    _AR_MR_HP = {"target_armor": 60, "target_mr": 40, "target_max_hp": 2000}
    EXTRA = {
        "_route_stats": {},
        "_route_ehp": {},
        "_route_hps": {},
        "_route_ally_protected_ehp": {},
        "_route_rank_tank": {"top": 8},
        "_route_rank_enchanter": {"top": 8},
        "_route_dps": _AR_MR_HP,
        "_route_hybrid": _AR_MR_HP,
        "_route_fight_report": _AR_MR_HP,
        "_route_ability_dps": _AR_MR_HP,
        "_route_burst": _AR_MR_HP,
        "_route_rank": {**_AR_MR, "top": 8},
        "_route_rank_mage": {**_AR_MR, "top": 8},
        "_route_rank_onhit": {**_AR_MR, "top": 8},
        "_route_rank_assassin": {**_AR_MR, "top": 8},
        "_route_rank_bruiser": {**_AR_MR, "top": 8},
        "_route_beam": {**_AR_MR, "slots": 2, "beam_width": 3, "top": 3},
    }

    def _body(self, route: str, champ: str) -> dict:
        lvl = self.LVL
        if route == "_route_matchup":
            return {"champ_a": champ, "champ_b": champ, "level_a": lvl,
                    "level_b": lvl, "mode": "ARENA"}
        base = {"champion": champ, "level": lvl, "mode": "ARENA"}
        return {**base, **self.EXTRA[route]}

    def test_the_proof_set_covers_every_parsing_route(self):
        """Without this, a new wired route could ship with no proof at all.

        CASES must be exactly the gate-B set minus ``_route_antitank``, which
        is covered by the structural test below instead. If a route is added to
        gate B, this fails until it gets a response-changes case (or a
        documented structural one).
        """
        covered = set(self.CASES) | {"_route_antitank"}
        parsing = {n for n, v in _route_defs().items() if v}
        self.assertEqual(
            covered,
            parsing,
            "the response-changes proof set and the set of routes parsing the "
            "flag have diverged; every wired route needs evidence",
        )
        self.assertEqual(set(self.CASES), set(self.EXTRA) | {"_route_matchup"},
                         "CASES and EXTRA disagree on the route list")

    def test_every_wired_route_changes_its_response_when_the_flag_is_set(self):
        for route, (champ, _pop) in sorted(self.CASES.items()):
            with self.subTest(route=route, champion=champ):
                fn = getattr(self.server, route)
                off_body = self._body(route, champ)
                on_body = dict(off_body, apply_mode_modifiers=True)
                off = json.dumps(fn(off_body), sort_keys=True, default=str)
                on = json.dumps(fn(on_body), sort_keys=True, default=str)
                self.assertNotEqual(
                    off,
                    on,
                    f"{route} returned an IDENTICAL response with "
                    f"{FLAG}=True for {champ} in ARENA. The route parses the "
                    "flag but the value is not reaching the arithmetic - that "
                    "is the settable-but-inert failure, not a passing seam.",
                )

    def test_the_flag_is_a_no_op_at_the_default_for_every_wired_route(self):
        """Omitting the key must be byte-identical to sending it False.

        This is the other half of DEFAULT-OFF: RM-172 wired 11 new routes, and
        every existing caller omits the key entirely.
        """
        for route, (champ, _pop) in sorted(self.CASES.items()):
            with self.subTest(route=route, champion=champ):
                fn = getattr(self.server, route)
                omitted = self._body(route, champ)
                explicit = dict(omitted, apply_mode_modifiers=False)
                a = json.dumps(fn(omitted), sort_keys=True, default=str)
                b = json.dumps(fn(explicit), sort_keys=True, default=str)
                self.assertEqual(
                    a, b, f"{route}: omitted key != explicit False"
                )

    def test_antitank_is_unobservable_for_a_STRUCTURAL_reason(self):
        """/anti-tank parses and forwards the flag but cannot be seen to move.

        Not a broken transport - a genuinely empty intersection, so it gets a
        structural assertion instead of a response-changes one. Measured
        2026-08-06: the anti-tank registry has 7 champions with a nonzero
        ap/ad ratio row, exactly ONE of them (KogMaw) also carries an ARENA
        axis, and KogMaw's only nonzero ratio is an AP ratio - while the ARENA
        addend axes move ``ad`` and ``as`` and never ``ap``. If either
        population changes this test fails and the route gets a real
        response-changes case.
        """
        from agents.daemon_slayer import antitank as ds_antitank

        snap = _snapshot()
        movers = set(_arena_axis_champions(snap))
        ratio_champs = set()
        for cid, rows in ds_antitank._ANTITANK_REGISTRY.items():
            for row in (rows if isinstance(rows, (list, tuple)) else [rows]):
                if (getattr(row, "ap_ratio", 0) or 0) or (
                    getattr(row, "ad_ratio", 0) or 0
                ):
                    ratio_champs.add(str(cid))
        overlap = sorted(ratio_champs & movers)
        self.assertEqual(
            overlap,
            ["KogMaw"],
            "the anti-tank ratio population and the ARENA axis population no "
            "longer intersect in exactly {KogMaw}; re-measure whether "
            "/anti-tank can now be given a response-changes case",
        )
        off = build_champion(snap, "KogMaw", 11, [], mode="ARENA",
                             apply_mode_modifiers=False)
        on = build_champion(snap, "KogMaw", 11, [], mode="ARENA",
                            apply_mode_modifiers=True)
        moved_keys = {
            k for k in set(off.stats) | set(on.stats)
            if off.stats.get(k) != on.stats.get(k)
        }
        self.assertTrue(moved_keys, "KogMaw stopped responding to the addends")
        self.assertNotIn(
            "ap",
            moved_keys,
            "the ARENA addends now move 'ap', so KogMaw's ap_ratio anti-tank "
            "row WOULD move - give /anti-tank a real response-changes case",
        )


class TestClientTransportEmitsTheKey(unittest.TestCase):
    """Gate C proof: the client puts the key ON THE WIRE, and only when ON.

    Captures the POST body each client function would send by stubbing
    ``_post_json``. Then feeds the captured body to the REAL route handler and
    asserts the response changes - so this is a client-to-arithmetic chain, not
    a claim that a kwarg exists on the client signature.
    """

    CLIENT_TO_ROUTE = {
        "rank_for": "_route_rank",
        "rank_tank_for": "_route_rank_tank",
        "rank_bruiser_for": "_route_rank_bruiser",
        "rank_mage_for": "_route_rank_mage",
        "rank_assassin_for": "_route_rank_assassin",
        "rank_enchanter_for": "_route_rank_enchanter",
        "rank_onhit_for": "_route_rank_onhit",
        "ability_dps_for": "_route_ability_dps",
        "burst_for": "_route_burst",
        "hps_for": "_route_hps",
        "dps_for": "_route_dps",
        "ehp_for": "_route_ehp",
        "hybrid_for": "_route_hybrid",
        "matchup": "_route_matchup",
    }

    def _capture(self, fn_name: str, **kwargs) -> dict:
        import core.daemon_slayer_client as dsc

        captured: dict = {}

        def _fake(path, body, timeout=0.0):
            captured["path"] = path
            captured["body"] = body
            return None

        real = dsc._post_json
        dsc._post_json = _fake
        try:
            getattr(dsc, fn_name)(**kwargs)
        finally:
            dsc._post_json = real
        return captured

    # Briar moves 13 of the 14; rank_assassin_for needs Akshan. Both measured
    # 2026-08-06 over the arena-axis population.
    CHAMPION_FOR = {"rank_assassin_for": "Akshan"}
    DEFAULT_CHAMPION = "Briar"

    def _kwargs(self, fn_name: str, on: bool) -> dict:
        import core.daemon_slayer_client as dsc

        champ = self.CHAMPION_FOR.get(fn_name, self.DEFAULT_CHAMPION)
        if fn_name == "matchup":
            kw = {"champ_a": champ, "champ_b": champ, "level_a": 11,
                  "level_b": 11, "mode": "ARENA"}
        else:
            kw = {"champion": champ, "level": 11, "item_ids": [],
                  "mode": "ARENA"}
        # Feed the target resists only where the signature takes them - the
        # effect is input-sensitive and an all-zero target flattens some rankers.
        params = inspect.signature(getattr(dsc, fn_name)).parameters
        for name, val in (("target_armor", 60.0), ("target_mr", 40.0)):
            if name in params:
                kw[name] = val
        if on:
            kw["apply_mode_modifiers"] = True
        return kw

    def test_key_is_absent_by_default_and_true_when_set(self):
        for fn_name in sorted(self.CLIENT_TO_ROUTE):
            with self.subTest(client_fn=fn_name):
                off = self._capture(fn_name, **self._kwargs(fn_name, False))
                self.assertNotIn(
                    FLAG,
                    off["body"],
                    f"{fn_name} emits {FLAG} at the DEFAULT; every existing "
                    "caller would silently change its request",
                )
                on = self._capture(fn_name, **self._kwargs(fn_name, True))
                self.assertIs(
                    on["body"].get(FLAG),
                    True,
                    f"{fn_name} accepts {FLAG} but never puts it on the wire - "
                    "that is the settable-but-inert transport failure",
                )

    def test_the_captured_client_body_changes_the_route_response(self):
        """Close the loop: client body -> real route handler -> different result.

        ALL 14 client functions, not a convenient subset. This is the assertion
        that would have caught the RM-115 failure mode, and the one that caught
        the live /v2/fight-report instance during RM-172: a signature test and a
        body-contains-the-key test both pass on an inert seam; only a changed
        response does not.
        """
        from agents.daemon_slayer import server as ds_server

        ds_server._CACHE.set(_snapshot())
        for fn_name in sorted(self.CLIENT_TO_ROUTE):
            route = self.CLIENT_TO_ROUTE[fn_name]
            with self.subTest(client_fn=fn_name, route=route):
                off = self._capture(fn_name, **self._kwargs(fn_name, False))
                on = self._capture(fn_name, **self._kwargs(fn_name, True))
                handler = getattr(ds_server, route)
                a = json.dumps(handler(off["body"]), sort_keys=True,
                               default=str)
                b = json.dumps(handler(on["body"]), sort_keys=True,
                               default=str)
                self.assertNotEqual(
                    a, b,
                    f"the body {fn_name} sends with {FLAG}=True produces an "
                    f"identical {route} response - the wire carries the key but "
                    "the engine does not act on it",
                )


if __name__ == "__main__":
    unittest.main()
