"""RM-875: the ``apply_mode_modifiers`` seam through the archetype dispatcher.

WHY
    The live Arena coach could never arm the RM-172 ADDEND lane (the ``ar``
    growth addends, 45 champions). ``coaches/arena_coach.py`` reaches DS only
    through ``coach_integration.archetype_dispatch.dispatch_for_coach`` ->
    ``core.daemon_slayer_client.rank_for_primary_archetype``, and before RM-875
    ``inspect.signature`` gave NEITHER an ``apply_mode_modifiers`` parameter,
    while every per-scorer client function those branches call already carried
    it (Gate C, ``tests/test_rm172_mode_modifier_seam_characterization.py``).

WHAT IS PINNED HERE (each class failed before the RM-875 change)
    1. Signatures: both dispatchers take the kwarg, keyword-only, default
       False, appended LAST.
    2. Flag OFF is BYTE-IDENTICAL on the wire: the request body for a Quinn
       ARENA dispatch through every archetype branch equals the body captured
       at HEAD a21813b73 BEFORE the seam existed (``_HEAD_WIRE``), and an
       explicit False equals an omitted kwarg byte for byte.
    3. Flag ON sends the key on every branch, and the ON body is the OFF body
       plus exactly that one key (nothing else moves). The ranking the
       dispatcher returns is the order the flag-ON response carried.
    4. The ordered-build planner gets the seam too (SLICE A defect 2 shape).
    5. Arena coach: DEFAULT-OFF env flag ``RC_ARENA_MODE_MODIFIERS`` read once
       at import; OFF sends no key, ON sends it.
    6. TRANSPORT (CLAUDE.md: "check the TRANSPORT, not just the flag"): every
       DS route a dispatcher branch can POST to parses AND forwards the key
       (AST over ``agents/daemon_slayer/server.py``), and the flag-ON body the
       dispatcher builds for Quinn changes the real in-process ``/rank``
       response, looked up through ``_POST_ROUTES`` - the same table the HTTP
       handler dispatches on.

The live default flip is NOT here: it stays gated row G5-05 in
``docs/LIVE_GAME_GATED_SYNC.md`` (CHECK A stat half, CHECK B coach half).
"""
from __future__ import annotations

import ast
import inspect
import json
import os
import subprocess
import sys
from pathlib import Path
from unittest import mock

import pytest

from coach_integration import archetype_dispatch as ad
from coach_integration.enemy_stats import EnemyStats
from core import daemon_slayer_client as dsc

REPO_ROOT = Path(__file__).resolve().parents[1]
FLAG = "apply_mode_modifiers"
CHAMP = "Quinn"  # the row's named case: an `ar` champion (G5-05 compute half)
ARCHETYPES = ("carry", "tank", "bruiser", "mage", "assassin", "enchanter", "onhit")

# Wire bytes (``json.dumps(body).encode("utf-8")``, exactly what ``_post_json``
# sends) for ``_dispatch(arch)`` below, captured at HEAD a21813b73 BEFORE the
# RM-875 seam existed. Every value is a caller input or a client constant
# (carry ``top`` 40 = CARRY_COHERENCE_WINDOW), except onhit's
# ``ap_ad_coherence`` (champion data, normalized in ``_wire_off``). If a later,
# deliberate change to a branch's body shape breaks this, re-capture it in that
# change; never re-capture it to make an RM-875 diff pass.
_HEAD_WIRE = {
    "assassin": ("/rank-assassin", (
        '{"champion": "Quinn", "level": 9, "items": ["3006"], "mode": "ARENA", '
        '"target_armor": 80.0, "target_mr": 60.0, "target_max_hp": 2500.0, '
        '"target_bonus_hp": 300.0, "target_current_hp_pct": 1.0, "top": 5, '
        '"sort": "delta", "block_strategy": "first", "filter_shared_uniques": true, '
        '"augments": ["ItsCritical"], "prefer_kit_axis_by_win": true}')),
    "bruiser": ("/rank-bruiser", (
        '{"champion": "Quinn", "level": 9, "items": ["3006"], "mode": "ARENA", '
        '"target_armor": 80.0, "target_mr": 60.0, "target_max_hp": 2500.0, '
        '"target_bonus_hp": 300.0, "enemy_ad_share": 0.6, "enemy_ap_share": 0.4, '
        '"top": 5, "sort": "delta", "filter_shared_uniques": true, '
        '"augments": ["ItsCritical"]}')),
    "carry": ("/rank", (
        '{"champion": "Quinn", "level": 9, "items": ["3006"], "mode": "ARENA", '
        '"target_armor": 80.0, "target_mr": 60.0, "target_max_hp": 2500.0, '
        '"target_bonus_hp": 300.0, "top": 40, "sort": "delta", '
        '"filter_shared_uniques": true, "augments": ["ItsCritical"], '
        '"prefer_kit_axis_by_win": true}')),
    "enchanter": ("/rank-enchanter", (
        '{"champion": "Quinn", "level": 9, "items": ["3006"], "mode": "ARENA", '
        '"top": 5, "sort": "delta", "enchanter_only": true, '
        '"filter_shared_uniques": true, "augments": ["ItsCritical"], '
        '"caster_missing_hp_pct": 0.30000000000000004}')),
    "mage": ("/rank-mage", (
        '{"champion": "Quinn", "level": 9, "items": ["3006"], "mode": "ARENA", '
        '"target_armor": 80.0, "target_mr": 60.0, "target_max_hp": 2500.0, '
        '"target_bonus_hp": 300.0, "target_current_hp_pct": 1.0, "top": 5, '
        '"sort": "delta", "block_strategy": "first", "filter_shared_uniques": true, '
        '"augments": ["ItsCritical"]}')),
    "onhit": ("/rank-onhit", (
        '{"champion": "Quinn", "level": 9, "items": ["3006"], "mode": "ARENA", '
        '"target_armor": 80.0, "target_mr": 60.0, "target_max_hp": 2500.0, '
        '"target_bonus_hp": 300.0, "top": 5, "sort": "delta", '
        '"filter_shared_uniques": true, "apply_passive_damage": true, '
        '"ap_ad_coherence": 0.0, "augments": ["ItsCritical"]}')),
    "tank": ("/rank-tank", (
        '{"champion": "Quinn", "level": 9, "items": ["3006"], "mode": "ARENA", '
        '"enemy_ad_share": 0.6, "enemy_ap_share": 0.4, "top": 5, "sort": "delta", '
        '"filter_shared_uniques": true, "augments": ["ItsCritical"]}')),
}


def _enemy() -> EnemyStats:
    return EnemyStats(armor=80.0, mr=60.0, max_hp=2500.0, bonus_hp=300.0,
                      ad_share=0.6, ap_share=0.4)


def _dispatch(arch: str, response=None, **extra):
    """Run the REAL dispatcher + client for ``arch`` with ``_post_json`` stubbed.

    Returns ``(result, calls)`` where ``calls`` is ``[(path, body), ...]``.
    ``response`` maps a captured body to the stub's JSON reply (default: an
    engine-up empty ranking).
    """
    calls: list = []

    def _fake_post(path, body, timeout=dsc.DEFAULT_TIMEOUT):
        calls.append((path, dict(body)))
        return response(body) if response else {"ranked": []}

    with mock.patch.object(dsc, "_post_json", _fake_post), mock.patch(
        "core.archetype_picks.get_archetype_for",
        lambda *_a, **_k: {"primary": arch},
    ):
        result = ad.dispatch_for_coach(
            CHAMP, mode_engine="ARENA", level=9, item_ids=["3006"],
            enemy_stats=_enemy(), augments=["ItsCritical"], top=5,
            caster_hp=700.0, caster_hp_max=1000.0, **extra,
        )
    return result, calls


def _wire(body: dict) -> bytes:
    return json.dumps(body).encode("utf-8")


def _wire_off(arch: str, body: dict) -> bytes:
    if arch == "onhit":  # champion-data value, not a seam (see _HEAD_WIRE)
        body = {k: (0.0 if k == "ap_ad_coherence" else v) for k, v in body.items()}
    return _wire(body)


# --------------------------------------------------------------------------
# 1. Signatures.
# --------------------------------------------------------------------------

@pytest.mark.parametrize("fn", [dsc.rank_for_primary_archetype, ad.dispatch_for_coach],
                         ids=["rank_for_primary_archetype", "dispatch_for_coach"])
def test_dispatcher_takes_the_flag_keyword_only_default_off_appended_last(fn):
    params = inspect.signature(fn).parameters
    assert FLAG in params, f"{fn.__name__} has no {FLAG} parameter (RM-875 seam)"
    p = params[FLAG]
    assert p.default is False
    assert p.kind is inspect.Parameter.KEYWORD_ONLY
    assert list(params)[-1] == FLAG, "repo convention: a new seam is appended LAST"


# --------------------------------------------------------------------------
# 2. Flag OFF is byte-identical on the wire.
# --------------------------------------------------------------------------

@pytest.mark.parametrize("arch", ARCHETYPES)
def test_flag_off_wire_bytes_equal_the_pre_seam_head_capture(arch):
    _, omitted = _dispatch(arch)
    _, explicit = _dispatch(arch, apply_mode_modifiers=False)
    assert len(omitted) == 1 and len(explicit) == 1
    head_path, head_bytes = _HEAD_WIRE[arch]
    assert omitted[0][0] == head_path
    assert FLAG not in omitted[0][1]
    assert _wire_off(arch, omitted[0][1]) == head_bytes.encode("utf-8"), (
        f"{arch}: the flagless request is no longer byte-identical to HEAD"
    )
    assert explicit[0][0] == head_path
    assert _wire(explicit[0][1]) == _wire(omitted[0][1]), (
        f"{arch}: apply_mode_modifiers=False changed the request bytes"
    )


@pytest.mark.parametrize("arch", ARCHETYPES)
def test_client_dispatcher_explicit_false_equals_omitted(arch):
    """Same property one layer down, at ``rank_for_primary_archetype``."""
    bodies = []
    for extra in ({}, {FLAG: False}):
        calls: list = []

        def _fake_post(path, body, timeout=dsc.DEFAULT_TIMEOUT, _c=calls):
            _c.append((path, dict(body)))
            return {"ranked": []}

        with mock.patch.object(dsc, "_post_json", _fake_post):
            dsc.rank_for_primary_archetype(
                CHAMP, arch, level=9, item_ids=["3006"], mode="ARENA", **extra)
        assert len(calls) == 1
        bodies.append(calls[0])
    assert bodies[0][0] == bodies[1][0]
    assert FLAG not in bodies[0][1]
    assert _wire(bodies[0][1]) == _wire(bodies[1][1])


# --------------------------------------------------------------------------
# 3. Flag ON sends the key, and only the key.
# --------------------------------------------------------------------------

@pytest.mark.parametrize("arch", ARCHETYPES)
def test_flag_on_sends_the_key_and_changes_nothing_else(arch):
    _, off = _dispatch(arch)
    _, on = _dispatch(arch, apply_mode_modifiers=True)
    assert len(on) == 1
    assert on[0][0] == off[0][0], f"{arch}: the flag changed the route"
    assert on[0][1].get(FLAG) is True, (
        f"{arch}: dispatch_for_coach accepted {FLAG}=True but the "
        f"{on[0][0]} body does not carry it (settable-but-inert)"
    )
    stripped = {k: v for k, v in on[0][1].items() if k != FLAG}
    assert _wire(stripped) == _wire(off[0][1]), (
        f"{arch}: the ON body differs from the OFF body by more than the key"
    )


_ITEMS = (("3031", "Infinity Edge", 3400), ("6672", "Kraken Slayer", 3100),
          ("3046", "Phantom Dancer", 2650))


def _ranked(order) -> dict:
    deltas = (300.0, 200.0, 100.0)
    rows = []
    for (iid, name, gold), delta in zip(order, deltas):
        rows.append({"item_id": iid, "item_name": name, "delta_dps": delta,
                     "delta": delta, "gold": gold})
    return {"ranked": rows}


def test_flag_on_ranking_returned_is_the_flag_on_response_order():
    """Quinn carry: the stub answers ON and OFF with DIFFERENT orders; the
    dispatcher must hand the coach the order the flag-ON response carried."""
    on_order = (_ITEMS[1], _ITEMS[0], _ITEMS[2])
    off_order = _ITEMS

    def _reply(body):
        return _ranked(on_order if body.get(FLAG) else off_order)

    res_on, calls_on = _dispatch("carry", response=_reply, apply_mode_modifiers=True)
    res_off, _ = _dispatch("carry", response=_reply)
    assert calls_on[0][1].get(FLAG) is True
    assert res_on is not None and res_off is not None
    assert [r["item_id"] for r in res_on.rows] == [i[0] for i in on_order]
    assert [r["id"] for r in res_on.display_rows] == [i[0] for i in on_order]
    assert [r["item_id"] for r in res_off.rows] == [i[0] for i in off_order]


# --------------------------------------------------------------------------
# 4. The ordered-build planner receives the same seam.
# --------------------------------------------------------------------------

def test_with_build_order_planner_gets_the_seam_only_when_on():
    seen: list = []

    def _fake_plan(*_a, **kw):
        seen.append(kw.get("rank_kwargs"))
        return None

    with mock.patch("core.build_order.plan_build_order", _fake_plan):
        _dispatch("carry", with_build_order=True, apply_mode_modifiers=True)
        _dispatch("carry", with_build_order=True)
    assert len(seen) == 2
    assert (seen[0] or {}).get(FLAG) is True
    assert FLAG not in (seen[1] or {})


# --------------------------------------------------------------------------
# 5. Arena coach: DEFAULT-OFF env flag, read once at import.
# --------------------------------------------------------------------------

def _import_flag(env_value):
    env = {k: v for k, v in os.environ.items() if k != "RC_ARENA_MODE_MODIFIERS"}
    if env_value is not None:
        env["RC_ARENA_MODE_MODIFIERS"] = env_value
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    out = subprocess.run(
        [sys.executable, "-c",
         "import coaches.arena_coach as m; print(repr(m._ARENA_MODE_MODIFIERS))"],
        cwd=str(REPO_ROOT), env=env, capture_output=True, text=True,
        timeout=120, creationflags=flags,
    )
    assert out.returncode == 0, out.stderr[-2000:]
    return out.stdout.strip().splitlines()[-1]


@pytest.mark.parametrize("env_value,expected", [
    (None, "False"), ("0", "False"), ("true", "False"), ("1", "True"),
])
def test_arena_flag_is_default_off_and_strictly_one(env_value, expected):
    assert _import_flag(env_value) == expected


class _StubClient:
    """The DS block runs before the model call; failing the model call stops
    the tick after the capture (``@safe_coach_output`` absorbs it)."""

    class messages:  # noqa: N801 - mirrors the anthropic client attribute
        @staticmethod
        def create(*_a, **_k):
            raise RuntimeError("no model call in this test")


def _arena_tick(flag: bool, response=None):
    import coaches.arena_coach as arena_mod

    calls: list = []

    def _fake_post(path, body, timeout=dsc.DEFAULT_TIMEOUT):
        calls.append((path, dict(body)))
        return response(body) if response else {"ranked": []}

    coach = object.__new__(arena_mod.Coach)
    coach._client = _StubClient()
    coach._vision_state = {}
    coach._event_round_count = 4
    state = {
        "champion": CHAMP, "level": 9,
        "items": ["Berserker's Greaves", "Kraken Slayer"],
        "enemy_comp": ["Ashe", "Annie"], "game_seconds": 600,
        "teams": [{"name": "You", "is_you": True, "hp_pct": 90}],
        "augments": ["ItsCritical"], "hp": 850, "hp_max": 1000,
    }
    with mock.patch.object(arena_mod, "_ARENA_MODE_MODIFIERS", flag), \
            mock.patch.object(dsc, "_post_json", _fake_post), \
            mock.patch("core.archetype_picks.get_archetype_for",
                       lambda *_a, **_k: {"primary": "carry"}):
        coach._run_coach(state)
    assert calls, "the arena tick never reached the DS request (harness broke)"
    return calls


def test_arena_coach_flag_off_sends_no_key_and_on_sends_it():
    off = _arena_tick(False)
    on = _arena_tick(True)
    assert off[0][0] == on[0][0] == "/rank"
    assert FLAG not in off[0][1]
    assert on[0][1].get(FLAG) is True
    stripped = {k: v for k, v in on[0][1].items() if k != FLAG}
    assert _wire(stripped) == _wire(off[0][1])


def test_arena_coach_passes_the_module_flag_to_the_dispatcher():
    """AST: the Arena DS call site forwards the module constant, so the flag
    is read once at import and never re-read per tick."""
    src = (REPO_ROOT / "coaches/arena_coach.py").read_text(encoding="utf-8")
    hits = []
    for node in ast.walk(ast.parse(src)):
        if not isinstance(node, ast.Call):
            continue
        fn = node.func
        name = fn.id if isinstance(fn, ast.Name) else getattr(fn, "attr", "")
        if name != "_ds_dispatch_for_coach":
            continue
        for kw in node.keywords:
            if kw.arg == FLAG:
                hits.append(isinstance(kw.value, ast.Name)
                            and kw.value.id == "_ARENA_MODE_MODIFIERS")
    assert hits == [True], hits


# --------------------------------------------------------------------------
# 6. TRANSPORT: the DS routes parse the key; the ON body changes /rank.
# --------------------------------------------------------------------------

def _route_reads_and_forwards() -> dict:
    """Per ``_route_*``: is the flag read off the body (string-literal call
    arg, e.g. ``_opt_bool(body, "apply_mode_modifiers", False)``) AND passed on
    as a call keyword? Prose in a docstring satisfies neither."""
    src = (REPO_ROOT / "agents/daemon_slayer/server.py").read_text(encoding="utf-8")
    out = {}
    for node in ast.walk(ast.parse(src)):
        if not (isinstance(node, ast.FunctionDef) and node.name.startswith("_route_")):
            continue
        reads = forwards = False
        for sub in ast.walk(node):
            if isinstance(sub, ast.Call):
                reads |= any(isinstance(a, ast.Constant) and a.value == FLAG
                             for a in sub.args)
                forwards |= any(k.arg == FLAG for k in sub.keywords)
        out[node.name] = reads and forwards
    return out


def test_every_route_a_dispatcher_branch_posts_to_parses_and_forwards_the_key():
    from agents.daemon_slayer import server as ds_server

    parsing = _route_reads_and_forwards()
    paths = set()
    for arch in ARCHETYPES:
        _, calls = _dispatch(arch, apply_mode_modifiers=True)
        paths.update(p for p, _ in calls)
    assert paths == {"/rank", "/rank-tank", "/rank-bruiser", "/rank-mage",
                     "/rank-assassin", "/rank-enchanter", "/rank-onhit"}
    for path in sorted(paths):
        handler = ds_server._POST_ROUTES[path]
        assert parsing.get(handler.__name__), (
            f"{path} ({handler.__name__}) does not parse+forward {FLAG}: the "
            "RC seam would be INERT on this branch"
        )


def test_flag_on_body_changes_the_real_rank_route_response_for_quinn():
    """Client body -> the real in-process route -> a DIFFERENT ranking."""
    from agents.daemon_slayer import server as ds_server
    from agents.daemon_slayer.data_loader import DataSnapshot

    snap = DataSnapshot.load()
    assert snap.mode_modifier(CHAMP, "ARENA"), f"{CHAMP} lost its ARENA `ar` block"
    ds_server._CACHE.set(snap)
    _, off = _dispatch("carry")
    _, on = _dispatch("carry", apply_mode_modifiers=True)
    handler = ds_server._POST_ROUTES[on[0][0]]
    a = json.dumps(handler(off[0][1]), sort_keys=True, default=str)
    b = json.dumps(handler(on[0][1]), sort_keys=True, default=str)
    assert a != b, (
        "the /rank response is identical with the flag ON - the wire carries "
        "the key but the engine does not act on it"
    )
