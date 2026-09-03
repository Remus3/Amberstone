"""RM-330 option B: the roster-key id-only contract is written on every route.

THE ROW, AND WHY THIS IS NOT A BUG FIX
--------------------------------------
The DS HTTP surface resolves ``champion`` through the tolerant
``_resolve_champion_id`` (server.py:398), but the ROSTER keys - ``enemies``,
``ally_grant_champions``, ``granter_resists`` - take exact canonical DDragon
ids, so a Riot DISPLAY name silently contributes nothing. Probed live on the
filed row: ``enemies=["Chogath"]`` moves the number, ``["Cho'Gath"]`` returns
the no-enemy identity; likewise ``MonkeyKing`` against ``Wukong``.

RM-330 is DECIDE-THEN-ACT and the decision is OPTION B: keep the id-only
contract, propagate the sentence that documents it, and guard it. Option A - a
canonical-id resolver folded over the roster keys - was NOT taken, and this file
exists partly so that a later pass does not quietly take it because it "looks
like a bug fix". Two independent checks say the silent skip is intended:

  1. The contract is already WRITTEN DOWN, in
     ``dashboard/routes_cc_blended_ehp_threat.py``, and it names this row's own
     example: "comma-separated canonical DDragon ids (\"Annie\", \"Garen\",
     \"MonkeyKing\")" whose "unknown champions are silently skipped (mirrors
     compute_ehp's fail-soft contract on enemy_champions and
     compute_cc_pressure)". Pinned in ``UpstreamContractTests`` - if that
     sentence moves, everything this slice propagated is orphaned.
  2. TWO client-side canonicalizers already exist for exactly this bridge -
     ``core/archetype_picks.canonical_champion_id`` (:400), written to bridge
     Live Client display names to the engine's canonical-id registries, and
     ``core/daemon_slayer_client._canon_champ_key`` (RM-95, :2103). Option A
     would make a THIRD normalizer.

The live-defect claim was refuted twice on the row and is not re-filed here.

WHAT THIS FILE ASSERTS
----------------------
The row's acceptance for (B), both halves:

  (a) every roster-key parse site carries the id-only sentence in its ROUTE
      docstring, and
  (b) an unknown roster name is SKIPPED rather than raising.

THE PARSE SITES ARE DERIVED, NEVER LISTED
-----------------------------------------
``_parse_sites`` walks the ``server.py`` AST for every ``_route_*`` handler and
records which roster keys it reads off ``body``. A hand-written roster is the
failure this repo has paid for repeatedly: it can silently go stale, and worse,
it can silently go EMPTY, at which point every assertion keyed off it passes by
iterating nothing. ``test_derived_site_map_is_not_empty`` and
``test_the_derivation_can_go_red`` exist so that neither can happen quietly.

Note the derivation must see TWO parse spellings, not one:
``_coerce_str_list(body.get("enemies"), ...)`` and the bare
``body.get("granter_resists")`` - which is a dict, not a champion list, and is
keyed BY champion name. A walk that only understood ``_coerce_str_list`` would
miss the third key entirely and still look healthy.

A MEASURED CORRECTION: THE ECHO IS NOT CONFIRMATION
---------------------------------------------------
Naive byte-identity between "bogus name" and "key omitted" holds on /ehp,
/rank-tank, /rank-bruiser and /ally-protected-ehp - and FAILS on /hybrid. It is
not a fail-soft breach. MEASURED: the sole differing field is
``enemy_champions``, which /hybrid ECHOES back verbatim as ``['ZzNotAChampion']``
against ``[]``. The arithmetic is untouched.

That is worth pinning rather than working around, because the echo is precisely
the thing that makes this contract easy to get wrong from the outside: a caller
who sends a display name gets it REFLECTED IN THE RESPONSE and can read that as
confirmation the engine understood it. It did not. ``EchoIsNotConfirmationTests``
holds that line.

OFFLINE ONLY: no live :8860, no sockets. Direct handler calls plus AST.
"""
from __future__ import annotations

import ast
import json
import pathlib
import unittest

from agents.daemon_slayer import server
from agents.daemon_slayer.data_loader import DataSnapshot

# The roster keys, straight off the filed row. This is the DEFINITION of the
# contract's scope - a name set, not a site list. WHERE each is parsed is
# derived below and must never be written down here.
_ROSTER_KEYS = ("enemies", "ally_grant_champions", "granter_resists")

# The two anchors of the propagated sentence. Checked separately so that a
# docstring carrying only half of it - the id half without the skip half, which
# is the half a caller actually needs - fails loudly.
_ANCHOR_IDS = "canonical DDragon ids"
_ANCHOR_SKIP = "silently skipped"

_BOGUS = "ZzNotAChampion"

_SERVER_PY = pathlib.Path(server.__file__)
_SERVER_SRC = _SERVER_PY.read_text(encoding="utf-8")

_UPSTREAM_CONTRACT = (
    pathlib.Path(server.__file__).parents[2]
    / "dashboard" / "routes_cc_blended_ehp_threat.py"
)

_BODY_READERS = ("_opt_bool", "_opt_float", "_opt_int", "_opt_str",
                 "_coerce_str_list", "_required_str", "get")

_SNAP = None


def _snap() -> DataSnapshot:
    global _SNAP
    if _SNAP is None:
        _SNAP = DataSnapshot.load()
    return _SNAP


def _wire(payload) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def _body_keys_of(fn: ast.FunctionDef) -> set[str]:
    """Every body key one handler reads, measured off the AST.

    Covers both parse spellings: the ``_coerce_str_list(body.get("k"), "k")``
    form and the bare ``body.get("k")`` form that ``granter_resists`` uses.
    """
    keys: set[str] = set()
    for node in ast.walk(fn):
        if isinstance(node, ast.Call):
            name = getattr(node.func, "id", None) or getattr(node.func, "attr", None)
            if name in _BODY_READERS:
                keys |= {
                    a.value for a in node.args
                    if isinstance(a, ast.Constant) and isinstance(a.value, str)
                }
    return keys


def _parse_sites(src: str = _SERVER_SRC) -> dict[str, frozenset[str]]:
    """handler name -> the roster keys it parses. DERIVED, never listed."""
    tree = ast.parse(src)
    sites: dict[str, frozenset[str]] = {}
    for fn in ast.walk(tree):
        if not isinstance(fn, ast.FunctionDef) or not fn.name.startswith("_route_"):
            continue
        hit = frozenset(k for k in _ROSTER_KEYS if k in _body_keys_of(fn))
        if hit:
            sites[fn.name] = hit
    return sites


def _docstring_of(handler: str, src: str = _SERVER_SRC) -> str:
    fn = next(
        f for f in ast.walk(ast.parse(src))
        if isinstance(f, ast.FunctionDef) and f.name == handler
    )
    return ast.get_docstring(fn) or ""


def _route_paths(src: str = _SERVER_SRC) -> dict[str, str]:
    """handler name -> "/path", read out of the _POST_ROUTES dispatch table."""
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        if not any(
            isinstance(t, ast.Name) and t.id == "_POST_ROUTES" for t in node.targets
        ):
            continue
        if not isinstance(node.value, ast.Dict):
            continue
        return {
            v.id: k.value
            for k, v in zip(node.value.keys, node.value.values)
            if isinstance(k, ast.Constant) and isinstance(v, ast.Name)
        }
    return {}


# Probe bodies, one per handler shape. The HANDLERS are derived; only the
# minimum valid body per handler is written, and a derived handler with no body
# here fails loudly in _probe_body rather than being skipped.
_BASE = {
    "champion": "Braum", "level": 13,
    "items": ["3068", "3075", "3143", "3111"],
    "mode": "SR", "enemy_ad_share": 0.5, "enemy_ap_share": 0.5,
}
_ALLY = {
    "champion": "Braum", "level": 13,
    "item_ids": ["3068", "3075"], "mode": "SR",
}
_PROBE_BODIES = {
    "_route_ehp": _BASE,
    "_route_rank_tank": _BASE,
    "_route_hybrid": _BASE,
    "_route_rank_bruiser": _BASE,
    "_route_ally_protected_ehp": _ALLY,
}

# A roster key that is a dict keyed BY champion, not a list of champions.
_DICT_SHAPED = {"granter_resists"}


def _probe_body(handler: str) -> dict:
    body = _PROBE_BODIES.get(handler)
    if body is None:
        raise AssertionError(
            f"{handler} parses a roster key but this file has no probe body for "
            "it. A NEW roster-key route appeared - give it a body here and let "
            "the fail-soft assertions run against it. Do not delete it from the "
            "derivation to make this pass."
        )
    return dict(body)


def _bogus_value(key: str, handler: str) -> object:
    if key in _DICT_SHAPED:
        return {_BOGUS: [10.0, 10.0, 10.0, 10.0]}
    return [_BOGUS]


def _armed_extra(key: str) -> dict:
    """granter_resists is inert without a granter roster, so arm that too."""
    if key == "granter_resists":
        return {"ally_grant_champions": ["Janna"]}
    return {}


class _Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        server._CACHE.set(_snap())


class DerivationTests(unittest.TestCase):
    """The derivation itself, before anything is keyed off it."""

    def test_derived_site_map_is_not_empty(self) -> None:
        sites = _parse_sites()
        self.assertTrue(
            sites,
            "the derived roster-key parse-site map is EMPTY - the AST walk "
            "broke and every assertion in this file passes by iterating "
            "nothing",
        )

    def test_every_roster_key_is_found_at_a_real_site(self) -> None:
        """Both parse spellings must be visible, including the dict-shaped key."""
        covered = set().union(*_parse_sites().values())
        for key in _ROSTER_KEYS:
            with self.subTest(key=key):
                self.assertIn(
                    key, covered,
                    f"{key!r} is parsed nowhere the walk can see. If it really "
                    "left server.py, drop it from _ROSTER_KEYS deliberately; if "
                    "it only changed parse spelling, _BODY_READERS needs it",
                )

    def test_every_derived_handler_is_a_live_route(self) -> None:
        paths = _route_paths()
        self.assertTrue(paths, "the _POST_ROUTES table did not parse")
        for handler in _parse_sites():
            with self.subTest(handler=handler):
                self.assertIn(
                    handler, paths,
                    "a roster-key handler that no path dispatches to - either "
                    "dead code, or the dispatch table moved",
                )

    def test_the_derivation_can_go_red(self) -> None:
        """Non-vacuity. A walk that can never shrink is not measuring anything."""
        stripped = _SERVER_SRC.replace(
            '_coerce_str_list(body.get("enemies"), "enemies")', "[]"
        )
        before = set().union(*_parse_sites().values())
        after = _parse_sites(stripped)
        after_keys = set().union(*after.values()) if after else set()
        self.assertIn("enemies", before)
        self.assertNotIn(
            "enemies", after_keys,
            "removing every 'enemies' parse from the source left the "
            "derivation unchanged - it is not reading the source",
        )


class DocstringContractTests(unittest.TestCase):
    """ACCEPTANCE (a): every roster-key parse site documents the id-only rule."""

    def test_every_parse_site_carries_both_anchors(self) -> None:
        sites = _parse_sites()
        self.assertTrue(sites)
        paths = _route_paths()
        for handler, keys in sorted(sites.items()):
            doc = _docstring_of(handler)
            with self.subTest(route=paths.get(handler, handler)):
                self.assertTrue(
                    doc, f"{handler} has no docstring to carry the contract"
                )
                self.assertIn(
                    _ANCHOR_IDS, doc,
                    f"{handler} parses {sorted(keys)} but never says the values "
                    "must be canonical DDragon ids - a caller sending a Riot "
                    "display name has no way to learn it contributed nothing",
                )
                self.assertIn(
                    _ANCHOR_SKIP, doc,
                    f"{handler} names the id contract but not its consequence. "
                    "The skip half is the half that bites: the request "
                    "SUCCEEDS and the champion vanishes",
                )

    def test_the_anchors_are_not_repo_wide_noise(self) -> None:
        """A guard that passes because the words are everywhere proves nothing."""
        non_roster = [
            f.name for f in ast.walk(ast.parse(_SERVER_SRC))
            if isinstance(f, ast.FunctionDef)
            and f.name.startswith("_route_")
            and f.name not in _parse_sites()
        ]
        self.assertTrue(non_roster, "no non-roster routes left to contrast with")
        self.assertTrue(
            any(_ANCHOR_IDS not in _docstring_of(h) for h in non_roster),
            "every route in server.py carries the id anchor, roster key or not "
            "- this guard can no longer distinguish documented from "
            "undocumented and must be re-derived",
        )


class FailSoftTests(_Base):
    """ACCEPTANCE (b): an unknown roster name is SKIPPED, never raised."""

    def test_unknown_roster_name_does_not_raise(self) -> None:
        for handler, keys in sorted(_parse_sites().items()):
            for key in sorted(keys):
                with self.subTest(handler=handler, key=key):
                    body = _probe_body(handler)
                    body.update(_armed_extra(key))
                    body[key] = _bogus_value(key, handler)
                    try:
                        getattr(server, handler)(body)
                    except Exception as exc:  # noqa: BLE001 - that IS the assertion
                        self.fail(
                            f"{handler} raised {type(exc).__name__} on an "
                            f"unknown {key!r}. The documented contract is "
                            "fail-soft: unknown names are silently skipped"
                        )

    def test_unknown_name_is_arithmetically_inert(self) -> None:
        """Skipped means skipped - identical to omitting the key entirely.

        Request-ECHO fields are excluded and separately pinned; see
        EchoIsNotConfirmationTests. The exclusion is derived from the value
        (a verbatim echo of what was sent), not from a key allowlist.
        """
        for handler, keys in sorted(_parse_sites().items()):
            for key in sorted(keys):
                with self.subTest(handler=handler, key=key):
                    base = _probe_body(handler)
                    base.update(_armed_extra(key))
                    sent = _bogus_value(key, handler)
                    got = getattr(server, handler)(dict(base, **{key: sent}))
                    omitted = getattr(server, handler)(dict(base))
                    echoes = {k for k, v in got.items() if v == sent}
                    self.assertEqual(
                        _wire({k: v for k, v in got.items() if k not in echoes}),
                        _wire({k: v for k, v in omitted.items()
                               if k not in echoes}),
                        f"{handler} computed a DIFFERENT answer for an unknown "
                        f"{key!r} than for no {key!r} at all - the value was "
                        "partially honoured, which is neither resolution nor a "
                        "clean skip",
                    )

    def test_the_champion_key_still_raises_and_that_is_the_asymmetry(self) -> None:
        """The contrast that makes the fail-soft assertions non-vacuous.

        Without this, "nothing raised" would be equally consistent with a
        server that never raises on anything. ``champion`` goes through
        ``_resolve_champion_id`` and 404s; the roster keys deliberately do not.
        """
        with self.assertRaises(server._ApiError):
            server._route_ehp(dict(_BASE, champion=_BOGUS))

    def test_a_known_roster_name_actually_moves_the_number(self) -> None:
        """Proves the roster transport is live, so 'inert' above means skipped.

        If the roster key were ignored wholesale, every assertion above would
        pass and the contract would be documenting a dead parameter.
        """
        with_enemy = server._route_ehp(dict(_BASE, enemies=["Leona"]))
        without = server._route_ehp(dict(_BASE))
        self.assertNotEqual(
            with_enemy["cc_blended_ehp"], without["cc_blended_ehp"],
            "a KNOWN canonical id changed nothing either - the enemies "
            "transport is dead and the id-only contract is moot",
        )


class EchoIsNotConfirmationTests(_Base):
    """MEASURED: /hybrid reflects the unresolved name back to the caller.

    Pinned because it is the trap the written contract exists to defuse - the
    response contains the display name the caller sent, which reads as
    acknowledgement and is not.
    """

    def test_hybrid_echoes_the_unresolved_name_verbatim(self) -> None:
        got = server._route_hybrid(dict(_BASE, enemies=[_BOGUS]))
        self.assertEqual(
            got.get("enemy_champions"), [_BOGUS],
            "/hybrid stopped echoing enemy_champions - if it now RESOLVES the "
            "roster instead, RM-330 option A shipped and this whole file needs "
            "re-deriving against it",
        )

    def test_the_echo_carries_no_arithmetic(self) -> None:
        echoed = server._route_hybrid(dict(_BASE, enemies=[_BOGUS]))
        omitted = server._route_hybrid(dict(_BASE))
        self.assertNotEqual(echoed["enemy_champions"], omitted["enemy_champions"])
        for field in ("hybrid_score", "dps", "ehp"):
            with self.subTest(field=field):
                self.assertEqual(echoed[field], omitted[field])


class UpstreamContractTests(unittest.TestCase):
    """The sentence this slice propagated must still exist where it came from."""

    def test_the_source_contract_is_still_written_down(self) -> None:
        self.assertTrue(
            _UPSTREAM_CONTRACT.exists(),
            f"{_UPSTREAM_CONTRACT} is gone - the propagated sentence is now "
            "orphaned and RM-330's evidence for option B needs re-checking",
        )
        src = _UPSTREAM_CONTRACT.read_text(encoding="utf-8")
        self.assertIn(_ANCHOR_IDS, src)
        self.assertIn(_ANCHOR_SKIP, src)

    def test_option_a_was_not_quietly_taken(self) -> None:
        """The scope pin. A resolver over the roster keys is a THIRD normalizer.

        RM-330 is DECIDE-THEN-ACT and the decision was B. If a later pass folds
        ``_resolve_champion_id`` over a roster key, this fails and forces the
        decision to be re-made in the open rather than inherited.
        """
        for handler in _parse_sites():
            fn = next(
                f for f in ast.walk(ast.parse(_SERVER_SRC))
                if isinstance(f, ast.FunctionDef) and f.name == handler
            )
            calls = [
                n for n in ast.walk(fn)
                if isinstance(n, ast.Call)
                and getattr(n.func, "id", None) == "_resolve_champion_id"
            ]
            with self.subTest(handler=handler):
                self.assertLessEqual(
                    len(calls), 1,
                    "more than one _resolve_champion_id call in a roster-key "
                    "route - the second is almost certainly folded over a "
                    "roster key, which is RM-330 option A",
                )


if __name__ == "__main__":
    unittest.main()
