"""RM-172 characterization: the ``apply_mode_modifiers`` seam, pinned END TO END.

RM-169 pinned ONE path (``matchup.compute_matchup``). This file pins the whole
seam, so a PARTIAL wiring cannot land silently. MEASURED 2026-08-06 at
ENGINE 1.275.0 / patch 16.15.1.

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
is an engine-output change and would need an ENGINE_VERSION bump plus the Share
mirror, which is why RM-172 does NOT change it.

COST OF THE CURRENT STATE (measured, see the module docstring assertions below).
No production caller anywhere in the repo sets the flag True - the only non-test
occurrences of ``apply_mode_modifiers=True`` are docstrings. So every shipped
ARENA number today, including the generated ARENA build-order tables, is
computed from the SR stat line for those 45 champions.

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
}

# GATE B - HTTP routes that PARSE the flag out of the POST body.
EXPECTED_GATE_B = {
    "_route_beam",
    "_route_dps",
    "_route_ehp",
    "_route_fight_report",
    "_route_hybrid",
    "_route_rank",
    "_route_rank_bruiser",
    "_route_rank_tank",
}

# GATE C - core/daemon_slayer_client.py transport functions carrying the flag.
EXPECTED_GATE_C = {
    "dps_for",
    "ehp_for",
    "hybrid_for",
    "rank_bruiser_for",
    "rank_for",
    "rank_tank_for",
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
    src = (REPO_ROOT / "agents/daemon_slayer/server.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    out: dict[str, bool] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name.startswith("_route_"):
            out[node.name] = FLAG in (ast.get_source_segment(src, node) or "")
    return out


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

    def test_seam_is_currently_INCOHERENT_by_construction(self):
        """The row's whole premise: the seam is wired unevenly TODAY.

        This is a characterization, not an endorsement. If someone wires the
        seam uniformly, this test SHOULD fail and be deleted along with the
        RM-172 note in agents/daemon_slayer/matchup.py.
        """
        routes = _route_defs()
        parsing = {n for n, v in routes.items() if v}
        self.assertLess(
            len(parsing),
            len(routes),
            "expected SOME routes to be mode-modifier-blind",
        )
        # The pure stat-block route cannot ask for the corrected ARENA line at
        # all, even though build_champion is the function that would apply it.
        self.assertIn("_route_stats", routes)
        self.assertFalse(
            routes["_route_stats"],
            "/stats is the direct build_champion route; it not parsing the "
            "flag is the sharpest single instance of the incoherence",
        )
        # Four archetype rankers accept the kwarg downstream via rank.rank_items
        # / ehp.rank_items_by_ehp but expose no way to set it.
        for blind in ("_route_rank_mage", "_route_rank_assassin",
                      "_route_rank_enchanter", "_route_rank_onhit"):
            self.assertIn(blind, routes)
            self.assertFalse(routes[blind], f"{blind} unexpectedly parses {FLAG}")

    def test_no_production_caller_sets_the_flag_true(self):
        """Every shipped ARENA number is computed with the flag OFF.

        Only docstrings mention the True form outside tests. If a production
        caller ever sets it, the generated ARENA build-order / laning tables
        must be regenerated in the same change or the tables and the live
        engine will disagree.
        """
        needle = f"{FLAG}=True"
        offenders: list[str] = []
        skip_parts = ("tests", "test_", "docs", "_archive", "Share")
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
        bump and the Share mirror on the same commit.
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


if __name__ == "__main__":
    unittest.main()
