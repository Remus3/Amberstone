"""RM-870 - live /api/ds-preview rows carry ``unique_passive_key``.

The build planner (``core/build_planner/planner.py`` beam expansion,
``_resolve_forced`` and ``_to_planned``; ``core/build_planner/scoring.py``
``_seed_family``) inherits the no-double-unique rule from each seed row's
``unique_passive_key``. The live seed is ``/api/build-plan`` composing the
EXISTING ``/api/ds-preview`` handler in-process
(``dashboard/routes_build_plan.py`` ``_make_route_seed_fn``). That handler
projected the engine key under ``family`` only (BATCH A display field for
``web/js/panels/active_match.js``), so on the live route every ranked row
looked family-less and the planner could plan two items that share one
unique passive - the "Double Last Whisper" class, reached through a
projection rather than through engine data.

These tests run the REAL route row builder with only the DS boundary
stubbed (``core.daemon_slayer_client.rank_for_primary_archetype``), so no
live :8860 and no live game are needed. The shared group is DERIVED at
runtime from the engine's own ``ITEM_EFFECTS`` (no family literal anywhere -
the rule is engine-authoritative, CLAUDE.md Settled).

ASCII only - use " - " for a clause break (repo hard rule).
"""
from __future__ import annotations

import json

import pytest

import core.daemon_slayer_client as dsc
import dashboard.routes_build_plan as rbp
import dashboard.routes_state as rs
from agents.daemon_slayer.effects import ITEM_EFFECTS
from core.build_planner.planner import plan_build
from core.build_planner.replan import ReplanLoop


def _engine_shared_group() -> tuple[str, list[str]]:
    """One engine unique-passive group with >= 2 SR (4-digit) members.

    Read from ITEM_EFFECTS at runtime so the test never names a family and a
    renamed or added group is covered automatically.
    """
    groups: dict[str, list[str]] = {}
    for iid, eff in ITEM_EFFECTS.items():
        key = str(getattr(eff, "unique_passive_key", "") or "")
        sid = str(iid)
        if key and sid.isdigit() and len(sid) == 4:
            groups.setdefault(key, []).append(sid)
    for key in sorted(groups):
        members = sorted(groups[key])
        if len(members) >= 2:
            return key, members[:2]
    pytest.fail("engine defines no unique-passive group with 2 SR members")


_GROUP, (_FAM_A, _FAM_B) = _engine_shared_group()


def _engine_key(iid: str) -> str:
    eff = ITEM_EFFECTS.get(iid)
    return str(getattr(eff, "unique_passive_key", "") or "") if eff else ""


def _filler_ids(n: int) -> list[str]:
    """SR ids the engine gives NO unique-passive group (planner fillers)."""
    out: list[str] = []
    for iid in sorted(str(i) for i in ITEM_EFFECTS):
        if (iid.isdigit() and len(iid) == 4 and not _engine_key(iid)
                and iid not in (_FAM_A, _FAM_B)):
            out.append(iid)
        if len(out) == n:
            return out
    pytest.fail("engine has too few family-less SR items for fillers")


_FILL = _filler_ids(3)

# What the DS dispatcher returns: two NOT-owned candidates that share one
# engine unique-passive group rank 2nd and 3rd, high enough that a
# family-blind beam keeps both. Keys come from the engine, never typed.
_ENGINE_ROWS = [
    {"item_id": _FILL[0], "item_name": "Filler A", "delta": 120.0,
     "gold": 3400, "unique_passive_key": _engine_key(_FILL[0])},
    {"item_id": _FAM_A, "item_name": "Group A", "delta": 110.0,
     "gold": 3000, "unique_passive_key": _engine_key(_FAM_A)},
    {"item_id": _FAM_B, "item_name": "Group B", "delta": 105.0,
     "gold": 3000, "unique_passive_key": _engine_key(_FAM_B)},
    {"item_id": _FILL[1], "item_name": "Filler C", "delta": 60.0,
     "gold": 2600, "unique_passive_key": _engine_key(_FILL[1])},
    {"item_id": _FILL[2], "item_name": "Filler D", "delta": 50.0,
     "gold": 2600, "unique_passive_key": _engine_key(_FILL[2])},
]


class _Handler:
    """Captures ``_send`` - the handler surface the routes touch."""

    def __init__(self) -> None:
        self.status = 0
        self.body = b""

    def _send(self, status, body, content_type) -> None:
        self.status = status
        self.body = body

    def json(self) -> dict:
        return json.loads(self.body.decode())


@pytest.fixture
def live_route(monkeypatch):
    """Stub ONLY the DS boundary + live-state readers; keep the row builder."""
    monkeypatch.setenv("RC_CAPGAP_SURFACE", "0")
    monkeypatch.setattr(
        dsc, "rank_for_primary_archetype",
        lambda **kw: {"ok": True, "scorer": "dps", "fell_back": False,
                      "ranked": [dict(r) for r in _ENGINE_ROWS]})

    def _bo_down(h, payload):
        h._send(503, b"{}", "application/json")

    monkeypatch.setattr(rs, "_serve_build_order_post", _bo_down)
    monkeypatch.setattr(
        rs, "_resolve_ds_target_stats",
        lambda payload, mode, level: {
            "target_armor": 80.0, "target_mr": 50.0,
            "target_max_hp": 2000.0, "target_bonus_hp": 0.0})
    monkeypatch.setattr(rs, "_resolve_enemy_champions", lambda payload: [])
    return rbp._make_route_seed_fn(level=11, archetype="carry", enemies=[],
                                   target_overrides={})


def test_engine_group_precondition():
    # The fixture is meaningful only if the two picked ids truly share an
    # engine group and the fillers carry none.
    assert _engine_key(_FAM_A) == _engine_key(_FAM_B) == _GROUP != ""
    assert all(_engine_key(i) == "" for i in _FILL)


def test_route_rows_carry_engine_unique_passive_key(live_route):
    h = _Handler()
    rs._serve_ds_preview_post(h, {"champion": "Jhin", "mode": "SR",
                                  "level": 11, "archetype": "carry"})
    assert h.status == 200
    ranked = h.json()["ranked"]
    by_id = {r["item_id"]: r for r in ranked}
    assert set(by_id) == {r["item_id"] for r in _ENGINE_ROWS}
    for src in _ENGINE_ROWS:
        row = by_id[src["item_id"]]
        assert "unique_passive_key" in row, sorted(row)
        assert row["unique_passive_key"] == src["unique_passive_key"]
        # BATCH A display field stays (web/js/panels/active_match.js reads it).
        assert row["family"] == src["unique_passive_key"]


def test_route_row_without_engine_key_emits_empty_string(monkeypatch,
                                                         live_route):
    # A row the engine sent with no key (or None) projects to "" - the
    # planner treats "" as family-less, never as a shared group.
    monkeypatch.setattr(
        dsc, "rank_for_primary_archetype",
        lambda **kw: {"ok": True, "scorer": "dps", "ranked": [
            {"item_id": _FILL[0], "delta": 1.0, "gold": 1},
            {"item_id": _FILL[1], "delta": 1.0, "gold": 1,
             "unique_passive_key": None}]})
    h = _Handler()
    rs._serve_ds_preview_post(h, {"champion": "Jhin", "archetype": "carry"})
    assert h.status == 200
    assert [r["unique_passive_key"] for r in h.json()["ranked"]] == ["", ""]


def _both(ids) -> bool:
    ids = set(ids)
    return _FAM_A in ids and _FAM_B in ids


def test_plan_build_on_live_route_never_doubles_a_unique(live_route):
    plan = plan_build("Jhin", seed_fn=live_route, depth=3)
    assert plan.items, plan.notes
    assert not _both(pi.item_id for pi in plan.items), \
        [pi.item_id for pi in plan.items]
    for cand in plan.beam:
        assert not _both(pi.item_id for pi in cand.items), \
            [pi.item_id for pi in cand.items]


def test_replan_tick_on_live_route_never_doubles_a_unique(live_route):
    res = ReplanLoop().tick(champion="Jhin", owned_item_ids=[],
                            seed_fn=live_route, depth=3)
    assert res.plan_tail
    assert not _both(res.plan_tail), res.plan_tail


def test_forced_pair_on_live_route_keeps_one(live_route):
    # Two locked ids in one engine group: the planner keeps the first and
    # notes the drop, exactly as it does on an engine-keyed seed.
    plan = plan_build("Jhin", seed_fn=live_route, depth=3,
                      forced_item_ids=[_FAM_A, _FAM_B])
    ids = [pi.item_id for pi in plan.items]
    assert _FAM_A in ids and _FAM_B not in ids, (ids, plan.notes)
    assert any(_FAM_B in n and _GROUP in n for n in plan.notes), plan.notes


def test_build_plan_route_end_to_end_never_doubles_a_unique(live_route,
                                                            monkeypatch):
    # Full /api/build-plan handler over the real seed boundary.
    monkeypatch.setattr(rbp, "_seed_fn_factory", rbp._make_route_seed_fn)
    h = _Handler()
    rbp._serve_build_plan(h, {"champion": "Jhin", "items": [], "mode": "SR",
                              "level": 11, "archetype": "carry"})
    assert h.status == 200
    env = h.json()
    ids = [r.get("item_id") for r in env.get("live", [])]
    assert env.get("ok") is True and ids, env
    assert not _both(ids), ids
