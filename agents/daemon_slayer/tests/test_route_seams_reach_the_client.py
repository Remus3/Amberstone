"""Every seam a /rank route PARSES must be reachable from the Python client.

THE BUG CLASS THIS EXISTS TO KILL
---------------------------------
``agents/daemon_slayer/server.py`` grows a new operator seam almost every DS
batch: a body key, a ``_opt_bool`` parse, a kwarg forwarded to the engine. The
in-repo consumer of those routes is ``core/daemon_slayer_client.py``, and its
functions take EXPLICIT keyword arguments - there is no ``**kwargs`` passthrough
on ``rank_tank_for``. So a seam added on the server side and not mirrored on the
client side is born unreachable: it exists, it is documented, it is tested
in-process, and no shipped RC code path can ever set it.

The 2026-07-25 instance that motivated this file was worse than unreachable. The
three ASSUMED-INCOMING-SHARE flags (``assume_item_crit_dr`` /
``assume_item_aa_dr`` / ``assume_item_enemy_as_slow``) were armed DEFAULT-ON
inside ``compute_ehp`` while ``rank_items_by_ehp`` did not expose them at all -
an assumption worth +49.7 pct on Randuin's dEHP with NO off switch at any gate.

WHAT IS CHECKED
---------------
By INTROSPECTION over the two source files, never a hardcoded key list:

  * parse ``server.py``, collect every string literal read out of ``body`` inside
    a ``_route_*`` handler whose name is seam-shaped (``apply_`` / ``assume_`` /
    ``gate_`` / ``exclude_`` prefix),
  * parse ``daemon_slayer_client.py``, collect every keyword-argument name and
    every string used as a request-body key (docstring prose deliberately does
    NOT count - mentioning a seam is not exposing it),
  * assert the stranded set is EXACTLY the allowlist below.

THE ALLOWLIST IS A DEBT LEDGER, NOT AN EXEMPTION
------------------------------------------------
Every name in ``_STRANDED_TODAY`` is a real gap: a seam an operator can hit with
curl but not from RC code. It is written down so this test is GREEN on arrival
rather than blocking on 33 unrelated wirings, and the equality (not a subset
check) makes it self-cleaning in both directions:

  * add a NEW route seam with no client wire  -> RED (that is the point),
  * WIRE one of these into the client         -> RED until it is deleted here,
    so the ledger can only shrink.

The intended end state is an empty allowlist.

MEASUREMENT NOTE (2026-07-25): the hand-off for this file listed 36 stranded
seams including ``gate_caster_hp`` and ``gate_target_hp``. Neither string exists
in ``server.py`` - only the ``_amp`` variants ``gate_caster_hp_amp`` /
``gate_target_hp_amp`` are parsed (server.py ``_route_burst``). Those two entries
were dropped, the measurement was trusted over the hand-off, and
``apply_resist_damage_coupling`` was wired into ``rank_tank_for`` in this same
change, leaving 33.

OFFLINE ONLY: pure AST over two source files. No snapshot, no engine, no network.
"""
from __future__ import annotations

import ast
import pathlib
import unittest

import agents.daemon_slayer.server as server_mod
import core.daemon_slayer_client as client_mod

_SERVER_PY = pathlib.Path(server_mod.__file__)
_CLIENT_PY = pathlib.Path(client_mod.__file__)

# A body key is "seam-shaped" when it reads as an operator lever rather than a
# query input. ``champion`` / ``level`` / ``items`` / ``top`` are inputs;
# ``apply_x`` / ``assume_x`` / ``gate_x`` / ``exclude_x`` are levers.
_SEAM_PREFIXES = ("apply_", "assume_", "gate_", "exclude_")

# The body-reading helpers in server.py. Each takes the body first and the key
# name as a string literal.
_BODY_READERS = ("_opt_bool", "_opt_float", "_opt_int", "_opt_str",
                 "_coerce_str_list", "_required_str", "get")

# --------------------------------------------------------------- the debt ledger
# Route-parsed, client-unreachable as of 2026-07-25 (ENGINE 1.249.0). Measured by
# the introspection below, NOT copied from prose. Grouped by the route that owns
# them so a future wiring pass can take one route at a time.
_STRANDED_TODAY = frozenset({
    # --- EHP-family levers (/ehp, /hybrid, /rank-tank, /rank-bruiser) ---------
    "apply_build_tenacity",
    "apply_champion_tenacity",
    "apply_item_bonus_hp_amp",
    "apply_item_mana_health",
    "apply_item_resist_grants",
    "apply_item_spell_shield",
    "apply_passive_mitigation",
    "apply_passive_resist",
    "apply_passive_revive",
    "apply_rune_flat_mitigation",
    "apply_rune_health_grants",
    "apply_rune_hsp_amp",
    "apply_rune_resist_grants",
    "apply_spell_shield",
    "apply_survival_window",
    "assume_item_general_dr",
    "assume_item_health_stacks",
    "assume_item_proc_heal",
    # --- damage-family levers (/dps, /ability-dps, /rank-mage, /rank-bruiser) -
    "apply_ability_amps",
    "apply_ad_axis_ability_damage",
    "apply_melee_aa_gate",
    # --- burst / assassin levers (/burst, /rank-assassin) --------------------
    "assume_ability_amp",
    "assume_physical_burst",
    "assume_shielded_target",
    "assume_squishy_target",
    "assume_takedown",
    "gate_caster_hp_amp",
    "gate_target_hp_amp",
    # --- fight-report levers (/fight-report) ---------------------------------
    "apply_ability_haste",
    "gate_ammo",
    # --- cross-route ----------------------------------------------------------
    "apply_mode_modifiers",
    "exclude_off_axis_items",
})


def _route_parsed_seams() -> dict[str, frozenset[str]]:
    """seam key -> the ``_route_*`` handlers that parse it, from server.py AST."""
    tree = ast.parse(_SERVER_PY.read_text(encoding="utf-8"))
    found: dict[str, set[str]] = {}
    for fn in ast.walk(tree):
        if not isinstance(fn, ast.FunctionDef) or not fn.name.startswith("_route_"):
            continue
        for node in ast.walk(fn):
            keys: list[str] = []
            if isinstance(node, ast.Call):
                name = getattr(node.func, "id", None) or getattr(
                    node.func, "attr", None
                )
                if name in _BODY_READERS:
                    keys += [
                        a.value for a in node.args
                        if isinstance(a, ast.Constant) and isinstance(a.value, str)
                    ]
            elif isinstance(node, ast.Compare) and isinstance(
                node.left, ast.Constant
            ):
                # the ``"key" in body`` tri-state idiom
                if isinstance(node.left.value, str):
                    keys.append(node.left.value)
            elif isinstance(node, (ast.Tuple, ast.List)):
                # a seam name iterated over a literal sequence (the
                # ``for seam in ("a", "b"): if seam in body`` shape). Collected
                # so a handler cannot hide a seam from this guard just by
                # looping over its keys. The prefix filter below keeps unrelated
                # literal tuples (sort keys, score_by allowlists) out.
                keys += [
                    e.value for e in node.elts
                    if isinstance(e, ast.Constant) and isinstance(e.value, str)
                ]
            for k in keys:
                if k.startswith(_SEAM_PREFIXES):
                    found.setdefault(k, set()).add(fn.name)
    return {k: frozenset(v) for k, v in found.items()}


def _client_expressible_names() -> frozenset[str]:
    """Names a caller can actually SET through daemon_slayer_client.

    Two sources, both structural: keyword-argument names on the module's
    functions, and strings used as request-body keys. Docstring prose is
    excluded on purpose - naming a seam in a comment does not expose it.
    """
    tree = ast.parse(_CLIENT_PY.read_text(encoding="utf-8"))
    names: set[str] = set()
    for fn in ast.walk(tree):
        if isinstance(fn, ast.FunctionDef):
            a = fn.args
            for arg in list(a.posonlyargs) + list(a.args) + list(a.kwonlyargs):
                names.add(arg.arg)
    for node in ast.walk(tree):
        # body["key"] = ... / body.get("key")
        if isinstance(node, ast.Subscript) and isinstance(node.slice, ast.Constant):
            if isinstance(node.slice.value, str):
                names.add(node.slice.value)
        # {"key": value} literals
        elif isinstance(node, ast.Dict):
            names.update(
                k.value for k in node.keys
                if isinstance(k, ast.Constant) and isinstance(k.value, str)
            )
        # ("key", value) emit-pair tuples
        elif isinstance(node, ast.Tuple):
            names.update(
                e.value for e in node.elts
                if isinstance(e, ast.Constant) and isinstance(e.value, str)
            )
    return frozenset(names)


class RouteSeamReachabilityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.seams = _route_parsed_seams()
        cls.client = _client_expressible_names()
        cls.stranded = frozenset(k for k in cls.seams if k not in cls.client)

    def test_introspection_actually_found_seams(self) -> None:
        """Guard the guard - a broken parse must not read as a clean bill."""
        self.assertGreater(
            len(self.seams), 30,
            "the server.py AST scan found almost no seam keys - the parse "
            "shape drifted, so every other assertion here is vacuous",
        )
        self.assertIn("apply_mode_modifiers", self.seams)
        self.assertIn("assume_item_crit_dr", self.seams)

    def test_no_new_stranded_route_seam(self) -> None:
        new = sorted(self.stranded - _STRANDED_TODAY)
        self.assertEqual(
            new, [],
            "new route seam(s) parsed by server.py with no way to set them "
            f"from core/daemon_slayer_client.py: {new}. Add the keyword "
            "argument to the owning client function (None = inherit, omit the "
            "key) rather than adding the name to _STRANDED_TODAY.",
        )

    def test_allowlist_has_no_stale_entries(self) -> None:
        stale = sorted(_STRANDED_TODAY - self.stranded)
        self.assertEqual(
            stale, [],
            "these seams are now reachable from the client - delete them from "
            f"_STRANDED_TODAY so the debt ledger keeps shrinking: {stale}",
        )

    def test_assumed_share_seams_are_wired_end_to_end(self) -> None:
        """The named regression: the three DEFAULT-ON assumption flags."""
        for seam in ("assume_item_crit_dr", "assume_item_aa_dr",
                     "assume_item_enemy_as_slow"):
            self.assertIn(seam, self.seams, f"{seam} is not parsed by any route")
            self.assertIn(
                seam, self.client,
                f"{seam} is parsed by a route but unreachable from the client",
            )
            self.assertNotIn(seam, _STRANDED_TODAY)

    def test_resist_damage_coupling_pair_is_wired(self) -> None:
        """RM-87's 1.247.0 ship, wired in the same change as the ledger."""
        self.assertIn("apply_resist_damage_coupling", self.client)
        self.assertIn("resist_coupling_strength", self.client)
        self.assertNotIn("apply_resist_damage_coupling", _STRANDED_TODAY)


if __name__ == "__main__":
    unittest.main()
