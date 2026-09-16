# arch: RM-414 client-supplied JSON flag truthiness tests across five route sites | section=test | frozen=no
"""RM-414: route handlers read client-supplied JSON flags by bare truthiness.

A JSON body `{"disabled": "false"}` carries the non-empty string "false",
which Python reads as True, so each of these routes took the ON path for a
body that said OFF. RM-296d fixed the same defect on `/api/loadout/apply`;
this file pins the SAME rule (`dashboard/_json_flags.py`) at the five sibling
sites the RM-296d sweep filed:

  1. /api/sr-draft/apply   push_runes / push_items / push_summoners (default ON)
  2. /api/ds-preview       the default-OFF boolean seam flags
  3. /api/coach/toggle     disabled (default OFF) - PERSISTED to disk
  4. /api/cs-archetype-pick clear (default OFF) - deletes a saved pick
  5. /api/build-plan       reset_overrides (default OFF)

Contract, identical at every site:
  absent          -> that route's existing default (unchanged)
  on spellings    -> ON   (True, 1, "true", "1")
  off spellings   -> OFF  (False, 0, "false", "0", "")
  ambiguous       -> HTTP 400 naming the field, and NO side effect
                     (JSON null, "maybe", 2)

Harness: every test drives the real route handler with a stub `_send`
handler, the pattern of `tests/test_routes_loadout_lane8_cycle38.py`. All
persistence is redirected under pytest's tmp_path; nothing here writes the
real `config/coach_settings.json` or `data/cs_archetype_picks.json`.
"""
from __future__ import annotations

import json
import sys
import types
from unittest import mock

import pytest

_ABSENT = object()

_ON = [True, 1, "true", "1"]
_OFF = [False, 0, "false", "0", ""]
_AMBIGUOUS = [None, "maybe", 2]


def _cases(default_on: bool):
    """(value, expected) rows; expected is True / False / 'reject'."""
    rows = [(v, True) for v in _ON] + [(v, False) for v in _OFF]
    rows.append((_ABSENT, default_on))
    rows += [(v, "reject") for v in _AMBIGUOUS]
    return rows


def _ids(rows):
    return ["absent" if v is _ABSENT else f"{type(v).__name__}:{v!r}"
            for v, _ in rows]


class _Handler:
    def __init__(self) -> None:
        self.sent: tuple | None = None

    def _send(self, status: int, body: bytes, ctype: str) -> None:
        self.sent = (status, body, ctype)

    @property
    def status(self) -> int:
        assert self.sent is not None, "handler returned without sending"
        return self.sent[0]

    def json(self) -> dict:
        assert self.sent is not None, "handler returned without sending"
        return json.loads(self.sent[1].decode("utf-8"))


def _with(payload: dict, key: str, value) -> dict:
    out = dict(payload)
    if value is not _ABSENT:
        out[key] = value
    return out


# ============================================================ 1. sr-draft
_SR_PUSH_CMD = {
    "push_runes": "apply_runes",
    "push_items": "apply_item_set",
    "push_summoners": "set_summoners",
}
_SR_ROWS = _cases(default_on=True)


def _sr_apply(monkeypatch, payload):
    from dashboard import routes_sr_draft

    stub = types.ModuleType("web_dashboard")
    stub._VISION_TOKEN = "test-token"
    monkeypatch.setitem(sys.modules, "web_dashboard", stub)
    sent_cmds: list[str] = []

    class _Resp:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return b'{"ok":true}'

    def _urlopen(req, timeout=None):
        sent_cmds.append(json.loads(req.data.decode())["cmd"])
        return _Resp()

    h = _Handler()
    with mock.patch("urllib.request.urlopen", _urlopen):
        routes_sr_draft._serve_sr_draft_apply_post(h, payload)
    return h, sent_cmds


_SR_BASE = {
    "champion": "Tristana", "key": "primary",
    "runes": {"keystone": "Press the Attack", "primary": "Precision",
              "secondary": "Domination"},
    "summoner_spells": [4, 7],
    "item_ids": ["6675", "3094", "3036"],
}


@pytest.mark.parametrize("key", sorted(_SR_PUSH_CMD))
@pytest.mark.parametrize("value,expected", _SR_ROWS, ids=_ids(_SR_ROWS))
def test_sr_draft_push_flag_contract(monkeypatch, key, value, expected):
    h, sent = _sr_apply(monkeypatch, _with(_SR_BASE, key, value))
    cmd = _SR_PUSH_CMD[key]
    if expected == "reject":
        assert h.status == 400, f"{key}={value!r} was accepted"
        assert h.json() == {"error": "bad_push_flag", "field": key}
        assert sent == [], "a rejected body must not enqueue anything"
        return
    assert h.status == 200
    assert (cmd in sent) is expected, f"{key}={value!r} -> sent {sent}"
    for other, other_cmd in _SR_PUSH_CMD.items():
        if other != key:
            assert other_cmd in sent, "one flag must not move its siblings"


# ========================================================== 2. ds-preview
def _ds_seam_bools():
    from dashboard.routes_state import _DS_PREVIEW_SEAM_BOOLS
    return _DS_PREVIEW_SEAM_BOOLS


_DS_ROWS = _cases(default_on=False)


@pytest.mark.parametrize("key", [
    "exempt_offclass_by_win", "prefer_kit_axis_by_win",
    "prefer_survivability_by_win", "assume_magic_burst",
    "assume_passive_as_stacks", "apply_target_vuln",
    "assume_missing_hp_heal_amp", "widen_carry_pool",
])
@pytest.mark.parametrize("value,expected", _DS_ROWS, ids=_ids(_DS_ROWS))
def test_ds_preview_bool_seam_contract(key, value, expected):
    from dashboard.routes_state import _serve_ds_preview_post

    assert key in _ds_seam_bools(), "param list drifted from the route"
    ranked = {"ok": True, "scorer": "dps", "archetype": "carry",
              "ranked": [], "fell_back": False}
    body = _with({"champion": "Ezreal", "mode": "SR", "level": 11,
                  "target_armor": 80.0, "target_mr": 30.0,
                  "target_max_hp": 2000.0, "target_bonus_hp": 500.0},
                 key, value)
    h = _Handler()
    with mock.patch("core.daemon_slayer_client.rank_for_primary_archetype",
                    return_value=ranked) as m_rk, \
            mock.patch("core.archetype_picks.get_archetype_for",
                       return_value={"primary": "carry"}):
        _serve_ds_preview_post(h, body)
    if expected == "reject":
        assert h.status == 400, f"{key}={value!r} was accepted"
        assert h.json() == {"error": "bad_flag", "field": key}
        assert not m_rk.called, "a rejected body must not reach the ranker"
        return
    assert h.status == 200
    kwargs = m_rk.call_args.kwargs
    if expected:
        assert kwargs.get(key) is True
    else:
        assert key not in kwargs, f"{key}={value!r} forwarded {kwargs.get(key)!r}"


# ======================================================== 3. coach toggle
_COACH_ROWS = _cases(default_on=False)


@pytest.fixture
def coach_cfg(tmp_path, monkeypatch):
    """Redirect coach_settings.json to tmp_path (core/cost_tracker.py
    `_COACH_CFG`, written by `set_coach_disabled`) and hand the route a
    tracker whose persistence is the real method against that path."""
    from core import cost_tracker

    cfg = tmp_path / "coach_settings.json"
    monkeypatch.setattr(cost_tracker, "_COACH_CFG", cfg)
    fake = types.SimpleNamespace(
        set_coach_disabled=lambda mode, disabled:
            cost_tracker.CostTracker.set_coach_disabled(None, mode, disabled))
    monkeypatch.setattr(cost_tracker, "get_tracker", lambda: fake)
    real = cost_tracker.Path(cost_tracker.__file__).resolve().parent.parent
    assert cfg.resolve() != (real / "config" / "coach_settings.json").resolve()
    return cfg


def _coach_mode():
    from core.cost_tracker import GATES
    return GATES[0]


@pytest.mark.parametrize("value,expected", _COACH_ROWS, ids=_ids(_COACH_ROWS))
def test_coach_toggle_disabled_contract(coach_cfg, value, expected):
    from core.cost_tracker import CFG_COACH_DISABLED_MODES
    from dashboard.routes_coach import _serve_coach_toggle_post

    mode = _coach_mode()
    # Start in the OPPOSITE state so every accepted row provably moves it.
    start = [] if expected is True else [mode]
    coach_cfg.write_text(json.dumps({CFG_COACH_DISABLED_MODES: start}),
                         encoding="utf-8")
    before = coach_cfg.read_bytes()
    h = _Handler()
    _serve_coach_toggle_post(h, _with({"mode": mode}, "disabled", value))
    if expected == "reject":
        assert h.status == 400, f"disabled={value!r} was accepted"
        assert h.json() == {"error": "bad_flag", "field": "disabled"}
        assert coach_cfg.read_bytes() == before, "rejected body changed disk"
        return
    assert h.status == 200
    persisted = json.loads(coach_cfg.read_text(encoding="utf-8"))
    assert (mode in persisted[CFG_COACH_DISABLED_MODES]) is expected


@pytest.mark.parametrize("value", _AMBIGUOUS)
@pytest.mark.parametrize("start_disabled", [False, True])
def test_coach_toggle_rejected_body_leaves_persisted_bytes(
        coach_cfg, value, start_disabled):
    from core.cost_tracker import CFG_COACH_DISABLED_MODES
    from dashboard.routes_coach import _serve_coach_toggle_post

    mode = _coach_mode()
    coach_cfg.write_text(json.dumps(
        {CFG_COACH_DISABLED_MODES: [mode] if start_disabled else [],
         "other": {"kept": 1}}, indent=2), encoding="utf-8")
    before = coach_cfg.read_bytes()
    h = _Handler()
    _serve_coach_toggle_post(h, {"mode": mode, "disabled": value})
    assert h.status == 400
    assert coach_cfg.read_bytes() == before


def test_coach_toggle_dev_panel_body_still_works(coach_cfg):
    """web/js/panels/dev.js sends `{mode: gate, disabled: !cbx.checked}` -
    a real JSON bool. Both directions must keep working."""
    from core.cost_tracker import CFG_COACH_DISABLED_MODES
    from dashboard.routes_coach import _serve_coach_toggle_post

    mode = _coach_mode()
    for disabled in (True, False):
        h = _Handler()
        _serve_coach_toggle_post(h, {"mode": mode, "disabled": disabled})
        assert h.status == 200
        persisted = json.loads(coach_cfg.read_text(encoding="utf-8"))
        assert (mode in persisted[CFG_COACH_DISABLED_MODES]) is disabled


# ===================================================== 4. archetype clear
_ARCH_ROWS = _cases(default_on=False)


@pytest.fixture
def picks_tmp(tmp_path, monkeypatch):
    from core import archetype_picks

    monkeypatch.setattr(archetype_picks, "_PICKS_PATH",
                        tmp_path / "cs_archetype_picks.json")
    monkeypatch.setattr(archetype_picks, "_DATA_DIR", tmp_path)
    archetype_picks._invalidate_picks_cache()
    yield archetype_picks
    archetype_picks._invalidate_picks_cache()


@pytest.mark.parametrize("value,expected", _ARCH_ROWS, ids=_ids(_ARCH_ROWS))
def test_archetype_clear_contract(picks_tmp, value, expected):
    from dashboard.routes_archetype import _serve_archetype_post

    picks_tmp.save_archetype_pick("Aatrox", primary="tank")
    h = _Handler()
    _serve_archetype_post(h, _with({"champion": "Aatrox", "primary": "mage"},
                                   "clear", value))
    loaded = picks_tmp.get_archetype_for("Aatrox")
    if expected == "reject":
        assert h.status == 400, f"clear={value!r} was accepted"
        assert h.json() == {"error": "bad_flag", "field": "clear"}
        assert loaded["primary"] == "tank", "rejected body moved the pick"
        return
    assert h.status == 200
    body = h.json()
    if expected:
        assert body.get("cleared") is True
        assert loaded["source"] == "default"
    else:
        assert "cleared" not in body, f"clear={value!r} cleared the pick"
        assert loaded["primary"] == "mage"


# ============================================== 5. build-plan reset_overrides
_BP_ROWS = _cases(default_on=False)


@pytest.mark.parametrize("value,expected", _BP_ROWS, ids=_ids(_BP_ROWS))
def test_build_plan_reset_overrides_contract(monkeypatch, value, expected):
    from core.build_planner import replan
    from dashboard import routes_build_plan
    from tests.test_item_overrides_persist import _CHAMP, _route_seed_fn

    monkeypatch.setattr(routes_build_plan, "_seed_fn_factory",
                        lambda **_kw: _route_seed_fn)
    snapshot_reads: list = []
    real_from_snapshot = replan.ItemOverrideStore.from_snapshot

    def _spy(snap, *a, **kw):
        snapshot_reads.append(snap)
        return real_from_snapshot(snap, *a, **kw)

    monkeypatch.setattr(replan.ItemOverrideStore, "from_snapshot",
                        staticmethod(_spy))
    snap = {"3094": {"shift": -3, "deferred": False,
                     "keep": False, "silenced": False}}
    h = _Handler()
    routes_build_plan._serve_build_plan(
        h, _with({"champion": _CHAMP, "items": [], "overrides": snap},
                 "reset_overrides", value))
    body = h.json()
    if expected == "reject":
        assert h.status == 400, f"reset_overrides={value!r} was accepted"
        assert body["error"] == "bad_flag"
        assert body["field"] == "reset_overrides"
        assert body["ok"] is False
        assert snapshot_reads == []
        return
    assert h.status == 200
    assert body["ok"] is True
    # ON means the snapshot is ignored; OFF / absent means it is honoured.
    assert (snapshot_reads == []) is expected, (
        f"reset_overrides={value!r} -> snapshot reads {snapshot_reads}")
