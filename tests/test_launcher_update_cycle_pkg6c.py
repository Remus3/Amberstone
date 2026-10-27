# arch: PKG-6c update cycle - rollback game gate (H-A) + /api/state readiness (H-B) | section=tests | frozen=no
"""PKG-6c: the two plausible highs the review after PKG-6b round 5 found
(LEDGER 1934), fixed test-first.

  H-A a lost / interrupted apply rolled back with no idle / game gate
      (update_cycle.py _after_finish -> _recover; updater.recover is "Not
      game-gated: the app is already down", which is false here), so a
      supervisor rollback could restart main.py in champ select or a live
      game. Now: while main.py is up and ready, the rollback waits for the
      same full gate apply uses (game process, health flags, liveclient,
      LCU phase), recorded as `recover_due` in update_cycle.json and taken
      by the next idle cycle. A main.py that is down has nothing to
      interrupt: the rollback runs at once. The sibling - completing an
      interrupted recover - waits the same way.
  H-B readiness read health.json + /api/health only, never /api/state, so a
      release whose state builder 500s on every call verified and was kept,
      and every later cycle needs a fresh 200 /api/state, so none ran. Now
      the default readiness needs a 200 JSON /api/state. The H2 variant: an
      unreadable /api/state held a failed restart's rollback forever (the
      shell retried a sent check only on an idle state it never got). Now a
      positive game / LCU signal still holds it for as long as it lasts,
      but an unreadable state holds it at most UNREADABLE_HOLD_S, measured
      across cycles; a readable state in between restarts that clock.

Every root is tmp_path; no network (the updater suite's socket tripwire);
the supervisor and main.py are simulated in the injected sleep / probes.
"""
from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path

import pytest

from ops.launcher import update_cycle as uc
from ops.launcher import updater as up
from tests.test_launcher_update_hardening_pkg6b import (
    Clock,
    Script,
    Services,
    Sim,
    _applied,
    _cycle,
    _half_deploy,
    _lost_sim,
    _owed,
    _resume,
    _setup,
    _sup_requests,
    no_game,
    sample,
)
from tests.test_launcher_updater import (  # noqa: F401 - _no_network is an autouse fixture
    BASE_FILES,
    NEW_FILES,
    _no_network,
)

GAME = "process league of legends.exe"


def _recover_requests(root):
    return [n for n in _sup_requests(root) if n.startswith("launcher-recover-")]


# ------------------------------------------------ H-A lost / interrupted


def _lost_then_game(root, src, clock, game, off):
    """A deploy the worker never finished (LOST), and a game that started
    while it ran: the apply itself was idle-gated, the rollback is not yet."""
    inner = _lost_sim(root, clock, off, quit=False)

    def sleep(seconds):
        inner(seconds)
        if off[0]:
            game[0] = GAME
    return _cycle(root, src, clock, sleep, Script(clock, lambda t: sample("r1")),
                  now=lambda: time.time() + off[0], game_check=lambda: game[0],
                  finish_timeout_s=30)


def test_ha_a_lost_deploy_waits_out_a_game_before_the_rollback(tmp_path):
    root, src = _setup(tmp_path)
    clock = Clock()
    game, off = [None], [0.0]
    res = _lost_then_game(root, src, clock, game, off)
    assert res.status == "deferred" and res.exit_code == 3, res.to_dict()
    assert res.code == "game_live" and GAME in res.detail
    assert _recover_requests(root) == [], "no supervisor rollback while main.py serves a game"
    assert (root / "core" / "a.py").read_bytes() == NEW_FILES["core/a.py"], "nothing restored yet"
    assert up.read_state(root).get("recovering") is None
    due = uc.read_cycle(root)["recover_due"]
    assert due["version"] == "1.1.0" and due["bad"] is True
    assert uc.read_cycle(root)["bad_versions"] == {}, "not judged before it is rolled back"
    # A new `run` while the game lasts holds the same rollback; nothing new deploys.
    res = _cycle(root, src, clock, Sim(root, clock), Script(clock, lambda t: sample("r1")),
                 now=lambda: time.time() + off[0], game_check=lambda: game[0])
    assert res.status == "deferred", res.to_dict()
    assert not list((root / "ops" / "runtime" / "deploy_requests").glob("*.json"))
    # The game ends: the next resume rolls back (offline here, so the tree
    # itself shows it), marks the release bad and clears the record.
    game[0] = None
    res = uc.resume_cycle(root, clock=clock, sleep=Sim(root, clock),
                          now=lambda: time.time() + off[0],
                          health=Script(clock, lambda t: sample("r1")), serving=lambda: True,
                          supervisor_alive=lambda: False, game_check=lambda: game[0])
    assert res.status == "recovered", res.to_dict()
    assert (root / "core" / "a.py").read_bytes() == BASE_FILES["core/a.py"]
    assert not (root / "core" / "b.py").exists()
    assert up.installed_version(root) == "1.0.0"
    assert "1.1.0" in uc.read_cycle(root)["bad_versions"]
    assert uc.read_cycle(root)["recover_due"] is None


def test_ha_an_interrupted_deploy_waits_out_champ_select_on_the_default_gate(
        tmp_path, monkeypatch):
    root, src = _setup(tmp_path)
    clock = Clock()
    wall = [1_000_000.0]

    def quit_mid_deploy(seconds):
        clock.t += seconds
        wall[0] += seconds
        d = root / "ops" / "runtime" / "deploy_requests"
        for req in sorted(d.glob("*.json")):
            _half_deploy(root, type("R", (), {"request_id": req.stem, "request_path": req})())
    res = _cycle(root, src, clock, quit_mid_deploy, Script(clock, lambda t: sample("r1")),
                 now=lambda: wall[0], uptime=lambda: wall[0], finish_timeout_s=30)
    assert res.status == "pending"
    wall[0] += up.DEPLOYING_STALE_S + 60
    monkeypatch.setattr(uc.up, "game_live", lambda *a, **k: None)
    phase = ["ChampSelect"]
    monkeypatch.setattr(uc, "fetch_api_state", lambda r: {"lcu": {"phase": phase[0]}})
    kw = dict(clock=clock, sleep=quit_mid_deploy, now=lambda: wall[0], uptime=lambda: wall[0],
              health=Script(clock, lambda t: sample("r1")), serving=lambda: True,
              supervisor_alive=lambda: True, finish_timeout_s=30)
    res = uc.resume_cycle(root, **kw)   # game_check=None: the default full gate
    assert res.status == "deferred" and res.exit_code == 3, res.to_dict()
    assert "ChampSelect" in res.detail
    assert _recover_requests(root) == []
    assert uc.read_cycle(root)["recover_due"]["version"] == "1.1.0"
    phase[0] = "Lobby"
    res = uc.resume_cycle(root, **kw)
    assert res.status == "recovered", res.to_dict()
    assert any(n.endswith("-rollback.json") for n in _recover_requests(root))
    assert up.installed_version(root) == "1.0.0"


def test_ha_a_down_main_py_rolls_back_a_held_lost_deploy(tmp_path):
    """Nothing to interrupt: a held rollback runs at once when main.py is
    DOWN - game or not. Round 2 (review H1): down = its process is dead,
    health.json is missing, or the heartbeat is past the supervisor's 15 s."""
    root, src = _setup(tmp_path)
    clock = Clock()
    game, off = [None], [0.0]
    assert _lost_then_game(root, src, clock, game, off).status == "deferred"
    res = uc.resume_cycle(root, clock=clock, sleep=Sim(root, clock),
                          now=lambda: time.time() + off[0],
                          health=Script(clock, lambda t: sample("r1", alive=False,
                                                                pid_alive=False)),
                          serving=lambda: False, supervisor_alive=lambda: False,
                          game_check=lambda: game[0])
    assert res.status == "recovered", res.to_dict()
    assert (root / "core" / "a.py").read_bytes() == BASE_FILES["core/a.py"]


def _killed_before_requests(root, monkeypatch):
    real = up._write_json
    calls = []

    def flaky(path, data):
        if "supervisor_requests" in str(path) and not calls:
            calls.append(1)
            raise KeyboardInterrupt("killed before the first request")
        return real(path, data)
    monkeypatch.setattr(up, "_write_json", flaky)
    try:
        up.recover(root)
    except KeyboardInterrupt:
        pass
    monkeypatch.setattr(up, "_write_json", real)
    assert up.read_state(root)["recovering"]["requests"] is None


def test_ha_completing_an_interrupted_recover_waits_out_a_game(tmp_path, monkeypatch):
    """The sibling: a recover killed before its supervisor requests is
    completed by the next resume - which writes them and so restarts
    main.py. That waits for the gate too."""
    root = _applied(tmp_path)
    _killed_before_requests(root, monkeypatch)
    clock = Clock()
    game = [GAME]
    kw = dict(clock=clock, sleep=Sim(root, clock), health=Script(clock, lambda t: sample("r1")),
              serving=lambda: True, supervisor_alive=lambda: True,
              game_check=lambda: game[0])
    res = uc.resume_cycle(root, **kw)
    assert res.status == "deferred" and res.exit_code == 3, res.to_dict()
    assert _recover_requests(root) == []
    assert up.installed_version(root) == "1.1.0"
    assert uc.read_cycle(root)["recover_due"]["version"] == "1.1.0"
    game[0] = None
    res = uc.resume_cycle(root, **kw)
    assert res.status == "recovered", res.to_dict()
    assert any(n.endswith("-rollback.json") for n in _recover_requests(root))
    assert up.installed_version(root) == "1.0.0"
    assert uc.read_cycle(root)["recover_due"] is None


# ------------------------------------------------ H-B /api/state readiness


def test_hb_the_default_readiness_needs_a_200_api_state(tmp_path, monkeypatch):
    """/api/health answers (the old readiness) but the state builder 500s:
    the release is not ready, so it is rolled back and marked bad."""
    monkeypatch.setattr(uc.sh, "fetch_health_origin", lambda *a, **k: "https://127.0.0.1:8888")
    state = [None]
    monkeypatch.setattr(uc, "fetch_api_state", lambda r: state[0])
    root, src = _setup(tmp_path)
    clock = Clock()
    res = _cycle(root, src, clock, Sim(root, clock), Script(clock, lambda t: sample("r2")),
                 serving=None, health_timeout_s=90)
    assert res.status == "recovered", res.to_dict()
    assert "1.1.0" in uc.read_cycle(root)["bad_versions"]
    # positive control: the same release with a 200 /api/state verifies
    state[0] = {"lcu": {"phase": "Lobby"}, "health": {}, "liveclient": {}}
    root2, src2 = _setup(tmp_path / "b")
    res = _cycle(root2, src2, clock, Sim(root2, clock), Script(clock, lambda t: sample("r2")),
                 serving=None, health_timeout_s=90)
    assert res.status == "applied", res.to_dict()


def _failing(clock):
    return Services(clock, lambda n, t: {"restarted": False, "healthy": False, "pid": None})


def test_hb_an_unreadable_state_holds_a_failed_restart_only_for_a_bounded_time(
        tmp_path, monkeypatch):
    root, _src, clock = _owed(tmp_path)
    monkeypatch.setattr(uc.up, "game_live", lambda *a, **k: None)
    monkeypatch.setattr(uc, "fetch_api_state", lambda r: None)
    wall = [time.time()]
    kw = dict(restarts_sent=True, health_timeout_s=60, game_check=None, now=lambda: wall[0])
    res = _resume(root, clock, _failing(clock), **kw)
    assert res.status == "deferred", res.to_dict()   # round 5 H2: held at first
    wall[0] += uc.UNREADABLE_HOLD_S - 5
    assert _resume(root, clock, _failing(clock), **kw).status == "deferred"
    assert up.installed_version(root) == "1.1.0"
    wall[0] += 10
    res = _resume(root, clock, _failing(clock), **kw)
    assert res.status == "recovered", res.to_dict()
    assert up.installed_version(root) == "1.0.0"


def test_hb_a_readable_state_restarts_the_unreadable_clock(tmp_path, monkeypatch):
    root, _src, clock = _owed(tmp_path)
    monkeypatch.setattr(uc.up, "game_live", lambda *a, **k: None)
    state = [None]
    monkeypatch.setattr(uc, "fetch_api_state", lambda r: state[0])
    wall = [time.time()]
    kw = dict(restarts_sent=True, health_timeout_s=60, game_check=None, now=lambda: wall[0])
    assert _resume(root, clock, _failing(clock), **kw).status == "deferred"
    wall[0] += uc.UNREADABLE_HOLD_S - 10
    state[0] = {"lcu": {"phase": "ChampSelect"}}
    assert _resume(root, clock, _failing(clock), **kw).status == "deferred"
    wall[0] += 20
    state[0] = None
    res = _resume(root, clock, _failing(clock), **kw)
    assert res.status == "deferred", "the unreadable clock restarted at the readable sample"
    # the new episode, sampled within the gap (round 2 M1), runs out its own hold
    wall[0] += uc.UNREADABLE_HOLD_S / 2
    assert _resume(root, clock, _failing(clock), **kw).status == "deferred"
    wall[0] += uc.UNREADABLE_HOLD_S / 2 + 1
    assert _resume(root, clock, _failing(clock), **kw).status == "recovered"


def test_hb_a_positive_game_signal_holds_past_the_bound(tmp_path):
    root, _src, clock = _owed(tmp_path)
    wall = [time.time()]
    kw = dict(restarts_sent=True, health_timeout_s=60, game_check=lambda: GAME,
              now=lambda: wall[0])
    assert _resume(root, clock, _failing(clock), **kw).status == "deferred"
    wall[0] += 10 * uc.UNREADABLE_HOLD_S
    assert _resume(root, clock, _failing(clock), **kw).status == "deferred"
    assert up.installed_version(root) == "1.1.0"


def test_hb_an_idle_main_py_rolls_back_a_failed_restart(tmp_path):
    root, _src, clock = _owed(tmp_path)
    res = _resume(root, clock, _failing(clock), restarts_sent=True, health_timeout_s=60,
                  game_check=no_game)
    assert res.status == "recovered", res.to_dict()


# ================================ round 2 (the high-only review of 940e2fcda)
#
# H1 the rollback hold read "main.py is down" from ONE readiness sample: a
#    heartbeat older than the 5 s READINESS bound, or one tick whose state
#    provider raised, skipped the whole game gate - so a 6-10 s main.py stall
#    mid-game let the supervisor rollback restart main.py during the game.
#    Down is now: the process is dead, health.json is missing, or the
#    heartbeat is older than the supervisor's own 15 s stale threshold.
# M1 the unreadable-state clock survived busy stretches the cycle never saw,
#    so the first unreadable sample of a NEW episode released the hold at once.
# S1 the /api/state probe waits as long as the shell's own poll (4 s).


def _held_lost_deploy(tmp_path):
    root, src = _setup(tmp_path)
    clock = Clock()
    game, off = [None], [0.0]
    assert _lost_then_game(root, src, clock, game, off).status == "deferred"
    return root, clock, game, off


def _resume_held(root, clock, game, off, health):
    return uc.resume_cycle(root, clock=clock, sleep=Sim(root, clock),
                           now=lambda: time.time() + off[0], health=health,
                           serving=lambda: True, supervisor_alive=lambda: False,
                           game_check=lambda: game[0])


@pytest.mark.parametrize("stalled", [
    {"age_s": 6.0},                     # a 6 s stall: past readiness, not the supervisor's
    {"age_s": 15.0},                    # right at the supervisor's threshold
    {"ready": False},                   # one tick whose state provider raised
    {"alive": False},                   # a heartbeat that says alive=false, pid alive
])
def test_r2_h1_a_stalled_main_py_in_a_game_still_holds_the_rollback(tmp_path, stalled):
    root, clock, game, off = _held_lost_deploy(tmp_path)
    assert game[0] == GAME
    res = _resume_held(root, clock, game, off, Script(clock, lambda t: sample("r1", **stalled)))
    assert res.status == "deferred" and res.exit_code == 3, res.to_dict()
    assert GAME in res.detail
    assert (root / "core" / "a.py").read_bytes() == NEW_FILES["core/a.py"], "not rolled back"
    assert uc.read_cycle(root)["recover_due"]["version"] == "1.1.0"


@pytest.mark.parametrize("down", [
    {"age_s": 16.0, "pid_alive": False},   # the reviewer's case: 16 s old, process dead
    {"age_s": 16.0},                       # past the supervisor's own stale restart
    {"pid_alive": False},                  # the process is gone, whatever the beat says
])
def test_r2_h1_a_main_py_that_is_really_down_is_rolled_back_in_a_game(tmp_path, down):
    root, clock, game, off = _held_lost_deploy(tmp_path)
    res = _resume_held(root, clock, game, off, Script(clock, lambda t: sample("r1", **down)))
    assert res.status == "recovered", res.to_dict()
    assert (root / "core" / "a.py").read_bytes() == BASE_FILES["core/a.py"]


def test_r2_h1_the_default_probe_missing_is_down_torn_is_not(tmp_path):
    """health.json missing = down (rolled back in a game); present but torn /
    locked = unknown, so the game gate runs (held)."""
    root, clock, game, off = _held_lost_deploy(tmp_path)
    health = root / "ops" / "runtime" / "health.json"
    health.write_text('{"alive": tr', encoding="ascii")   # a torn read
    res = _resume_held(root, clock, game, off, None)
    assert res.status == "deferred", res.to_dict()
    assert uc.readiness(root).get("missing") is not True
    health.unlink()
    assert uc.readiness(root)["missing"] is True
    res = _resume_held(root, clock, game, off, None)
    assert res.status == "recovered", res.to_dict()


def test_r2_h1_the_threshold_is_the_supervisors_own():
    cfg = json.loads((Path(__file__).resolve().parent.parent / "ops" / "rc_config.json")
                     .read_text(encoding="utf-8"))
    assert uc.MAIN_DOWN_STALE_S == float(cfg["max_heartbeat_age_seconds"]) == 15.0
    assert uc.MAIN_DOWN_STALE_S > uc.HEARTBEAT_STALE_S


def test_r2_m1_a_new_unreadable_episode_does_not_inherit_an_old_clock(tmp_path, monkeypatch):
    root, _src, clock = _owed(tmp_path)
    monkeypatch.setattr(uc.up, "game_live", lambda *a, **k: None)
    monkeypatch.setattr(uc, "fetch_api_state", lambda r: None)
    wall = [time.time()]
    kw = dict(restarts_sent=True, health_timeout_s=60, game_check=None, now=lambda: wall[0])
    assert _resume(root, clock, _failing(clock), **kw).status == "deferred"
    # An hour the cycle never sampled (a game the shell saw as busy): the
    # next unreadable sample starts a NEW episode, it does not release.
    wall[0] += 3600
    res = _resume(root, clock, _failing(clock), **kw)
    assert res.status == "deferred", res.to_dict()
    assert up.installed_version(root) == "1.1.0"
    # ... and that episode, sampled inside the gap, runs out its own hold.
    wall[0] += 150
    assert _resume(root, clock, _failing(clock), **kw).status == "deferred"
    wall[0] += 151
    assert _resume(root, clock, _failing(clock), **kw).status == "recovered"


def test_r2_s1_the_state_probe_waits_as_long_as_the_shells_poll(monkeypatch):
    main_js = (Path(__file__).resolve().parent.parent / "rc-shell" / "src" / "main.js") \
        .read_text(encoding="utf-8")
    shell_ms = int(re.search(r'originRequest\(resolvedOrigin, "/api/state", (\d+),', main_js)
                   .group(1))
    assert shell_ms >= 4000
    seen = []

    class Opener:
        def open(self, url, timeout):
            seen.append((url, timeout))
            raise OSError("no server in a test")

    monkeypatch.setattr(uc.sh, "fetch_health_origin", lambda *a, **k: "https://127.0.0.1:8888")
    monkeypatch.setattr(uc.urllib.request, "build_opener", lambda *a: Opener())
    assert uc.fetch_api_state(Path(os.getcwd())) is None
    assert len(seen) == 1 and seen[0][0] == "https://127.0.0.1:8888/api/state"
    assert seen[0][1] * 1000 >= shell_ms, "the cycle gives up no sooner than the shell's poll"

