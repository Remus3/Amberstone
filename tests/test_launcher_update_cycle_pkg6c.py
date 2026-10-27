# arch: PKG-6c update cycle - rollback game gate (H-A) | section=tests | frozen=no
"""PKG-6c: the plausible highs the review after PKG-6b round 5 found
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

Every root is tmp_path; no network (the updater suite's socket tripwire);
the supervisor and main.py are simulated in the injected sleep / probes.
"""
from __future__ import annotations

import time

from ops.launcher import update_cycle as uc
from ops.launcher import updater as up
from tests.test_launcher_update_hardening_pkg6b import (
    Clock,
    Script,
    Sim,
    _applied,
    _cycle,
    _half_deploy,
    _lost_sim,
    _setup,
    _sup_requests,
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
    """Nothing to interrupt: the gate holds only a main.py that is up and
    ready, so a held rollback runs at once when main.py goes down - game or
    not."""
    root, src = _setup(tmp_path)
    clock = Clock()
    game, off = [None], [0.0]
    assert _lost_then_game(root, src, clock, game, off).status == "deferred"
    res = uc.resume_cycle(root, clock=clock, sleep=Sim(root, clock),
                          now=lambda: time.time() + off[0],
                          health=Script(clock, lambda t: sample("r1", alive=False)),
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
