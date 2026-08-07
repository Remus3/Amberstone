"""RM-119 class B2: the Daemon Slayer live-route skip gates.

WHY THIS FILE EXISTS - read before re-opening B2 a fourth time
==============================================================

B2 was filed as "19 DS live-route sites": tests that skip because the Daemon
Slayer HTTP engine on :8860 is not answering, so the assertion never runs and
the suite reports green while the route may be broken. Re-derived 2026-08-06
(the filed count for both sibling classes was wrong by a large factor, in
opposite directions, so no count in this family is inherited): the true census at ae0c2897, BEFORE this module existed, was
**20 skip control points across 18 modules**, not 19 - see ``_B2_CENSUS``
below, which is machine-checked, not a note.

The verdict, per site, is the SAME, and it is not the verdict B2 assumed:

    Every one of the 20 gates is a LEGITIMATE capability gate (class A).
    None is dead (class C). The masking B2 named is real, but it is not in
    the skip CONDITION - it is in the total absence of any environment that
    ever declares the engine REQUIRED.

The evidence for class A:

  * ``.github/workflows/ci.yml`` never starts the engine. Measured 2026-08-06:
    the only match for `8860` in `.github/workflows/*.yml` is a prose comment
    at ci.yml:403, and no job runs `tools/start_daemon_slayer.py`. CI collects
    `tests/` and `agents/daemon_slayer/tests/` with nothing listening on 8860,
    so deleting these skips makes CI permanently red for an environment
    reason.
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
_TEST_TREES = ("tests", "agents/daemon_slayer/tests",
               "agents/agent3_testing/suite", "tools/tests", "benchmarks")

_DECOR_SKIPS = {"pytest.mark.skipif", "mark.skipif", "skipif",
                "unittest.skipIf", "skipIf",
                "unittest.skipUnless", "skipUnless"}
_BODY_SKIPS = {"pytest.skip", "skip", "skipTest"}

#: A call to the shared gate is itself a control point - otherwise adopting
#: the gate would DELETE sites from the census, which is the one direction a
#: census must never move for free.
_GATE_CALL = "require_live_engine"

#: What a DS-route gate says about ITSELF. Matched against the skip
#: construct's OWN source segment, never a surrounding window - measured
#: 2026-08-06, a +/-12-line window false-positives on
#: `agents/daemon_slayer/tests/test_changelog_tracks_engine_version.py:65`,
#: whose reason is about the CHANGELOG and whose docstring happens to say
#: "daemon_slayer pulls the whole engine in".
#:
#: LIMIT, stated so it is not mistaken for completeness: this recognises the
#: gate SHAPES that exist today. A DS-route gate written with a reason that
#: names neither the port, nor "DS server/engine", nor an engine-liveness
#: helper would not be seen. That is why the census is pinned as a SET below -
#: a new site in a known shape turns this red and has to be classified.
_DS_GATE_HINT = re.compile(
    r"8860"
    r"|DS server"
    r"|DS engine"
    r"|engine (is )?(down|up|unreachable)"
    r"|engine on [^\"']*is not responding"
    r"|_engine_is_up",
    re.I)


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


def scan_ds_route_gates() -> dict[str, int]:
    """{repo-relative module -> number of DS-route skip control points}."""
    found: dict[str, int] = {}
    for tree_name in _TEST_TREES:
        root = _REPO_ROOT / tree_name
        if not root.is_dir():
            continue
        for path in sorted(root.rglob("*.py")):
            src = path.read_text(encoding="utf-8", errors="replace")
            if "8860" not in src and "DS server" not in src \
                    and "DS engine" not in src and "_engine_is_up" not in src \
                    and "require_live_engine" not in src:
                continue
            try:
                tree = ast.parse(src)
            except SyntaxError:  # pragma: no cover - not expected in-tree
                continue
            n = 0
            for node in _skip_nodes(tree):
                if isinstance(node, ast.Call) \
                        and _dotted(node.func) == _GATE_CALL:
                    n += 1  # a gate call is a gate by construction
                    continue
                segment = ast.get_source_segment(src, node) or ""
                if _DS_GATE_HINT.search(segment):
                    n += 1
            if n:
                found[path.relative_to(_REPO_ROOT).as_posix()] = n
    return found


#: The re-derived census AS IT STANDS AFTER this slice. The pre-slice count
#: was 20 control points over 18 modules, measured 2026-08-06 at ae0c2897;
#: every one was hand-read and classified, all 20 came out class A (legitimate
#: capability gate), and zero came out class C - all 34 live paths
#: (31 `_POST_ROUTES` + /health + /snapshot + /modifier-summary) were probed
#: the same day and every one answered. The count below is higher only because
#: this module's own gate calls are counted too.
#:
#: The five `tests/`-tree modules now route through `require_live_engine`
#: above, so `RC_REQUIRE_DS_ENGINE=1` arms them. The thirteen
#: `agents/daemon_slayer/tests/` modules deliberately do NOT: that tree is
#: mirrored verbatim into `Share/src/` by `tools/ds_share_sync.py` and the
#: mirror is a hard CI gate (`ds_share_sync.py --check`, ci.yml:245), and most
#: of those modules are stdlib-only by design so they cannot import a `tests/`
#: helper without breaking the shipped package. They are covered CLASS-WIDE
#: instead, by `test_engine_is_up_when_required` and
#: `test_every_post_route_dispatches_when_required` below - one control point
#: for one class-wide capability, which is the right shape anyway.
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
    # --- agents/daemon_slayer/tests/: Share-mirrored, covered class-wide ---
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
