"""RM-118 mana lane: the MANA -> DAMAGE coupling pair reaches its ROUTE.

THE DEFECT
----------
The engine half of RM-118 shipped complete - registry
(``_mana_damage_coupling``), consumer (``ehp._mana_key``) and guards - while
``server.py`` parsed neither ``apply_mana_damage_coupling`` nor
``mana_coupling_strength``, and ``core/daemon_slayer_client.py`` could express
neither. The seam was settable from Python, guard-green, and unreachable over
HTTP: the exact stranded-seam class RM-118 exists to retire, and it was parked
in ``test_stranded_hsp_seam_r197.STRANDED_TODAY`` rather than fixed.

BOTH shipped siblings are route-exposed - ``apply_resist_damage_coupling`` /
``resist_coupling_strength`` (RM-87) and ``apply_health_damage_coupling`` /
``health_coupling_strength`` (RM-91 T1) - so the mana pair was the odd one out
of a three-lever family, not a deliberate scoping decision.

WHAT THIS SLICE ADDS - TRANSPORT ONLY
-------------------------------------
``_route_rank_tank`` parses the pair with the HEALTH pair's exact shape
(``_opt_bool`` default False, ``_opt_float`` default 0.0, a ``< 0.0`` ->
``_ApiError(400)`` guard) and forwards both to ``rank_items_by_ehp``.
``core.daemon_slayer_client.rank_tank_for`` gains the pair as
``Optional[bool] = None`` / ``Optional[float] = None``, appended at END per the
no-mid-signature-insert convention, emitted only when not-None so a flagless
call stays byte-identical on the wire. No engine math changed in this slice.

ROUTE OWNERSHIP, MEASURED - NOT INHERITED FROM PROSE
----------------------------------------------------
``reference_ds_route_seam_transport_vs_flag``: a seam has THREE gates - the
flag, the TRANSPORT, and the owner - and a docstring's claim about any of them
is not evidence. Every route-set claim below is DERIVED, at test time:

  * the OWNER set, by ``inspect.signature`` over every module in the package
    (``rank_items_by_ehp`` and nothing else, for the mana pair AND for the
    health pair it mirrors),
  * the ROUTE set, by AST over ``server.py`` - the ``_POST_ROUTES`` dispatch
    table joined to the body keys each ``_route_*`` handler actually reads.

The mana pair must land on EXACTLY the health pair's route set (``/rank-tank``)
and nowhere else. ``compute_ehp`` does not name either pair, so ``/ehp`` must
NOT grow the keys - asserted against rather than left to convention.

THE TRANSPORT IS THE PAIR ITSELF
--------------------------------
Unlike the rune lanes (keyed by perk id, inert without a ``rune_ids`` roster)
this seam needs no third body key: the math reads ``champion_id`` - already on
every ``/rank-tank`` body - and the candidate's own ``delta_max_mp``
(ehp.py:3966-3968). So the "armed transport, flags OFF" control here is the
MAGNITUDE half sent alone: a body carrying ``mana_coupling_strength`` with the
gate absent must be byte-identical.

REACHABILITY IS PROVED, NOT GREPPED
-----------------------------------
Three independent proofs, none of which a presence grep would satisfy:

  1. a SPY on ``server.rank_items_by_ehp`` captures the kwargs the handler
     actually passed, so the value is shown crossing the seam;
  2. the route's RANKING ORDER moves between an armed and an unarmed request
     over the full 138-row pool (``top=200``, no truncation);
  3. the armed response populates ``delta_max_mp`` on the mana rows, which the
     unarmed response leaves at 0.0 - the engine-side evidence the credit ran.

PROBE HYGIENE (all measured traps, see the DS probe memories)
-------------------------------------------------------------
* the HTTP body key is ``items``, never ``item_ids`` (silently dropped),
* ``/rank`` is the CARRY scorer and ignores archetype kwargs - this seam is
  ``/rank-tank`` only,
* ``top`` is a TRUNCATION, so presence/absence claims use ``top=200``,
* never an empty build - two real early-tank items,
* ``mode="SR"`` (production default; ``"CLASSIC"`` is not a mode key).

OFFLINE ONLY: direct handler + client calls. No live :8860, no network.
"""
from __future__ import annotations

import ast
import importlib
import inspect
import pathlib
import pkgutil
import unittest
from unittest import mock

import agents.daemon_slayer as ds_pkg
import core.daemon_slayer_client as client_mod
from agents.daemon_slayer import server
from agents.daemon_slayer.data_loader import DataSnapshot
from agents.daemon_slayer.ehp import compute_ehp, rank_items_by_ehp
from agents.daemon_slayer.tests.test_route_seams_reach_the_client_per_route import (
    _client_by_route,
    _route_table,
)
from agents.daemon_slayer.tests.test_stranded_hsp_seam_r197 import (
    STRANDED_TODAY,
    stranded_seams,
)

_FLAG = "apply_mana_damage_coupling"
_MAGNITUDE = "mana_coupling_strength"
_HEALTH_FLAG = "apply_health_damage_coupling"
_HEALTH_MAGNITUDE = "health_coupling_strength"

_ROUTE = "/rank-tank"
_CLIENT_FN = "rank_tank_for"

# The ONE seeded champion (Blitzcrank R "Static Field", 2 percent of MAXIMUM
# mana as magic damage) and the unseeded control. Malphite is seeded in the
# RM-87 RESIST registry and NOT here, which is exactly the cross-arming the
# separate-flag decision exists to prevent.
_SEEDED = "Blitzcrank"
_UNSEEDED = "Malphite"

_LEVEL = 13
# Probe hygiene: never an empty build (reference_ds_probe_empty_build_artifact).
_BUILD = ("3068", "3047")     # Sunfire Aegis + Plated Steelcaps
# ``top`` truncates AFTER the sort, so any presence/absence claim needs a cut
# above the pool size (138 rows measured at 16.15.1 on this build).
_TOP = 200

_FROZEN_HEART = "3110"        # +400 mana - the measured mover
_WINTERS_APPROACH = "3119"    # +500 mana - the largest mana grant in the pool
_THORNMAIL = "3075"           # ZERO mana - the no-credit control

# Measured floor for a visible reorder at this build; the engine-side sibling
# test pins the same magnitude.
_STRENGTH = 8.0

_SNAP = None


def _snap() -> DataSnapshot:
    global _SNAP
    if _SNAP is None:
        _SNAP = DataSnapshot.load()
    return _SNAP


def _body(champion: str = _SEEDED, **extra) -> dict:
    body = {
        "champion": champion,
        "level": _LEVEL,
        "items": list(_BUILD),
        "mode": "SR",
        "enemy_ad_share": 0.5,
        "enemy_ap_share": 0.5,
        "top": _TOP,
    }
    body.update(extra)
    return body


def _order(result: dict) -> tuple[str, ...]:
    return tuple(r["item_id"] for r in result["ranked"])


def _row(result: dict, item_id: str) -> dict:
    for r in result["ranked"]:
        if r["item_id"] == item_id:
            return r
    raise AssertionError(f"{item_id} is not in the ranked pool")


def _body_keys_by_route() -> dict[str, frozenset[str]]:
    """``"/path" -> every string body key that route's handler reads``.

    Derived by AST off ``server.py``, NOT filtered to the ``apply_`` /
    ``assume_`` seam prefixes the sibling guards use - this pair's magnitude
    half (``mana_coupling_strength``) carries no seam prefix and would be
    invisible to that filter, which is precisely how a half-wired transport
    hides.
    """
    src = pathlib.Path(server.__file__).read_text(encoding="utf-8")
    tree = ast.parse(src)
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
            name = getattr(v, "id", None) or getattr(v, "attr", None)
            if name in handlers:
                path_of.setdefault(k.value, name)
    readers = ("_opt_bool", "_opt_float", "_opt_int", "_opt_str",
               "_coerce_str_list", "_required_str", "get")
    out: dict[str, frozenset[str]] = {}
    for path, handler in path_of.items():
        keys: set[str] = set()
        for node in ast.walk(handlers[handler]):
            if isinstance(node, ast.Call):
                name = (getattr(node.func, "id", None)
                        or getattr(node.func, "attr", None))
                if name in readers:
                    keys.update(
                        a.value for a in node.args
                        if isinstance(a, ast.Constant)
                        and isinstance(a.value, str)
                    )
            elif isinstance(node, ast.Compare) and isinstance(
                node.left, ast.Constant
            ):
                if isinstance(node.left.value, str):
                    keys.add(node.left.value)
        out[path] = frozenset(keys)
    return out


def _routes_reading(key: str) -> frozenset[str]:
    return frozenset(
        path for path, keys in _body_keys_by_route().items() if key in keys
    )


def _engine_owners(key: str) -> frozenset[tuple[str, str]]:
    """``(module, function)`` pairs naming ``key``, swept over the package.

    MEASURED off ``inspect.signature``, never inherited from a docstring - the
    ``test_ehp_survivability_route_seams_rm118.py`` prose was wrong TWICE in one
    run, in OPPOSITE directions.
    """
    found: set[tuple[str, str]] = set()
    for mod_info in pkgutil.iter_modules(ds_pkg.__path__):
        if mod_info.name == "tests":
            continue
        try:
            mod = importlib.import_module(f"agents.daemon_slayer.{mod_info.name}")
        except Exception:                                       # pragma: no cover
            continue
        for fn_name, fn in inspect.getmembers(mod, inspect.isfunction):
            if getattr(fn, "__module__", "") != mod.__name__:
                continue
            try:
                params = inspect.signature(fn).parameters
            except (TypeError, ValueError):                      # pragma: no cover
                continue
            if key in params:
                found.add((mod_info.name, fn_name))
    return frozenset(found)


class _Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        server._CACHE.set(_snap())


class EngineOwnershipTests(_Base):
    """Gate 3 of the three - who the math actually belongs to."""

    def test_the_mana_pair_owner_set_equals_the_health_pair_owner_set(self) -> None:
        expected = frozenset({("ehp", "rank_items_by_ehp")})
        for key in (_FLAG, _MAGNITUDE, _HEALTH_FLAG, _HEALTH_MAGNITUDE):
            with self.subTest(seam=key):
                self.assertEqual(
                    _engine_owners(key), expected,
                    "the engine entry points naming this coupling key changed - "
                    "re-measure the route table before wiring anything",
                )

    def test_the_pair_ships_default_off_on_its_owner(self) -> None:
        params = inspect.signature(rank_items_by_ehp).parameters
        self.assertIs(params[_FLAG].default, False)
        self.assertEqual(params[_MAGNITUDE].default, 0.0)

    def test_compute_ehp_names_neither_coupling_pair(self) -> None:
        """The scope pin ``/ehp`` depends on.

        If a later slice teaches ``compute_ehp`` a coupling lever, THIS goes red
        and points at the ``/ehp`` wire that then needs to grow with it - the
        alternative is a body key silently dropped before the engine call.
        """
        params = inspect.signature(compute_ehp).parameters
        for key in (_FLAG, _MAGNITUDE, _HEALTH_FLAG, _HEALTH_MAGNITUDE):
            with self.subTest(seam=key):
                self.assertNotIn(key, params)


class RouteSetTests(_Base):
    """The mana pair must reach the health pair's route set - and only it."""

    def test_health_pair_route_set_is_exactly_rank_tank(self) -> None:
        # Anti-vacuity: derived, non-empty, and the reference set for the
        # equality below. If this ever reads empty the comparison test would
        # pass on two empty sets and prove nothing.
        for key in (_HEALTH_FLAG, _HEALTH_MAGNITUDE):
            with self.subTest(seam=key):
                self.assertEqual(_routes_reading(key), frozenset({_ROUTE}))

    def test_mana_pair_reaches_exactly_the_health_pair_route_set(self) -> None:
        self.assertEqual(_routes_reading(_FLAG), _routes_reading(_HEALTH_FLAG))
        self.assertEqual(
            _routes_reading(_MAGNITUDE), _routes_reading(_HEALTH_MAGNITUDE)
        )
        self.assertEqual(_routes_reading(_FLAG), frozenset({_ROUTE}))
        self.assertEqual(_routes_reading(_MAGNITUDE), frozenset({_ROUTE}))

    def test_no_other_route_parses_the_mana_pair(self) -> None:
        for path, keys in _body_keys_by_route().items():
            if path == _ROUTE:
                continue
            with self.subTest(route=path):
                self.assertNotIn(_FLAG, keys)
                self.assertNotIn(_MAGNITUDE, keys)

    def test_the_derivation_is_not_vacuous(self) -> None:
        """Negative control: rename the BODY KEY literals and re-derive.

        Proves ``_routes_reading`` reads the handler rather than returning a
        constant. Renaming the quoted key (rather than deleting lines, which
        would leave an unmatched paren and fail to parse at all) is the precise
        mutation: the parse call still exists, it simply no longer reads THIS
        key, which is exactly the pre-wire state. The health pair must still
        read ``/rank-tank`` in the same mutated source.
        """
        src = pathlib.Path(server.__file__).read_text(encoding="utf-8")
        mutated = (
            src.replace(f'"{_FLAG}"', '"zz_not_a_body_key"')
               .replace(f'"{_MAGNITUDE}"', '"zz_not_a_body_key_2"')
        )
        self.assertEqual(mutated.count(f'"{_FLAG}"'), 0)
        self.assertEqual(mutated.count(f'"{_MAGNITUDE}"'), 0)
        with mock.patch.object(
            pathlib.Path, "read_text", lambda self, **kw: mutated
        ):
            self.assertEqual(_routes_reading(_FLAG), frozenset())
            self.assertEqual(_routes_reading(_MAGNITUDE), frozenset())
            self.assertEqual(_routes_reading(_HEALTH_FLAG), frozenset({_ROUTE}))


class TransportSpyTests(_Base):
    """PROOF 1: the parsed value is caught crossing into the engine call."""

    def _spy(self, **extra) -> dict:
        seen: dict = {}
        real = server.rank_items_by_ehp

        def _wrapped(*args, **kwargs):
            seen.update(kwargs)
            return real(*args, **kwargs)

        with mock.patch.object(server, "rank_items_by_ehp", _wrapped):
            server._route_rank_tank(_body(**extra))
        return seen

    def test_absent_keys_reach_the_engine_at_the_default_off_pair(self) -> None:
        seen = self._spy()
        self.assertIs(seen[_FLAG], False)
        self.assertEqual(seen[_MAGNITUDE], 0.0)

    def test_the_armed_pair_reaches_the_engine_verbatim(self) -> None:
        seen = self._spy(**{_FLAG: True, _MAGNITUDE: _STRENGTH})
        self.assertIs(
            seen[_FLAG], True,
            f"{_FLAG} was parsed but never reached rank_items_by_ehp",
        )
        self.assertEqual(
            seen[_MAGNITUDE], _STRENGTH,
            f"{_MAGNITUDE} was parsed but never reached rank_items_by_ehp",
        )

    def test_the_magnitude_is_not_rounded_or_coerced_to_the_flag(self) -> None:
        # A transport that forwarded ``bool(strength)`` or an int would pass a
        # presence grep and a coarse ON/OFF assertion; this catches it.
        seen = self._spy(**{_FLAG: True, _MAGNITUDE: 2.5})
        self.assertIsInstance(seen[_MAGNITUDE], float)
        self.assertEqual(seen[_MAGNITUDE], 2.5)


class ArmedRankingTests(_Base):
    """PROOF 2 and 3: a measured ORDER move and a measured row value."""

    def _rank(self, champion: str = _SEEDED, **extra) -> dict:
        return server._route_rank_tank(_body(champion, **extra))

    def test_the_route_order_actually_moves(self) -> None:
        # Blitzcrank, level 13, SR, Sunfire + Plated Steelcaps over the full
        # 138-row pool. The credit is monotone in the candidate's mana delta, so
        # the mana rows float above the mana-free rows and WHICH item ranks
        # where changes - not merely a row value.
        off = self._rank()
        on = self._rank(**{_FLAG: True, _MAGNITUDE: _STRENGTH})
        self.assertNotEqual(
            _order(off), _order(on),
            f"{_FLAG} was parsed but the engine call never saw it",
        )

    def test_the_measured_mana_movers_gain_rank(self) -> None:
        off, on = _order(self._rank()), _order(
            self._rank(**{_FLAG: True, _MAGNITUDE: _STRENGTH})
        )
        for item in (_FROZEN_HEART, _WINTERS_APPROACH):
            with self.subTest(item=item):
                self.assertLess(
                    on.index(item), off.index(item),
                    "a mana-granting candidate did not gain rank with the "
                    "coupling armed",
                )

    def test_the_zero_mana_control_does_not_gain_rank(self) -> None:
        off, on = _order(self._rank()), _order(
            self._rank(**{_FLAG: True, _MAGNITUDE: _STRENGTH})
        )
        self.assertGreaterEqual(
            on.index(_THORNMAIL), off.index(_THORNMAIL),
            "a zero-mana candidate gained rank - the credit is not keyed by mana",
        )

    def test_the_row_evidence_the_credit_ran(self) -> None:
        off = self._rank()
        on = self._rank(**{_FLAG: True, _MAGNITUDE: _STRENGTH})
        self.assertEqual(_row(off, _FROZEN_HEART)["delta_max_mp"], 0.0)
        self.assertGreater(_row(on, _FROZEN_HEART)["delta_max_mp"], 0.0)

    def test_the_credit_is_sort_only_on_every_pre_existing_field(self) -> None:
        """Anti-double-count: no shipped row value may move, only the ORDER.

        ``delta_max_mp`` is the one legitimate difference - an additive
        observability key the lane populates - so it is excluded by name and
        asserted separately above.
        """
        off = {r["item_id"]: dict(r) for r in self._rank()["ranked"]}
        on = {
            r["item_id"]: dict(r)
            for r in self._rank(**{_FLAG: True, _MAGNITUDE: _STRENGTH})["ranked"]
        }
        self.assertEqual(set(off), set(on))
        for item_id, row in off.items():
            row.pop("delta_max_mp", None)
            other = dict(on[item_id])
            other.pop("delta_max_mp", None)
            with self.subTest(item=item_id):
                self.assertEqual(row, other)

    def test_the_unseeded_champion_is_arm_but_inert(self) -> None:
        off = self._rank(_UNSEEDED)
        on = self._rank(_UNSEEDED, **{_FLAG: True, _MAGNITUDE: _STRENGTH})
        self.assertEqual(_order(off), _order(on))
        self.assertEqual(off["ranked"], on["ranked"])
        added = [n for n in (on.get("notes") or [])
                 if n not in (off.get("notes") or [])]
        self.assertTrue(
            any("ON but inert" in n for n in added),
            "the arm-but-inert operator note did not survive the route",
        )


class ByteIdenticalTransportTests(_Base):
    """DEFAULT-OFF, three arms. A future transport removal fails LOUDLY above."""

    def _rank(self, **extra) -> dict:
        return server._route_rank_tank(_body(**extra))

    def test_absent_keys_equal_the_flag_sent_explicitly_false(self) -> None:
        self.assertEqual(self._rank(), self._rank(**{_FLAG: False}))

    def test_the_armed_flag_at_zero_strength_is_byte_identical(self) -> None:
        self.assertEqual(
            self._rank(), self._rank(**{_FLAG: True, _MAGNITUDE: 0.0})
        )

    def test_the_armed_transport_with_the_flag_off_is_byte_identical(self) -> None:
        """The magnitude half sent ALONE must be inert.

        This is this seam's "armed transport, flags OFF" control: there is no
        separate roster key here, so the transport IS the pair, and a caller
        that sends a magnitude without opening the gate must get exactly the
        pre-wire response.
        """
        self.assertEqual(self._rank(), self._rank(**{_MAGNITUDE: _STRENGTH}))
        self.assertEqual(
            self._rank(),
            self._rank(**{_FLAG: False, _MAGNITUDE: _STRENGTH}),
        )

    def test_a_negative_magnitude_is_a_400(self) -> None:
        with self.assertRaises(server._ApiError) as ctx:
            self._rank(**{_FLAG: True, _MAGNITUDE: -1.0})
        self.assertEqual(ctx.exception.status, 400)
        self.assertIn(_MAGNITUDE, str(ctx.exception))

    def test_the_guard_mirrors_the_health_pair_verbatim(self) -> None:
        # Same coercion, same defaults, same 400 shape - the mirror the slice
        # was scoped to produce, asserted rather than asserted-in-prose.
        src = inspect.getsource(server._route_rank_tank)
        for flag, magnitude in ((_HEALTH_FLAG, _HEALTH_MAGNITUDE),
                                (_FLAG, _MAGNITUDE)):
            with self.subTest(seam=flag):
                self.assertRegex(
                    src, rf'_opt_bool\(\s*body,\s*"{flag}",\s*False\s*\)'
                )
                self.assertRegex(
                    src, rf'_opt_float\(\s*body,\s*"{magnitude}",\s*0\.0\s*\)'
                )
                self.assertRegex(src, rf"if {magnitude} < 0\.0:")


class ClientWiringTests(_Base):
    """Gate 2 from the caller's side: the client must be able to SEND it."""

    def _sent(self, **kwargs) -> dict:
        seen: dict = {}

        def _fake(path, body, timeout=0.0):
            seen["path"] = path
            seen["body"] = body
            return {"ranked": []}

        with mock.patch.object(client_mod, "_post_json", _fake):
            getattr(client_mod, _CLIENT_FN)(
                _SEEDED, level=_LEVEL, item_ids=list(_BUILD), **kwargs
            )
        return seen

    def test_the_signature_mirrors_the_health_pair(self) -> None:
        params = inspect.signature(getattr(client_mod, _CLIENT_FN)).parameters
        for key in (_FLAG, _MAGNITUDE, _HEALTH_FLAG, _HEALTH_MAGNITUDE):
            with self.subTest(seam=key):
                self.assertIn(key, params)
                self.assertIsNone(params[key].default)

    def test_the_pair_is_appended_at_the_end_of_the_signature(self) -> None:
        names = list(inspect.signature(getattr(client_mod, _CLIENT_FN)).parameters)
        self.assertEqual(tuple(names[-2:]), (_FLAG, _MAGNITUDE))

    def test_a_flagless_call_omits_both_keys(self) -> None:
        bare = self._sent()
        self.assertEqual(bare["path"], _ROUTE)
        self.assertNotIn(_FLAG, bare["body"])
        self.assertNotIn(_MAGNITUDE, bare["body"])

    def test_an_armed_call_emits_both_keys_the_route_parses(self) -> None:
        armed = self._sent(**{_FLAG: True, _MAGNITUDE: _STRENGTH})
        self.assertIs(armed["body"][_FLAG], True)
        self.assertEqual(armed["body"][_MAGNITUDE], _STRENGTH)
        self.assertIsInstance(armed["body"][_MAGNITUDE], float)
        # The item list rides the ``items`` key, NEVER ``item_ids`` - an
        # ``item_ids`` body is silently dropped and probes an empty build.
        self.assertEqual(armed["body"]["items"], list(_BUILD))
        self.assertNotIn("item_ids", armed["body"])

    def test_an_explicit_false_is_expressible(self) -> None:
        # ``None`` means inherit, so the client must still be able to say OFF.
        body = self._sent(**{_FLAG: False})["body"]
        self.assertIs(body[_FLAG], False)

    def test_the_body_the_client_emits_is_what_the_route_parses(self) -> None:
        """End to end across BOTH files, not two independent presence checks."""
        armed = self._sent(**{_FLAG: True, _MAGNITUDE: _STRENGTH})["body"]
        armed["top"] = _TOP
        off = server._route_rank_tank(_body())
        on = server._route_rank_tank(armed)
        self.assertNotEqual(
            _order(off), _order(on),
            "the client-emitted body did not move the route's ranking - the two "
            "halves of the wire disagree",
        )


class StrandedLedgerTests(_Base):
    """The debt ledger can only shrink - this seam must have left it."""

    def test_the_mana_flag_is_no_longer_stranded(self) -> None:
        src = pathlib.Path(server.__file__).read_text(encoding="utf-8")
        self.assertNotIn(_FLAG, stranded_seams(src))
        self.assertNotIn(
            _FLAG, STRANDED_TODAY,
            "the seam is wired - delete its STRANDED_TODAY entry so the ledger "
            "keeps shrinking",
        )

    def test_the_per_route_guard_sees_the_pair_as_reached(self) -> None:
        parsed, _ = _route_table()
        self.assertIn(_FLAG, parsed[_ROUTE])
        self.assertIn(_FLAG, _client_by_route()[_ROUTE])


if __name__ == "__main__":
    unittest.main()
