"""RM-119 class B2: the Daemon Slayer live-route skip gates.

WHY THIS FILE EXISTS - read before re-opening B2 a fourth time
==============================================================

B2 was filed as "19 DS live-route sites": tests that skip because the Daemon
Slayer HTTP engine on :8860 is not answering, so the assertion never runs and
the suite reports green while the route may be broken. Re-derived 2026-08-06
(the filed count for both sibling classes was wrong by a large factor, in
opposite directions, so no count in this family is inherited): the true census at 09d9c7a1, BEFORE this module existed, was
**20 skip control points across 18 modules**, not 19 - see ``_B2_CENSUS``
below, which is machine-checked, not a note.

The verdict, per site, is the SAME, and it is not the verdict B2 assumed:

    Every one of the 20 gates is a LEGITIMATE capability gate (class A).
    None is dead (class C). The masking B2 named is real, but it is not in
    the skip CONDITION - it is in the total absence of any environment that
    ever declares the engine REQUIRED.

The evidence for class A:

  * CI never starts the engine. Measured 2026-08-06, and RE-measured after an
    adversarial pass caught the first statement of it being wrong: a
    case-insensitive grep of the whole `.github/` tree for `8860`, for
    `start_daemon_slayer`, and for any daemon-slayer serve/start/launch verb
    returns NOTHING - the port and the launcher appear in no workflow at all.
    (The first draft of this file cited "one prose comment at ci.yml:403" as
    the single match. That was false: `8860` occurs zero times under
    `.github/`, and ci.yml:403 is a comment about `request_queue_size`. The
    conclusion survived; the cited evidence did not exist, which is worse than
    a wrong conclusion in a file whose purpose is to be trusted instead of
    re-derived.) What CI does run is `pytest tests/
    agents/daemon_slayer/tests/` at ci.yml:125 and ci.yml:407, with nothing
    listening on the port, so deleting these skips makes CI permanently red
    for an environment reason.
  * A fresh clone, and any machine that is not Legion, is in the same
    position. The engine is opt-in infrastructure
    (`core/daemon_slayer_client.py:1-6`, "never load-bearing").

The evidence that a real hole remains anyway:

  * On Legion the engine IS expected up, and these 20 gates are the ONLY
    tests that exercise the :8860 route surface end to end. Nothing in the
    repo ever asserts the engine is up. So a wedged engine - the measured
    failure mode in memory `reference_ds_wedges_with_every_signal_green`,
    where the scheduled task reads Running, the port reads LISTENING and the
    PID is live, and only a real HTTP request finds it - turns all 20 into
    silent skips and the suite still reports green.

So the fix is NOT to convert the skips. Converting a capability skip into an
assertion that cannot fail is strictly worse than the skip: it trades a
visible SKIPPED for a silent green dot. The fix is the opt-in that this repo
has already shipped twice for exactly this shape - `RC_REQUIRE_HOOK_GATE`
(tests/test_drift_guard.py:34) and `RC_REQUIRE_BUILD_ORDER_TABLES`
(tests/test_build_order_precompute.py:36). A third instance, same idiom:

    RC_REQUIRE_DS_ENGINE=1

means "the caller has declared the engine is supposed to be up here". Under
it, `require_live_engine` raises AssertionError instead of SkipTest, and
`test_every_post_route_dispatches_when_required` probes the WHOLE route
surface derived from `server._POST_ROUTES` - so a route that 404s or 500s is
one loud failure rather than 20 quiet skips.

Without the flag, every gate behaves exactly as it did. That is deliberate:
class A stays class A.
"""
from __future__ import annotations

import ast
import json
import os
import re
import unittest
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from core import daemon_slayer_client as dsc

_REPO_ROOT = Path(__file__).resolve().parent.parent

REQUIRE_ENGINE_ENV = "RC_REQUIRE_DS_ENGINE"

_BASE_URL = f"http://{dsc.DEFAULT_HOST}:{dsc.DEFAULT_PORT}"


# --------------------------------------------------------------------------- #
# The gate - SHARED. Imported by the tests/-tree B2 sites; one implementation.
# --------------------------------------------------------------------------- #
def ds_engine_is_required() -> bool:
    """True when the CALLER has declared the :8860 engine must be answering.

    Same parse as `build_order_tables_are_required` so `=0` cannot arm it by
    accident, which is a mistake a plain truthiness check invites.
    """
    return os.environ.get(REQUIRE_ENGINE_ENV, "").strip().lower() not in (
        "", "0", "false", "no", "off",
    )


def require_live_engine(label: str, timeout: float = 2.0,
                        up: bool | None = None,
                        also_required: bool = False) -> None:
    """Skip when the engine is down - unless the caller SAID it is up.

    `up` lets a caller supply its own liveness answer (two B2 sites retry the
    probe with a backoff because collection-time xdist load overflows the
    listen backlog); `also_required` lets a caller declare the engine required
    for a reason of its own, independent of RC_REQUIRE_DS_ENGINE.

    The AssertionError branch must NOT be a `unittest.SkipTest`. `SkipTest`
    subclasses `Exception`, which is how a guard in this repo once caught its
    own skip and reported it as an unrelated import failure
    (tests/test_build_order_variants.py:243-250). The unit tests below assert
    the non-subclass relationship directly rather than trusting the type name.
    """
    engine_up = dsc.is_engine_up(timeout=timeout) if up is None else up
    if engine_up:
        return
    if ds_engine_is_required():
        why = f"{REQUIRE_ENGINE_ENV} is set"
    elif also_required:
        why = "the caller declared the engine required"
    else:
        why = ""
    if why:
        raise AssertionError(
            f"{why}, so the Daemon Slayer engine at "
            f"{_BASE_URL} was supposed to be ANSWERING - but it is not, so "
            f"{label} would have skipped silently. A wedged engine reads as "
            "task-Running + port-LISTENING + live-PID and only an HTTP "
            "request finds it; that is the case this flag exists to catch. "
            "Start it with python tools/start_daemon_slayer.py"
        )
    raise unittest.SkipTest(
        f"{label}: Daemon Slayer engine at {_BASE_URL} is not answering "
        f"(set {REQUIRE_ENGINE_ENV}=1 to make this a failure)"
    )


# --------------------------------------------------------------------------- #
# Route-surface verdict
# --------------------------------------------------------------------------- #
#: A body rich enough that every route in `_POST_ROUTES` dispatches to real
#: work. Measured 2026-08-06 against the live engine (ENGINE 1.275.0, patch
#: 16.15.1): 30 of 31 POST routes answered 200 with this body and `/v2/matchup`
#: answered 400 for its own missing `champ_a`. A 400 still PROVES the route
#: exists and dispatched, which is the only question asked here.
_PROBE_BODY = {
    "champion": "Sion", "level": 11, "item_ids": ["3068"], "mode": "SR",
    "target_armor": 80.0, "target_mr": 60.0, "target_max_hp": 2200.0,
    "enemy_champion": "Garen", "ally_champion": "Sona",
}

ROUTE_ALIVE = "alive"
ROUTE_DEAD = "dead"
ROUTE_BROKEN = "broken"


def classify_route_status(status: int) -> str:
    """404 means the dispatch table lost the route; 5xx means it raised.

    Anything else - including a 400 for a body this probe did not tailor - is
    a route that exists and ran. Split out so it is unit-testable without a
    server, which is what makes the guard below falsifiable off-Legion.
    """
    if status == 404:
        return ROUTE_DEAD
    if status >= 500:
        return ROUTE_BROKEN
    return ROUTE_ALIVE


def _probe_route(path: str, timeout: float = 30.0) -> int:
    req = Request(_BASE_URL + path, data=json.dumps(_PROBE_BODY).encode(),
                  headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urlopen(req, timeout=timeout) as resp:
            resp.read()
            return resp.status
    except HTTPError as e:
        e.read()
        return e.code


# --------------------------------------------------------------------------- #
# The B2 census, machine-derived from the PRODUCING side
# --------------------------------------------------------------------------- #
# Kept in step with the copy in tests/test_skip_condition_hygiene.py by hand -
# this one is a SECOND producing side, and unlike that copy it does not assert
# the directories exist, so it goes stale SILENTLY. "benchmarks" was dropped
# here on 2026-09-06 with the tree itself; that guard failed loudly and this
# census stayed green while naming a dead path.
_TEST_TREES = ("tests", "agents/daemon_slayer/tests",
               "agents/agent3_testing/suite", "tools/tests")

_DECOR_SKIPS = {"pytest.mark.skipif", "mark.skipif", "skipif",
                "unittest.skipIf", "skipIf",
                "unittest.skipUnless", "skipUnless"}
_BODY_SKIPS = {"pytest.skip", "skip", "skipTest"}

#: A call to the shared gate is itself a control point - otherwise adopting
#: the gate would DELETE sites from the census, which is the one direction a
#: census must never move for free.
_GATE_CALL = "require_live_engine"

#: What a DS-route gate says about ITSELF, or what its condition calls.
#: Matched against the skip construct's own source segment plus the nearest
#: enclosing `if`/`while` test - never a surrounding LINE WINDOW. A window
#: pulls in whatever prose happens to sit nearby: a bare `engine` matcher over
#: a +/-12-line window fires on
#: `agents/daemon_slayer/tests/test_changelog_tracks_engine_version.py:65`,
#: whose skip is about the CHANGELOG and whose neighbouring docstring says
#: "daemon_slayer pulls the whole engine in". (An earlier draft of this
#: comment claimed the SHIPPED matcher false-positived there. It does not, and
#: never did - that file fails the prefilter on all six tokens and the hint
#: does not match its reason. The corrected statement is the one above: window
#: matching is rejected on principle and on a demonstrated bare-`engine`
#: false positive, not on a false positive of this regex.)
#:
#: LIMIT, stated so it is not mistaken for completeness: this recognises the
#: gate SHAPES that exist today. A gate whose reason AND whose condition both
#: avoid every token here - say a liveness helper with a novel name, called
#: through a variable - would not be seen. That is why the census is pinned as
#: a SET below: a new site in any known shape turns this red and has to be
#: classified.
_DS_GATE_HINT = re.compile(
    r"8860"
    r"|DS server"
    r"|DS engine"
    r"|live engine"
    r"|engine (is )?(down|up|unreachable|not answering|not responding)"
    r"|engine on [^\"']*is not responding"
    r"|_?is_engine_up"
    r"|_engine_is_up",
    re.I)

#: Cheap per-file prefilter. It MUST be a superset of what the hint can match,
#: or a file is dropped before the hint ever runs. It was not, and that is the
#: sharpest thing an adversarial pass found here: the hint carried
#: `_engine_is_up` (a local helper name in one module) while the real client
#: predicate is `core.daemon_slayer_client.is_engine_up` - different token
#: order, so neither pass matched it. A net-new gate written the most natural
#: way possible,
#:
#:     if not dsc.is_engine_up():
#:         raise unittest.SkipTest("live engine not answering")
#:
#: was invisible to BOTH passes - exactly the net-new B2 this census exists to
#: catch. `test_census_scanner_sees_the_natural_gate_spelling` pins it now.
#:
#: The fix is not a longer token list - a longer list is another chance to miss
#: one, and the first attempt at it did (it carried `is_engine_up` and still
#: dropped `_engine_is_up`). Every alternative in `_DS_GATE_HINT` except `8860`
#: and `DS server` contains the substring `engine`, so these three tokens are a
#: PROVABLE superset, and `test_prefilter_is_a_superset_of_the_hint` checks the
#: property rather than the list. Matched case-insensitively.
_PREFILTER_TOKENS = ("8860", "ds server", "engine")


def _dotted(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = _dotted(node.value)
        return f"{base}.{node.attr}" if base else node.attr
    return ""


def _skip_nodes(tree: ast.AST):
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            name = _dotted(node.func)
            if name == _GATE_CALL:
                yield node
            elif name in _DECOR_SKIPS or name in _BODY_SKIPS \
                    or name.endswith(".skipTest"):
                yield node
        elif isinstance(node, ast.Raise) and node.exc is not None:
            exc = node.exc
            fn = exc.func if isinstance(exc, ast.Call) else exc
            if _dotted(fn).endswith(("SkipTest", "Skipped")):
                yield node


def count_ds_route_gates(src: str) -> int:
    """DS-route skip control points in one module's SOURCE.

    Takes text, not a path, so the guard below can drive it with a synthetic
    module and prove the scanner sees a shape that is not in the tree yet.
    """
    low = src.lower()
    if not any(tok in low for tok in _PREFILTER_TOKENS):
        return 0
    try:
        tree = ast.parse(src)
    except SyntaxError:  # pragma: no cover - not expected in-tree
        return 0
    parent: dict[int, ast.AST] = {}
    for p in ast.walk(tree):
        for child in ast.iter_child_nodes(p):
            parent[id(child)] = p
    n = 0
    for node in _skip_nodes(tree):
        if isinstance(node, ast.Call) and _dotted(node.func) == _GATE_CALL:
            n += 1  # a gate call is a gate by construction
            continue
        # The skip's OWN text, plus the nearest enclosing `if` / `while` test.
        # Reason-only matching reads the site's self-description and misses a
        # gate whose reason is generic while its CONDITION calls the liveness
        # predicate; condition-only matching misses the reverse. Both, and no
        # wider - a +/- line window pulls in unrelated prose.
        parts = [ast.get_source_segment(src, node) or ""]
        cur: ast.AST | None = node
        while cur is not None and not isinstance(
                cur, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef,
                      ast.Module)):
            if isinstance(cur, (ast.If, ast.While)):
                parts.append(ast.get_source_segment(src, cur.test) or "")
                break
            cur = parent.get(id(cur))
        if any(_DS_GATE_HINT.search(p) for p in parts if p):
            n += 1
    return n


def scan_ds_route_gates() -> dict[str, int]:
    """{repo-relative module -> number of DS-route skip control points}."""
    found: dict[str, int] = {}
    for tree_name in _TEST_TREES:
        root = _REPO_ROOT / tree_name
        if not root.is_dir():
            continue
        for path in sorted(root.rglob("*.py")):
            n = count_ds_route_gates(
                path.read_text(encoding="utf-8", errors="replace"))
            if n:
                found[path.relative_to(_REPO_ROOT).as_posix()] = n
    return found


#: The re-derived census AS IT STANDS AFTER this slice. The pre-slice count
#: was 20 control points over 18 modules, measured 2026-08-06 at 09d9c7a1;
#: every one was hand-read and classified, all 20 came out class A (legitimate
#: capability gate), and zero came out class C - all 34 live paths
#: (31 `_POST_ROUTES` + /health + /snapshot + /modifier-summary) were probed
#: the same day and every one answered. The count below is higher only because
#: this module's own gate calls are counted too.
#:
#: SEVEN modules now route through `require_live_engine` above, so
#: `RC_REQUIRE_DS_ENGINE=1` arms them: the five in `tests/`, plus the two
#: RM-115 seam modules in the DS tree. Those two are host-dependent already -
#: they `import core.daemon_slayer_client` at module level - so adopting the
#: gate costs the engine tree nothing it had not already spent. An earlier
#: draft justified leaving all thirteen DS-tree modules alone with
#: "stdlib-only, cannot import a tests/ helper". That is true of ELEVEN of
#: them and was false of these two.
#:
#: The remaining ELEVEN deliberately do not adopt it: THOSE ELEVEN are
#: stdlib-only (checked individually - zero non-stdlib top-level imports
#: each), and importing a `tests/` helper would break that. Note the scope:
#: the ELEVEN are stdlib-only, the TREE is not - 32 of its 438 modules import
#: `core.*` at module scope, so "that tree is stdlib-only" would be false.
#: They are covered CLASS-WIDE instead, by
#: `LiveRouteSurfaceTests` below - one control point for one class-wide
#: capability, which is the right shape anyway.
_B2_CENSUS: dict[str, int] = {
    # --- tests/ tree: armed by RC_REQUIRE_DS_ENGINE ---
    "tests/phase8_smoke/test_sr_draft_profile_engine.py": 1,
    "tests/test_build_order_alias_dedupe_w3.py": 1,
    "tests/test_build_order_variants.py": 1,
    "tests/test_build_orders_family_a_guard.py": 3,
    "tests/test_ds_client_conversion_seam_plumb_w2.py": 1,
    # This module: 1 flag-gate SkipTest + 1 real gate call in setUpClass + 6
    # gate calls inside the falsifiability tests, which gate nothing but are
    # counted anyway rather than special-cased away. A scanner with a
    # carve-out for its own author is the shape that goes quietly blind.
    "tests/test_ds_live_route_gate.py": 8,
    # --- agents/daemon_slayer/tests/: stdlib-only, covered class-wide ---
    "agents/daemon_slayer/tests/test_block_index_overrides.py": 1,
    "agents/daemon_slayer/tests/test_burst_off_axis_rm41.py": 1,
    "agents/daemon_slayer/tests/test_combo_overrides.py": 1,
    "agents/daemon_slayer/tests/test_conditional_block_index_s228.py": 1,
    "agents/daemon_slayer/tests/test_cooldown_inheritance.py": 1,
    "agents/daemon_slayer/tests/test_ehp_family_seams_reach_the_client_rm115.py": 1,
    "agents/daemon_slayer/tests/test_form_index_overrides.py": 1,
    "agents/daemon_slayer/tests/test_lightshield_strike_burst.py": 1,
    "agents/daemon_slayer/tests/test_max_priority_overrides.py": 1,
    "agents/daemon_slayer/tests/test_on_hit_per_aa.py": 1,
    "agents/daemon_slayer/tests/test_rm115_tail_seams_reach_the_client.py": 1,
    "agents/daemon_slayer/tests/test_spellblade_burst.py": 1,
    "agents/daemon_slayer/tests/test_sum_of_blocks.py": 1,
}


# --------------------------------------------------------------------------- #
# Falsifiability: these run everywhere, with no engine and no network
# --------------------------------------------------------------------------- #
class GateBehaviourTests(unittest.TestCase):
    """Prove the gate can FAIL. A guard that cannot is worse than the skip.

    MEASURED while writing this, and worth recording: the first draft used
    ``os.environ.pop(REQUIRE_ENGINE_ENV, None)`` to clean up. That DELETES an
    ambient ``RC_REQUIRE_DS_ENGINE=1`` set by the operator, so the armed run
    of this very module silently disarmed itself mid-suite and reported the
    same "2 skipped" as the unarmed run. A test that erases the flag it is
    testing is the exact failure this whole row is about, one level up.
    """

    def setUp(self) -> None:
        self._saved = os.environ.get(REQUIRE_ENGINE_ENV)
        self.addCleanup(self._restore_env)

    def _restore_env(self) -> None:
        if self._saved is None:
            os.environ.pop(REQUIRE_ENGINE_ENV, None)
        else:
            os.environ[REQUIRE_ENGINE_ENV] = self._saved

    def test_engine_down_and_not_required_skips(self) -> None:
        os.environ[REQUIRE_ENGINE_ENV] = "0"
        with self.assertRaises(unittest.SkipTest):
            require_live_engine("probe", up=False)

    def test_engine_down_and_required_fails(self) -> None:
        os.environ[REQUIRE_ENGINE_ENV] = "1"
        with self.assertRaises(AssertionError) as ctx:
            require_live_engine("probe", up=False)
        # The load-bearing half: a SkipTest here would report GREEN.
        self.assertNotIsInstance(ctx.exception, unittest.SkipTest)
        self.assertIn(REQUIRE_ENGINE_ENV, str(ctx.exception))

    def test_engine_up_passes_either_way(self) -> None:
        os.environ[REQUIRE_ENGINE_ENV] = "1"
        self.assertIsNone(require_live_engine("probe", up=True))
        os.environ[REQUIRE_ENGINE_ENV] = "0"
        self.assertIsNone(require_live_engine("probe", up=True))
        self.assertIsNone(
            require_live_engine("probe", up=True, also_required=True))

    def test_also_required_arms_without_the_env_flag(self) -> None:
        os.environ[REQUIRE_ENGINE_ENV] = "0"
        with self.assertRaises(AssertionError) as ctx:
            require_live_engine("caller-declared", up=False,
                                also_required=True)
        # The message must not blame a flag that is NOT set - a wrong pointer
        # sends whoever hits this to the wrong knob.
        self.assertNotIn(REQUIRE_ENGINE_ENV, str(ctx.exception).split(",")[0])
        self.assertIn("caller declared", str(ctx.exception))

    def test_env_parse_does_not_arm_on_falsey_spellings(self) -> None:
        for raw in ("", "0", "false", "no", "off", " OFF "):
            with self.subTest(raw=raw):
                os.environ[REQUIRE_ENGINE_ENV] = raw
                self.assertFalse(ds_engine_is_required())

    def test_env_parse_arms_on_truthy_spellings(self) -> None:
        for raw in ("1", "true", "yes", "on"):
            with self.subTest(raw=raw):
                os.environ[REQUIRE_ENGINE_ENV] = raw
                self.assertTrue(ds_engine_is_required())

    def test_route_status_classifier(self) -> None:
        self.assertEqual(classify_route_status(404), ROUTE_DEAD)
        self.assertEqual(classify_route_status(500), ROUTE_BROKEN)
        self.assertEqual(classify_route_status(503), ROUTE_BROKEN)
        self.assertEqual(classify_route_status(200), ROUTE_ALIVE)
        self.assertEqual(classify_route_status(400), ROUTE_ALIVE)


class B2CensusTests(unittest.TestCase):
    """A NEW DS-route skip gate must be classified, not silently added."""

    def test_census_matches_the_tree(self) -> None:
        found = scan_ds_route_gates()
        self.assertEqual(
            found, _B2_CENSUS,
            "the DS live-route skip census moved. Every entry here was "
            "hand-classified under RM-119 B2 (all class A - a legitimate "
            "capability gate; see this module's docstring). A new site is "
            "not automatically class A: read it, decide whether the engine "
            "is genuinely optional where that test runs, route it through "
            "require_live_engine if it lives in tests/, then update "
            "_B2_CENSUS.",
        )

    def test_census_scanner_sees_the_natural_gate_spelling(self) -> None:
        """The evasion an adversarial pass found: `dsc.is_engine_up`.

        The hint once carried only `_engine_is_up` - a local helper name in
        one module - while the real client predicate is `is_engine_up`.
        Different token order, so this shape failed the prefilter AND the
        hint and was invisible on both passes. It is the most natural way to
        write a net-new B2 site, which made it the worst possible blind spot.
        """
        natural = (
            "import unittest\n"
            "from core import daemon_slayer_client as dsc\n"
            "class T(unittest.TestCase):\n"
            "    def setUp(self):\n"
            "        if not dsc.is_engine_up():\n"
            "            raise unittest.SkipTest('skipping')\n"
        )
        self.assertEqual(count_ds_route_gates(natural), 1,
                         "a gate on dsc.is_engine_up() with a generic reason "
                         "is invisible to the census scanner")

    def test_census_scanner_ignores_an_unrelated_skip(self) -> None:
        """The other half: it must not count everything that says 'engine'."""
        unrelated = (
            "import unittest\n"
            "# the engine package is imported wholesale here\n"
            "@unittest.skipIf(True, 'does not vendor the engine CHANGELOG')\n"
            "class T(unittest.TestCase):\n"
            "    pass\n"
        )
        self.assertEqual(count_ds_route_gates(unrelated), 0)

    def test_prefilter_is_a_superset_of_the_hint(self) -> None:
        """A file dropped by the prefilter never reaches the hint at all.

        This is the invariant whose violation created the blind spot above.
        Every alternative the hint can match must contain a prefilter token,
        or be unreachable by construction.
        """
        for probe in ("8860", "DS server", "DS engine", "live engine",
                      "engine is down", "engine up", "engine unreachable",
                      "engine not answering", "engine not responding",
                      "is_engine_up", "_engine_is_up",
                      "dsc.is_engine_up()"):
            with self.subTest(probe=probe):
                self.assertTrue(_DS_GATE_HINT.search(probe),
                                f"{probe} should match the hint")
                self.assertTrue(
                    any(tok in probe.lower() for tok in _PREFILTER_TOKENS),
                    f"{probe} matches the hint but no prefilter token - the "
                    "prefilter would drop the file before the hint ran",
                )

    def test_every_census_module_exists(self) -> None:
        for rel in _B2_CENSUS:
            self.assertTrue((_REPO_ROOT / rel).is_file(), f"missing {rel}")


# --------------------------------------------------------------------------- #
# The class-wide live gate. Skips unless the caller armed RC_REQUIRE_DS_ENGINE.
# --------------------------------------------------------------------------- #
class LiveRouteSurfaceTests(unittest.TestCase):
    """The single control point that covers all 20 B2 sites at once.

    Skipped - not failed - when the flag is unset, because that is the class-A
    verdict this module argues for. Under the flag it is the loudest test in
    the repo about a wedged or route-lossy engine.
    """

    @classmethod
    def setUpClass(cls) -> None:
        if not ds_engine_is_required():
            raise unittest.SkipTest(
                f"{REQUIRE_ENGINE_ENV} not set - the :8860 engine is opt-in "
                "infrastructure and is legitimately absent in CI and in a "
                "fresh clone (RM-119 B2 class A). Set it to 1 on a host "
                "where the engine is supposed to be up."
            )
        # Armed. From here a down engine is an AssertionError, not a skip -
        # that is the whole point of the flag.
        require_live_engine("the DS live-route surface")

    def test_every_post_route_dispatches_when_required(self) -> None:
        from agents.daemon_slayer import server

        verdicts: dict[str, tuple[str, int]] = {}
        for path in sorted(server._POST_ROUTES):
            status = _probe_route(path)
            verdicts[path] = (classify_route_status(status), status)
        bad = {p: v for p, v in verdicts.items() if v[0] != ROUTE_ALIVE}
        self.assertEqual(
            bad, {},
            f"routes in server._POST_ROUTES that did not dispatch: {bad}. "
            f"A '{ROUTE_DEAD}' verdict means the live engine no longer serves "
            "a path its own dispatch table lists (a stale process, or a route "
            f"removed without a restart); '{ROUTE_BROKEN}' means the handler "
            "raised. Either way the tests gated on this surface would have "
            "SKIPPED, which is the RM-119 B2 hole.",
        )

    def test_health_reports_the_engine_version_the_tree_declares(self) -> None:
        from agents.daemon_slayer import ENGINE_VERSION

        with urlopen(f"{_BASE_URL}/health", timeout=10) as resp:
            payload = json.loads(resp.read())
        self.assertEqual(payload.get("status"), "ok")
        self.assertEqual(
            payload.get("engine_version"), ENGINE_VERSION,
            "the live engine is serving a different ENGINE_VERSION than this "
            "checkout declares - every live-route test below is measuring a "
            "stale process. Restart it: python tools/start_daemon_slayer.py",
        )


if __name__ == "__main__":
    unittest.main()
