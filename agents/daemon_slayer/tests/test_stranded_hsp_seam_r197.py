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
import importlib
import inspect
import pathlib
import re
import sys
import textwrap
import unittest

from .. import server as S
from ..data_loader import DataSnapshot
from ..ehp import compute_ehp
from ..sustain import compute_sustain
from .._hsp_amp import sum_wielder_hsp_pct

SERVER_PATH = pathlib.Path(S.__file__)
SERVER_SRC = SERVER_PATH.read_text(encoding="utf-8")
_PKG = "agents.daemon_slayer"

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


# RM-333 - THE DEFAULT-TYPE AXIS.
#
# RM-207 (below) recorded the NAME axis of this checker's blindness: a seam
# wired at the route level under a DIFFERENT PARAMETER NAME reads as stranded,
# because the checker keys on the name. This is the same failure along a NEW
# axis - A SEAM UNDER A DIFFERENT DEFAULT TYPE IS INVISIBLE TO A DEFAULT-KEYED
# CHECKER. Both tiers keyed on ``p.default is False``, so
# ``apply_canonical_cast_rate_keys`` (``bool | None = None`` on
# ``ult_rates.get_ult_casts_per_sec``, ult_rates.py:167, and
# ``get_spell_casts_per_sec``, ult_rates.py:205) was in NEITHER universe, and
# both equality ledgers stayed green while the seam was unreachable from every
# route. ``grep -c apply_canonical_cast_rate_keys server.py`` returns 0.
#
# ``None`` is a DEFAULT-OFF seam here, not a third state to skip. Both
# surviving None-defaulting seams document the same tri-state contract: the
# kwarg defers to a value the CALLER did not choose - the module global
# ``ult_rates.APPLY_CANONICAL_CAST_RATE_KEYS`` (``False``) for the cast-rate
# seam, a derived per-route default for ``apply_build_tenacity``. "The caller
# did not decide" is exactly the shape of a seam a route has to be able to set,
# which is what this guard exists to measure.
#
# This predicate widens the DEPTH-0 universe only. The tri-state residue at
# depth 1 gets its own tier and its own ledger - see STRANDED_TRISTATE and the
# comment above it for why growing STRANDED_DEPTH1 was the wrong move.
def _is_seam_default(default: object) -> bool:
    """Is this parameter default the DEFAULT-OFF shape a seam must have.

    ``is`` not ``==`` on both arms, so a 0 / 0.0 numeric default is not swept
    in as a boolean seam. ``True`` is deliberately NOT admitted: a DEFAULT-ON
    parameter has nothing to strand, since a route that omits the key still
    gets the behaviour, and admitting one would write a phantom row into a
    ledger. A parameter with no default at all (``inspect.Parameter.empty``)
    is likewise not a seam - every caller is forced to pass it.
    """
    return default is False or default is None


def _engine_seams() -> dict[str, list[str]]:
    """Every DEFAULT-OFF seam kwarg on a route-facing entry point -> its owners.

    A seam is a parameter named ``assume_`` / ``apply_`` / ``use_`` whose
    default is DEFAULT-OFF per ``_is_seam_default`` - ``False``, or ``None``
    for a tri-state seam (RM-333).
    """
    seams: dict[str, list[str]] = {}
    for fq, fn in _route_facing_entry_points().items():
        for p in inspect.signature(fn).parameters.values():
            if p.name.startswith(("assume_", "apply_", "use_")) and _is_seam_default(
                p.default
            ):
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

    RM-202: also counts keys forwarded through a ``**splat``. Collecting only
    ``kw.arg`` made this helper blind to ``handler(**assumed_share_kwargs)`` at
    ``server.py:1155``, and it reported three genuinely-wired keys
    (assume_item_aa_dr / assume_item_crit_dr / assume_item_enemy_as_slow) as
    stranded. That is the one blind spot in this file that produces FALSE
    POSITIVES rather than false negatives - it would have written three lies
    into the debt ledger. Resolution is precise, not an over-approximation:
    only dicts that are actually splatted into a call are read, so this cannot
    silently mark an unrelated seam as reachable.
    """
    tree = ast.parse(src)
    explicit = {
        kw.arg
        for n in ast.walk(tree)
        if isinstance(n, ast.Call)
        for kw in n.keywords
        if kw.arg
    }
    splatted = {
        kw.value.id
        for n in ast.walk(tree)
        if isinstance(n, ast.Call)
        for kw in n.keywords
        if kw.arg is None and isinstance(kw.value, ast.Name)
    }
    via_splat: set[str] = set()
    for n in ast.walk(tree):
        if not isinstance(n, ast.Assign):
            continue
        for t in n.targets:
            # opts["key"] = ...
            if (
                isinstance(t, ast.Subscript)
                and isinstance(t.value, ast.Name)
                and t.value.id in splatted
                and isinstance(t.slice, ast.Constant)
                and isinstance(t.slice.value, str)
            ):
                via_splat.add(t.slice.value)
            # opts = {"key": ...}
            if (
                isinstance(t, ast.Name)
                and t.id in splatted
                and isinstance(n.value, ast.Dict)
            ):
                via_splat.update(
                    k.value
                    for k in n.value.keys
                    if isinstance(k, ast.Constant) and isinstance(k.value, str)
                )
    return explicit | via_splat


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
    # (The HSP ABILITY lane - apply_ability_hsp_amp - was wired to /hps at
    # ENGINE 1.274.0 and is therefore gone from this ledger. The "own slice, not
    # measured here" reason it carried was discharged by measurement: it is a
    # pure boolean over the amp_factor this route already derives from
    # ``item_ids``, and ``rank_items_by_hps`` cannot read it, so /hps is the
    # sole owner and /rank-enchanter must never carry the key.)
    # (The RM-98 cast-rate propensity PRIOR - apply_cast_rate_propensity_prior -
    # and the R58 hybrid MS utility term - assume_ms_utility - were wired to
    # /hybrid and /rank-bruiser at the same ENGINE 1.274.0 and are likewise
    # gone.)
    # (The R212 crit CHANCE / crit DAMAGE MULTIPLIER lane -
    # apply_crit_chance_overrides - was wired to /dps at ENGINE 1.274.0. Its
    # "unmeasured live flip" reason confused two questions: this slice exposes
    # the seam DEFAULT-OFF, which is byte-identical, and does NOT flip a live
    # default. The default flip remains unshipped and unclaimed.)
    # See test_stranded_lane_route_seams_rm118.py for all four measured route
    # tables, the per-route asymmetry guards and the ON-path movement proofs.
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
    # (The FIVE per-item shield opt-ins into the EHP ItemShield pool -
    # assume_kaenic_shield / assume_eclipse_shield / assume_chainlaced_shield /
    # assume_seraphs_shield / assume_fimbulwinter_shield - were wired to /ehp and
    # to ``core.daemon_slayer_client.ehp_for`` and are therefore gone from this
    # ledger. Their "live flip operator-gated" reason confused two questions, the
    # same way the crit-chance lane's did: that slice exposes the seams
    # DEFAULT-OFF, which is byte-identical, and does NOT flip any live default.
    # The default flip remains unshipped, unclaimed and operator-gated. See
    # test_per_item_shield_route_seams_rm118.py for the measured per-seam route
    # table, the per-item non-leak proof and the ON-path movement pairs.)
    # (The two vamp lanes - assume_crit_weighted_vamp / assume_cleave_lifesteal -
    # were wired at ENGINE 1.268.0, together with the non-boolean
    # ``targets_in_rotation`` transport the cleave lane needs, and are therefore
    # gone from this ledger. See test_vamp_lane_route_seams_rm118.py for the
    # measured per-seam route table.)
    # (The RM-118 mana lane - apply_mana_damage_coupling - was wired to
    # /rank-tank and to ``core.daemon_slayer_client.rank_tank_for`` in its own
    # follow-up slice, exactly as its two shipped siblings
    # (apply_resist_damage_coupling / apply_health_damage_coupling) were, and is
    # therefore gone from this ledger. See
    # test_mana_coupling_transport_rm118.py for the measured route table and the
    # end-to-end reachability proof.)
}


# ---------------------------------------------------------------------------
# RM-202 - THE DEPTH-1 TIER
#
# The guard above is GREEN and was structurally BLIND. Its universe is the 32
# functions server.py calls DIRECTLY; a seam owned by a function that one of
# those 32 calls is invisible to it. That is not a depth-of-call-stack claim -
# ``cc_pressure.compute_cc_pressure`` is ONE hop from a live route and has five
# production callers - it is membership in a closed set.
#
# Extending by exactly one hop needed TWO resolution fixes that the depth-0
# helpers did not need, both measured rather than predicted:
#
#   1. FUNCTION-LOCAL IMPORTS. ``getattr(module, name)`` cannot see
#      ``from .cc_pressure import compute_cc_pressure`` written INSIDE
#      ``compute_ehp`` (ehp.py:2510, a deliberate lazy import that breaks a
#      circular module load). Depth extension ALONE still did not reach
#      ``apply_cc_floor``; the local-import map is what reaches it.
#   2. ``**SPLAT`` FORWARDING - see _passed_kwargs. Without it this tier
#      reported three genuinely-wired keys as stranded.
#
# WHY A SECOND LEDGER RATHER THAN APPENDING TO STRANDED_TODAY
# -----------------------------------------------------------
# RM-202's acceptance asks for two things that look contradictory: the guard
# must go RED until each new name is wired or ledgered, AND the ledger must
# stay an equality that can only ever shrink. Appending six names to
# STRANDED_TODAY would GROW it and break its ratchet.
#
# The contradiction dissolves once "can only shrink" is read as a property of a
# ledger relative to a FIXED universe. Widening the universe does not ADD debt,
# it REVEALS debt that was always there. So the depth-0 ledger is left
# byte-exact - its ratchet is untouched and still measures exactly what it
# always measured - and the newly-visible tier gets its OWN baseline and its
# OWN equality, which can likewise only shrink from here. Ledgering with a
# stated reason is the same choice the depth-0 ledger made and documented: it
# keeps the guard green on arrival instead of blocking on unrelated wirings.
# ---------------------------------------------------------------------------
def _local_import_map(tree: ast.AST) -> dict[str, str]:
    """Names bound by ``from .mod import name`` anywhere in ``tree``."""
    out: dict[str, str] = {}
    for n in ast.walk(tree):
        if isinstance(n, ast.ImportFrom) and n.module:
            target = f"{_PKG}.{n.module}" if n.level else n.module
            for a in n.names:
                out[a.asname or a.name] = target
    return out


def _callees(fn: object) -> dict[str, object]:
    """Package functions ``fn`` calls, by qualified name.

    Resolved through the defining module namespace FIRST and through the
    function's own local imports second - a lazy import inside a function body
    never lands in the module namespace.
    """
    mod = sys.modules[fn.__module__]
    try:
        tree = ast.parse(textwrap.dedent(inspect.getsource(fn)))
    except (OSError, TypeError, SyntaxError):
        return {}
    local = _local_import_map(tree)
    out: dict[str, object] = {}
    for n in ast.walk(tree):
        if not (isinstance(n, ast.Call) and isinstance(n.func, ast.Name)):
            continue
        name = n.func.id
        obj = getattr(mod, name, None)
        if obj is None and name in local:
            try:
                obj = getattr(importlib.import_module(local[name]), name, None)
            except Exception:  # noqa: BLE001 - unimportable is simply not a seam
                obj = None
        if not inspect.isfunction(obj):
            continue
        owner = getattr(obj, "__module__", "") or ""
        if not owner.startswith(_PKG) or owner.endswith(".server"):
            continue
        out[f"{owner.rsplit('.', 1)[-1]}.{name}"] = obj
    return out


def _depth1_functions() -> dict[str, object]:
    """Package functions called BY a route-facing entry point, minus the
    entry points themselves."""
    eps = _route_facing_entry_points()
    out: dict[str, object] = {}
    for fn in eps.values():
        for fq, obj in _callees(fn).items():
            if fq not in eps:
                out[fq] = obj
    return out


def _depth1_only_seams() -> dict[str, list[str]]:
    """DEFAULT-OFF seams visible at depth 1 and NOT already at depth 0."""
    depth0 = _engine_seams()
    seams: dict[str, list[str]] = {}
    for fq, fn in sorted(_depth1_functions().items()):
        for p in inspect.signature(fn).parameters.values():
            # RM-333 deliberately does NOT widen THIS tier to _is_seam_default.
            # Doing so is byte-exact for every other name but pulls
            # apply_canonical_cast_rate_keys into STRANDED_DEPTH1, which GROWS a
            # ledger whose emptiness is a measured floor - and is pinned as such
            # from another file. The tri-state residue gets its own tier below,
            # exactly as RM-202 gave the depth-1 residue its own rather than
            # appending to STRANDED_TODAY.
            if p.name.startswith(("assume_", "apply_", "use_")) and p.default is False:
                if p.name not in depth0:
                    seams.setdefault(p.name, []).append(fq)
    return seams


# RM-207 - ENGINE-INTERNAL BY RENAME, NOT DEBT.
#
# A fifth blind-spot class, and the only one that cannot be fixed by widening
# the universe: this checker keys on the PARAMETER NAME, so a seam that is
# fully wired at the route level under a DIFFERENT name reads as stranded.
# ``hybrid.py:657`` forwards ``apply_dual_scaling_split=<route name>``, and the
# route name is on three depth-0 entry points, parsed and passed by server.py,
# and exposed on the Python client.
#
# This is an EXCLUSION, not an exemption, and it is required to PROVE its own
# reason: the test below asserts the named route-level twin is genuinely wired
# and not itself stranded. If that twin ever strands, this exclusion goes RED
# instead of quietly hiding real debt - which is the failure mode an untested
# exemption list always eventually becomes.
DEPTH1_ENGINE_INTERNAL: dict[str, str] = {
    "apply_dual_scaling_split": "apply_ad_axis_dual_scaling_split",
}


def stranded_seams_depth1(src: str) -> dict[str, list[str]]:
    """Depth-1-only seams that ``src`` neither parses nor forwards.

    Excludes internal parameter names that a route-level seam forwards under a
    different name - see DEPTH1_ENGINE_INTERNAL.
    """
    parsed, passed = _parsed_keys(src), _passed_kwargs(src)
    return {
        name: owners
        for name, owners in _depth1_only_seams().items()
        if name not in DEPTH1_ENGINE_INTERNAL
        and not (name in parsed and name in passed)
    }


# Measured 2026-08-15 against 219 depth-1 functions. Started at 3 and SHRANK to
# 2 the same day: RM-207 established that apply_dual_scaling_split is wired
# under a different name, so it moved to DEPTH1_ENGINE_INTERNAL above rather
# than being deleted. SHRANK to 1 when RM-201 wired apply_cc_floor onto /ehp -
# a real drain, not a reclassification: server.py now parses and forwards it,
# and compute_ehp names it, so the seam left this tier by being fixed. Equality,
# so this tier can only ever shrink from here - exactly like STRANDED_TODAY,
# from its own baseline rather than by editing depth-0's.
STRANDED_DEPTH1: dict[str, str] = {
    # (assume_scaling_hsp_grants was WIRED by RM-200 - threaded through
    # ehp.compute_ehp and sustain.compute_sustain to its sole owner
    # _hsp_amp.sum_wielder_hsp_pct, parsed and passed on /ehp and /sustain, and
    # exposed on the Python client. Threading it through two route-facing entry
    # points promoted it OUT of this tier and into the depth-0 universe, where
    # the depth-0 guard now measures it as reachable. See
    # test_scaling_hsp_route_seam_rm200.py for the measured per-seam route
    # table and the ON-path movement proofs.)
    # (apply_cc_floor was WIRED by RM-201 in the same batch - forwarded from
    # ehp.compute_ehp to its depth-1 owner cc_pressure.compute_cc_pressure,
    # parsed and passed on /ehp, and exposed on the Python client together with
    # include_conditional, which the floor is an AND-gate with. See
    # test_cc_floor_route_seam_rm201.py.)
    #
    # This tier is now EMPTY, which is the ledger reaching its floor rather than
    # the guard going quiet: both names left by being WIRED, and both left by
    # landing on a depth-0 entry point, so the depth-0 guard measures them from
    # here on. The equality below still fails on any newly-revealed depth-1 seam.
    #
    # RM-333 left this dict BYTE-EXACT on purpose. Its tri-state residue lives
    # in STRANDED_TRISTATE below, not here - see the comment on that ledger.
}


# ---------------------------------------------------------------------------
# RM-333 - THE TRI-STATE TIER
#
# _is_seam_default (above) widened the DEPTH-0 universe to admit a ``None``
# default. Measured, that adds ZERO new names there: apply_build_tenacity is
# the only None-defaulting prefixed parameter on the 32 depth-0 entry points
# and it was already in that universe through ehp.compute_ehp /
# hybrid.compute_hybrid (``bool = False``), so the widening gives it two extra
# OWNERS and STRANDED_TODAY does not move at all.
#
# The whole tri-state residue is therefore at DEPTH 1, and it is exactly one
# name. It gets its OWN tier rather than being appended to STRANDED_DEPTH1,
# for the same reason RM-202 refused to append its six names to
# STRANDED_TODAY: STRANDED_DEPTH1's emptiness is a measured FLOOR with its own
# shrink-only equality, and growing it would break that ratchet. Widening a
# universe does not ADD debt, it REVEALS debt that was always there, so the
# newly-visible tier gets its own baseline and its own equality - which can
# likewise only shrink from here.
#
# There is a second, harder reason, and it is the RM-202 lesson applied rather
# than re-learned: STRANDED_DEPTH1 is pinned from ANOTHER FILE
# (test_cc_floor_route_seam_rm201.py asserts it equals {}). A slice that grows
# a shared ledger to record its own finding breaks a neighbour's guard, which
# is the collision that file's own docstring warns about two tests earlier.
# ---------------------------------------------------------------------------
def _tristate_only_seams() -> dict[str, list[str]]:
    """None-defaulting seams visible in NEITHER False-keyed tier -> owners.

    Walks the same two universes the tiers above walk, so this reveals debt
    rather than inventing a new surface: a name already measured at depth 0 or
    depth 1 is excluded, so no seam is ever reported by two tiers at once.
    """
    already = set(_engine_seams()) | set(_depth1_only_seams())
    universe = {**_route_facing_entry_points(), **_depth1_functions()}
    seams: dict[str, list[str]] = {}
    for fq, fn in sorted(universe.items()):
        for p in inspect.signature(fn).parameters.values():
            if (
                p.name.startswith(("assume_", "apply_", "use_"))
                and p.default is None
                and p.name not in already
            ):
                seams.setdefault(p.name, []).append(fq)
    return seams


def stranded_tristate_seams(src: str) -> dict[str, list[str]]:
    """Tri-state seams ``src`` neither parses nor forwards."""
    parsed, passed = _parsed_keys(src), _passed_kwargs(src)
    return {
        name: owners
        for name, owners in _tristate_only_seams().items()
        if not (name in parsed and name in passed)
    }


# Measured 2026-09-03 against the 32 depth-0 entry points plus 220 depth-1
# functions. Exactly one name, and it is the one RM-333 was filed for.
STRANDED_TRISTATE: dict[str, str] = {
    "apply_canonical_cast_rate_keys": (
        "no TRANSPORT, not an unflipped default. The seam sits on two ult_rates "
        "lookups reached only through three intermediaries - ability_dps.py:1378 "
        "and :1501, ability_hps.py:925, dps.py:1369 - and NONE of the three "
        "carries the kwarg: all four call sites pass resolved.champion_name "
        "positionally, so there is nothing for a route key to travel on. Wiring "
        "means threading the parameter through those intermediaries first, which "
        "is its own slice. This is NOT the crit-chance / per-item-shield "
        "confusion recorded in STRANDED_TODAY: exposing the seam DEFAULT-OFF is "
        "byte-identical, and RM-333 did not flip the live default, which stays "
        "False at ult_rates.py:80"
    ),
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


class StrandedSeamGuardDepth1(unittest.TestCase):
    """RM-202 - the tier the depth-0 guard is structurally blind to."""

    def test_depth1_universe_strictly_extends_depth0(self):
        eps = _route_facing_entry_points()
        d1 = _depth1_functions()
        self.assertGreater(len(eps), 25, "depth-0 entry points collapsed")
        self.assertGreater(len(d1), len(eps), "depth-1 did not widen the universe")
        self.assertFalse(
            set(d1) & set(eps),
            "depth-1 must be the NEW functions only, not a superset",
        )

    def test_depth1_stranded_set_equals_the_depth1_ledger(self):
        self.assertEqual(
            sorted(stranded_seams_depth1(SERVER_SRC)),
            sorted(STRANDED_DEPTH1),
            "depth-1 stranded seams drifted - wire the seam into a route, or add "
            "it to STRANDED_DEPTH1 with a reason",
        )

    def test_the_two_seams_rm202_filed_are_now_visible(self):
        # The headline. Both were invisible to the depth-0 guard while it was
        # green. RM-202 made them visible; RM-200 and RM-201 then DRAINED both
        # in one batch, so this asserts the OPPOSITE of what it was written to
        # assert. Every half below is load-bearing, and a bare "not stranded"
        # would NOT be: that negative also passes if a seam were DELETED
        # outright, so the wire itself is pinned in three parts - membership in
        # _engine_seams() proves the promotion to depth 0 (both landed on
        # compute_ehp, which is exactly why _depth1_only_seams no longer offers
        # them), and parsed + passed prove the route wire, the same two-part
        # contract the depth-0 guard applies.
        stranded = stranded_seams_depth1(SERVER_SRC)
        for seam in ("assume_scaling_hsp_grants", "apply_cc_floor"):
            with self.subTest(seam=seam):
                self.assertNotIn(seam, stranded)
                self.assertIn(seam, _engine_seams())
                self.assertIn(seam, _parsed_keys(SERVER_SRC))
                self.assertIn(seam, _passed_kwargs(SERVER_SRC))
                self.assertNotIn(seam, stranded_seams(SERVER_SRC))

    def test_local_import_resolution_is_load_bearing(self):
        # Pins resolution fix 1. compute_cc_pressure is imported INSIDE
        # compute_ehp to break a circular module load, so it is absent from the
        # ehp module namespace - depth extension alone never reaches it.
        import agents.daemon_slayer.ehp as _ehp
        self.assertFalse(
            hasattr(_ehp, "compute_cc_pressure"),
            "compute_cc_pressure became a module attribute - this test's premise "
            "is gone, re-derive whether the local-import map is still needed",
        )
        self.assertIn("cc_pressure.compute_cc_pressure", _depth1_functions())

    def test_splat_forwarded_keys_are_not_reported_stranded(self):
        # Pins resolution fix 2, the one blind spot here that produces FALSE
        # POSITIVES. These three are forwarded through **assumed_share_kwargs,
        # so they are wired; a splat-blind checker would have written all three
        # into the ledger as debt that does not exist.
        stranded = stranded_seams_depth1(SERVER_SRC)
        for name in (
            "assume_item_aa_dr",
            "assume_item_crit_dr",
            "assume_item_enemy_as_slow",
        ):
            with self.subTest(seam=name):
                self.assertIn(name, _parsed_keys(SERVER_SRC))
                self.assertIn(name, _passed_kwargs(SERVER_SRC))
                self.assertNotIn(name, stranded)

    def test_splat_awareness_did_not_move_the_depth0_ledger(self):
        # The depth-0 ratchet must be byte-exact after this change, which is
        # what lets STRANDED_TODAY keep its shrink-only property untouched.
        self.assertEqual(sorted(stranded_seams(SERVER_SRC)), sorted(STRANDED_TODAY))

    def test_depth1_negative_control_goes_red_on_stripped_source(self):
        # Not vacuously green: a wired depth-1 key must read as stranded once
        # its forwarding is removed from the source.
        stripped = SERVER_SRC.replace(
            'assumed_share_kwargs["assume_item_aa_dr"]', '_dropped_aa_dr'
        )
        self.assertNotIn("assume_item_aa_dr", _passed_kwargs(stripped))
        self.assertIn("assume_item_aa_dr", stranded_seams_depth1(stripped))

    def test_engine_internal_exclusions_prove_their_route_level_twin(self):
        # RM-207. An exclusion must EARN its place: the route-level name that
        # forwards this internal one has to be genuinely reachable. If that
        # twin ever strands, this goes red rather than hiding real debt.
        depth0_seams = _engine_seams()
        depth0_stranded = stranded_seams(SERVER_SRC)
        parsed, passed = _parsed_keys(SERVER_SRC), _passed_kwargs(SERVER_SRC)
        for internal, route_name in DEPTH1_ENGINE_INTERNAL.items():
            with self.subTest(internal=internal, route=route_name):
                self.assertIn(internal, _depth1_only_seams(),
                              "exclusion is stale - the internal seam is gone")
                self.assertIn(route_name, depth0_seams,
                              "route-level twin is not a depth-0 seam")
                self.assertIn(route_name, parsed)
                self.assertIn(route_name, passed)
                self.assertNotIn(route_name, depth0_stranded)

    def test_engine_internal_exclusions_are_not_in_the_ledger(self):
        # The two lists must stay disjoint, or a name could be silently
        # excused twice and its removal from one would look harmless.
        self.assertFalse(set(DEPTH1_ENGINE_INTERNAL) & set(STRANDED_DEPTH1))

    def test_depth1_universe_is_engine_derived_not_server_derived(self):
        # Anti-circularity for the new tier, mirroring the depth-0 test.
        seams = _depth1_only_seams()
        self.assertTrue(seams, "depth-1 seam universe collapsed")
        self.assertTrue(
            set(seams) - _parsed_keys(SERVER_SRC),
            "depth-1 seam universe is a subset of what server.py parses",
        )


class StrandedSeamDefaultTypeAxisRM333(unittest.TestCase):
    """RM-333 - the DEFAULT-TYPE axis of the blind spot RM-207 named.

    RM-207 (above) recorded the NAME axis: a seam wired at the route level
    under a DIFFERENT PARAMETER NAME is invisible to a name-keyed checker.
    This is the same failure along a new axis - a seam under a DIFFERENT
    DEFAULT TYPE is invisible to a default-keyed checker. Both tiers keyed on
    ``p.default is False``, so ``apply_canonical_cast_rate_keys``
    (``bool | None = None`` on ``ult_rates.get_ult_casts_per_sec`` at
    ult_rates.py:167 and ``ult_rates.get_spell_casts_per_sec`` at
    ult_rates.py:205) was in NEITHER universe. Both ledgers stayed green while
    the seam was unreachable from every route:
    ``grep -c apply_canonical_cast_rate_keys server.py`` returns 0.

    ``None`` is a DEFAULT-OFF seam here, not a third state to be ignored: the
    kwarg documents itself as deferring to the module global
    ``ult_rates.APPLY_CANONICAL_CAST_RATE_KEYS``, which is ``False``. What
    ``None`` means in both surviving cases is "the caller did not decide",
    which is exactly the shape of a seam a route has to be able to set.
    """

    def test_rm333_seam_is_visible_to_the_checker(self):
        # RED at HEAD. The seam is in neither tier's universe, which is why
        # both equality ledgers below could be green while it was stranded.
        visible = (
            set(_engine_seams())
            | set(_depth1_only_seams())
            | set(_tristate_only_seams())
        )
        self.assertIn(
            "apply_canonical_cast_rate_keys",
            visible,
            "the cast-rate seam is invisible to both tiers - the checker keys "
            "on a default TYPE the seam does not use",
        )

    def test_rm333_seam_is_wired_or_ledgered_with_a_reason(self):
        # RED at HEAD. The acceptance: once visible, the seam must be either
        # parsed-and-passed by server.py or carry a written reason in a ledger.
        name = "apply_canonical_cast_rate_keys"
        wired = name in _parsed_keys(SERVER_SRC) and name in _passed_kwargs(SERVER_SRC)
        reason = (
            STRANDED_TODAY.get(name)
            or STRANDED_DEPTH1.get(name)
            or STRANDED_TRISTATE.get(name)
        )
        self.assertTrue(
            wired or (reason and reason.strip()),
            "cast-rate seam is neither wired into a route nor ledgered with a "
            "reason",
        )

    def test_rm333_ult_rates_is_in_the_entry_point_universe(self):
        # The seam's owners are reachable from the entry-point universe at
        # depth 1, and were BEFORE this row: the ONLY thing hiding the seam was
        # the default-type filter. They are deliberately NOT forced into
        # _route_facing_entry_points - server.py does not call them, so listing
        # them there would falsify that helper's contract AND drag ult_rates'
        # private helpers into depth 1 as a side effect.
        d1 = _depth1_functions()
        for fq in ("ult_rates.get_ult_casts_per_sec",
                   "ult_rates.get_spell_casts_per_sec"):
            with self.subTest(fn=fq):
                self.assertIn(fq, d1)
                self.assertNotIn(fq, _route_facing_entry_points())

    def test_rm333_predicate_admits_none_and_false_only(self):
        # The widening must not over-admit, and that is asserted on the
        # PREDICATE rather than on champion data. MEASURED: no prefixed
        # parameter in either universe defaults to True on every owner - all
        # five True-defaulting names also have a False-defaulting or a required
        # owner elsewhere - so a name-based "True is excluded" anchor would be
        # data-fragile and would assert the wrong thing.
        self.assertTrue(_is_seam_default(False))
        self.assertTrue(_is_seam_default(None))
        self.assertFalse(_is_seam_default(True), "DEFAULT-ON is not a seam")
        self.assertFalse(_is_seam_default(0), "is False, not == False")
        self.assertFalse(_is_seam_default(0.0), "is False, not == False")
        self.assertFalse(
            _is_seam_default(inspect.Parameter.empty),
            "a required parameter cannot be stranded - every caller passes it",
        )

    def test_rm333_default_on_parameter_stays_out_of_every_tier(self):
        # The data anchor that IS sound: apply_egg_resist's only two defaults
        # anywhere are True and no-default, so it must stay absent from all
        # three seam universes after the widening.
        self.assertNotIn("apply_egg_resist", _engine_seams())
        self.assertNotIn("apply_egg_resist", _depth1_only_seams())
        self.assertNotIn("apply_egg_resist", _tristate_only_seams())

    def test_rm333_tristate_stranded_set_equals_the_tristate_ledger(self):
        # The new tier's equality, mirroring both tiers above. A newly-revealed
        # None-defaulting seam goes RED here; wiring this one goes RED until it
        # is deleted from the ledger, so this tier can only ever shrink.
        self.assertEqual(
            sorted(stranded_tristate_seams(SERVER_SRC)),
            sorted(STRANDED_TRISTATE),
            "tri-state stranded seams drifted - wire the seam into a route, or "
            "add it to STRANDED_TRISTATE with a reason",
        )

    def test_rm333_every_tristate_ledger_row_carries_a_real_reason(self):
        # An exemption list whose reasons are placeholders is an exemption list
        # that stops meaning anything. Each row must cite something.
        for name, reason in STRANDED_TRISTATE.items():
            with self.subTest(seam=name):
                self.assertGreater(len(reason), 80, "reason is a placeholder")
                self.assertNotIn("TODO", reason)
                self.assertIn(".py:", reason, "reason cites no source location")

    def test_rm333_the_three_tiers_are_disjoint(self):
        # No seam may be measured - or excused - by two tiers at once, or
        # deleting it from one ledger would look harmless.
        d0, d1, tri = _engine_seams(), _depth1_only_seams(), _tristate_only_seams()
        self.assertFalse(set(d0) & set(d1))
        self.assertFalse(set(d0) & set(tri))
        self.assertFalse(set(d1) & set(tri))
        self.assertFalse(set(STRANDED_TODAY) & set(STRANDED_TRISTATE))
        self.assertFalse(set(STRANDED_DEPTH1) & set(STRANDED_TRISTATE))

    def test_rm333_left_both_existing_ratchets_byte_exact(self):
        # The reason the tri-state residue got its own tier. Both existing
        # ledgers must be exactly what they were before the widening, so
        # neither ratchet is disturbed and no sibling guard that pins them
        # (test_cc_floor_route_seam_rm201.py pins STRANDED_DEPTH1 == {} from
        # another file) is broken by this row.
        self.assertEqual(sorted(stranded_seams(SERVER_SRC)), sorted(STRANDED_TODAY))
        self.assertEqual(stranded_seams_depth1(SERVER_SRC), {})
        self.assertEqual(STRANDED_DEPTH1, {})

    def test_rm333_tristate_checker_is_not_vacuous(self):
        # Non-vacuity, the same bar the two tiers above are held to: give
        # server.py a body key AND a forward for the seam, and the checker must
        # clear it. A tier that can never go empty is as dead as one that can
        # never go red.
        wired_src = SERVER_SRC + textwrap.dedent(
            """

            def _rm333_probe(body):
                apply_canonical_cast_rate_keys = _opt_bool(
                    body, "apply_canonical_cast_rate_keys", False
                )
                return get_spell_casts_per_sec(
                    "Ahri", "R", "SR",
                    apply_canonical_cast_rate_keys=apply_canonical_cast_rate_keys,
                )
            """
        )
        self.assertIn("apply_canonical_cast_rate_keys", _parsed_keys(wired_src))
        self.assertIn("apply_canonical_cast_rate_keys", _passed_kwargs(wired_src))
        self.assertEqual(stranded_tristate_seams(wired_src), {})

    def test_rm333_tristate_universe_is_engine_derived_not_server_derived(self):
        # Anti-circularity for the new tier, mirroring both tiers above.
        seams = _tristate_only_seams()
        self.assertTrue(seams, "tri-state seam universe collapsed")
        self.assertTrue(
            set(seams) - _parsed_keys(SERVER_SRC),
            "tri-state seam universe is a subset of what server.py parses",
        )

    def test_rm333_widening_added_no_new_depth0_names(self):
        # Measured, and stated because a near-zero result deserves pinning
        # rather than prose. apply_build_tenacity is the ONLY None-defaulting
        # prefixed parameter on the 32 depth-0 entry points, and it was already
        # in the depth-0 universe through ehp.compute_ehp / hybrid.compute_hybrid
        # (bool = False). The widening therefore gives it two extra OWNERS
        # (ehp.rank_items_by_ehp, hybrid.rank_items_by_hybrid), not membership,
        # so STRANDED_TODAY's ratchet is untouched by construction.
        self.assertIn("apply_build_tenacity", _engine_seams())
        owners = _engine_seams()["apply_build_tenacity"]
        self.assertIn("ehp.rank_items_by_ehp", owners)
        self.assertIn("hybrid.rank_items_by_hybrid", owners)
        self.assertIn("apply_build_tenacity", _parsed_keys(SERVER_SRC))
        self.assertIn("apply_build_tenacity", _passed_kwargs(SERVER_SRC))
        self.assertEqual(sorted(stranded_seams(SERVER_SRC)), sorted(STRANDED_TODAY))

    def test_rm333_seam_stays_default_off(self):
        # This row is guard widening ONLY. Wiring the seam is a separate Tier-2
        # decision: ult_rates' own docstring records the correction is not
        # byte-identical (13 of 21 champions reorder on the ability scorer, 3 of
        # 21 on carry), so a default flip would turn the measured-rate
        # assertions in test_cast_rate_canonical_keys.py into tautologies.
        from .. import ult_rates
        self.assertIs(ult_rates.APPLY_CANONICAL_CAST_RATE_KEYS, False)
        sig = inspect.signature(ult_rates.get_spell_casts_per_sec)
        self.assertIsNone(sig.parameters["apply_canonical_cast_rate_keys"].default)


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
